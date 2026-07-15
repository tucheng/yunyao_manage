"""Shared, expiring one-time challenge storage for multi-instance deployments."""

from __future__ import annotations

import hashlib
import hmac
import threading
import time

from app_config import AUTH_SECRET, IS_PRODUCTION, REDIS_URL

_VERIFY_SCRIPT = """
local current = redis.call('GET', KEYS[1])
if not current or current ~= ARGV[1] then return 0 end
if ARGV[2] == '1' then redis.call('DEL', KEYS[1]) end
return 1
"""


class ChallengeStore:
    def __init__(self, namespace: str, redis_url: str | None = None) -> None:
        self.namespace = namespace
        self.redis_url = REDIS_URL if redis_url is None else redis_url
        self._redis = None
        self._memory: dict[str, tuple[str, float]] = {}
        self._lock = threading.Lock()

    def _client(self):
        if not self.redis_url:
            if IS_PRODUCTION:
                raise RuntimeError("Redis is required for production challenge storage")
            return None
        if self._redis is None:
            from redis import Redis
            self._redis = Redis.from_url(self.redis_url, decode_responses=True)
        return self._redis

    def _key(self, identity: str) -> str:
        digest = hashlib.sha256(identity.encode()).hexdigest()
        return f"yunyao:challenge:{self.namespace}:{digest}"

    @staticmethod
    def _value(code: str) -> str:
        return hmac.new(AUTH_SECRET.encode(), code.strip().encode(), hashlib.sha256).hexdigest()

    def set(self, identity: str, code: str, ttl_seconds: int) -> None:
        key, value = self._key(identity), self._value(code)
        client = self._client()
        if client is not None:
            client.setex(key, ttl_seconds, value)
            return
        with self._lock:
            self._memory[key] = (value, time.monotonic() + ttl_seconds)

    def verify(self, identity: str, code: str, *, consume: bool = True) -> bool:
        key, candidate = self._key(identity), self._value(code)
        client = self._client()
        if client is not None:
            return bool(client.eval(_VERIFY_SCRIPT, 1, key, candidate, "1" if consume else "0"))
        with self._lock:
            stored = self._memory.get(key)
            if not stored or stored[1] < time.monotonic():
                self._memory.pop(key, None)
                return False
            if not hmac.compare_digest(stored[0], candidate):
                return False
            if consume:
                self._memory.pop(key, None)
            return True


verification_codes = ChallengeStore("verification")
captcha_codes = ChallengeStore("captcha")
