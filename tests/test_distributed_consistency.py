import asyncio
import os
import threading
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("AUTH_SECRET", "test-secret-that-is-at-least-32-bytes")

from fastapi import HTTPException
from starlette.requests import Request

from auth_utils import create_access_token
from challenge_store import ChallengeStore
from database import SessionLocal, engine
from models import RedeemCode, User
from rate_limiter import POLICIES, Policy, RateLimiter
from routes.redeem import RedeemBody, redeem_code
from services.user_quota import ensure_system_levels


def request_with_token(token: str, path: str = "/redeem/use") -> Request:
    return Request({
        "type": "http", "method": "POST", "path": path, "query_string": b"",
        "headers": [(b"authorization", f"Bearer {token}".encode())],
        "client": ("198.51.100.17", 1234), "server": ("test", 80), "scheme": "http",
    })


@unittest.skipUnless(os.getenv("TEST_REDIS_URL"), "distributed Redis test")
class RedisConsistencyTests(unittest.TestCase):
    def test_code_created_by_one_instance_is_consumed_by_another(self):
        redis_url = os.environ["TEST_REDIS_URL"]
        first = ChallengeStore("ci", redis_url=redis_url)
        second = ChallengeStore("ci", redis_url=redis_url)
        identity = f"ci:{uuid.uuid4().hex}"
        first.set(identity, "123456", 30)
        self.assertTrue(second.verify(identity, "123456"))
        self.assertFalse(first.verify(identity, "123456"))

    def test_rate_limit_is_shared_between_instances(self):
        old = POLICIES["auth"]
        POLICIES["auth"] = Policy(1, 60)
        first, second = RateLimiter(), RateLimiter()

        async def run():
            self.assertIsNone(await first.check(request_with_token("", "/auth/login")))
            blocked = await second.check(request_with_token("", "/auth/login"))
            self.assertEqual(blocked.status_code, 429)
            await first.close()
            await second.close()

        try:
            asyncio.run(run())
        finally:
            POLICIES["auth"] = old


@unittest.skipUnless(engine.dialect.name == "mysql", "requires transactional MySQL")
class MySqlConsistencyTests(unittest.TestCase):
    def test_same_redeem_code_cannot_be_spent_twice(self):
        marker = uuid.uuid4().hex[:12]
        db = SessionLocal()
        try:
            ensure_system_levels(db)
            user = User(username=f"ci-{marker}", password="", level_id=1)
            code = RedeemCode(code=f"CI{marker.upper()}", days=1, max_uses=1, current_uses=0, is_active=True)
            db.add_all([user, code])
            db.commit()
            db.refresh(user)
            token = create_access_token(user)
            user_id = user.id
            code_text = code.code
        finally:
            db.close()

        barrier = threading.Barrier(2)

        def spend_once():
            session = SessionLocal()
            try:
                barrier.wait(timeout=5)
                redeem_code(RedeemBody(code=code_text), request_with_token(token), session)
                return "ok"
            except HTTPException as exc:
                session.rollback()
                return f"http-{exc.status_code}"
            finally:
                session.close()

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _n: spend_once(), range(2)))
        self.assertEqual(results.count("ok"), 1, results)

        check = SessionLocal()
        try:
            stored = check.query(RedeemCode).filter(RedeemCode.code == code_text).one()
            self.assertEqual(stored.current_uses, 1)
            self.assertEqual(check.query(User).filter(User.id == user_id).count(), 1)
        finally:
            check.close()
