"""Distributed, route-aware rate limiting backed by Redis."""

from __future__ import annotations

import hashlib
import logging
import secrets
import time
from dataclasses import dataclass
from ipaddress import ip_address, ip_network

from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app_config import IS_PRODUCTION, RATE_LIMIT_ENABLED, REDIS_URL, TRUSTED_PROXY_IPS

logger = logging.getLogger("yunyao.rate_limit")

_SLIDING_WINDOW_SCRIPT = """
local key = KEYS[1]
local now = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local limit = tonumber(ARGV[3])
local member = ARGV[4]
redis.call('ZREMRANGEBYSCORE', key, 0, now - window)
local count = redis.call('ZCARD', key)
if count >= limit then
  local oldest = redis.call('ZRANGE', key, 0, 0, 'WITHSCORES')
  local retry = window
  if oldest[2] then retry = math.max(1, math.ceil((tonumber(oldest[2]) + window - now) / 1000)) end
  return {0, count, retry}
end
redis.call('ZADD', key, now, member)
redis.call('PEXPIRE', key, window)
return {1, count + 1, 0}
"""


@dataclass(frozen=True)
class Policy:
    requests: int
    seconds: int


POLICIES = {
    "auth": Policy(10, 60),
    "ocr": Policy(12, 60),
    "upload": Policy(20, 60),
    "write": Policy(60, 60),
    "admin": Policy(120, 60),
    "read": Policy(300, 60),
}


class RateLimiter:
    def __init__(self) -> None:
        self._redis = None
        self._trusted_networks = [ip_network(value, strict=False) for value in TRUSTED_PROXY_IPS]

    async def _client(self):
        if self._redis is None:
            if not REDIS_URL:
                return None
            from redis.asyncio import from_url
            self._redis = from_url(REDIS_URL, encoding="utf-8", decode_responses=True)
        return self._redis

    def client_ip(self, request: Request) -> str:
        peer = request.client.host if request.client else "unknown"
        try:
            trusted = any(ip_address(peer) in network for network in self._trusted_networks)
        except ValueError:
            trusted = False
        if trusted:
            forwarded = request.headers.get("x-forwarded-for", "").split(",", 1)[0].strip()
            if forwarded:
                return forwarded
        return peer

    @staticmethod
    def _group(request: Request) -> str:
        path = request.url.path
        if path.startswith("/auth/"):
            return "auth"
        if path.startswith("/ocr/"):
            return "ocr"
        if path.startswith("/upload/"):
            return "upload"
        if path.startswith(("/admin", "/redeem/admin")):
            return "admin"
        return "read" if request.method in {"GET", "HEAD", "OPTIONS"} else "write"

    async def check(self, request: Request) -> Response | None:
        if not RATE_LIMIT_ENABLED or request.method == "OPTIONS":
            return None
        client = await self._client()
        if client is None:
            if IS_PRODUCTION:
                return JSONResponse({"detail": "限流服务未配置"}, status_code=503)
            return None
        group = self._group(request)
        policy = POLICIES[group]
        now_ms = int(time.time() * 1000)
        identity = hashlib.sha256(self.client_ip(request).encode()).hexdigest()[:32]
        key = f"yunyao:rate:{group}:{identity}"
        member = f"{now_ms}:{secrets.token_hex(8)}"
        try:
            allowed, _used, retry_after = await client.eval(
                _SLIDING_WINDOW_SCRIPT, 1, key, now_ms, policy.seconds * 1000,
                policy.requests, member,
            )
        except Exception:
            logger.exception("Redis rate limiter unavailable")
            if IS_PRODUCTION:
                return JSONResponse({"detail": "限流服务暂不可用"}, status_code=503)
            return None
        if int(allowed):
            return None
        return JSONResponse(
            {"detail": "请求过于频繁，请稍后再试"}, status_code=429,
            headers={"Retry-After": str(retry_after), "X-RateLimit-Limit": str(policy.requests)},
        )

    async def close(self) -> None:
        if self._redis is not None:
            await self._redis.aclose()

    async def healthcheck(self) -> None:
        if not RATE_LIMIT_ENABLED:
            return
        client = await self._client()
        if client is None:
            if IS_PRODUCTION:
                raise RuntimeError("Redis rate limiter is not configured")
            return
        await client.ping()
