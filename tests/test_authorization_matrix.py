import asyncio
import json
import os
import unittest

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("AUTH_SECRET", "test-secret-that-is-at-least-32-bytes")

from fastapi import HTTPException
from starlette.requests import Request
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from auth_utils import create_access_token, current_admin, current_user
from database import Base
from models import User


def make_request(token="", query="", body=None):
    raw = json.dumps(body or {}).encode()
    sent = False

    async def receive():
        nonlocal sent
        if sent:
            return {"type": "http.request", "body": b"", "more_body": False}
        sent = True
        return {"type": "http.request", "body": raw, "more_body": False}

    headers = [(b"content-type", b"application/json")]
    if token:
        headers.append((b"authorization", f"Bearer {token}".encode()))
    return Request({
        "type": "http",
        "method": "POST",
        "path": "/private",
        "query_string": query.encode(),
        "headers": headers,
        "client": ("127.0.0.1", 1234),
        "server": ("test", 80),
        "scheme": "http",
    }, receive)


class AuthorizationMatrixTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine)()
        self.owner = User(username="owner", password="", is_admin=False)
        self.other = User(username="other", password="", is_admin=False)
        self.admin = User(username="admin", password="", is_admin=True)
        self.db.add_all([self.owner, self.other, self.admin])
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_anonymous_user_is_rejected(self):
        with self.assertRaises(HTTPException) as caught:
            asyncio.run(current_user(make_request(), self.db))
        self.assertEqual(caught.exception.status_code, 401)

    def test_resource_owner_identity_comes_from_token(self):
        token = create_access_token(self.owner)
        user = asyncio.run(current_user(make_request(token), self.db))
        self.assertEqual(user.id, self.owner.id)

    def test_normal_user_cannot_claim_another_user_id(self):
        token = create_access_token(self.owner)
        request = make_request(token, body={"user_id": self.other.id})
        with self.assertRaises(HTTPException) as caught:
            asyncio.run(current_user(request, self.db))
        self.assertEqual(caught.exception.status_code, 403)

    def test_admin_dependency_rejects_normal_user_and_accepts_admin(self):
        with self.assertRaises(HTTPException) as caught:
            asyncio.run(current_admin(self.owner))
        self.assertEqual(caught.exception.status_code, 403)
        self.assertEqual(asyncio.run(current_admin(self.admin)).id, self.admin.id)

    def test_token_version_revokes_existing_token(self):
        token = create_access_token(self.owner)
        self.owner.token_version = (self.owner.token_version or 0) + 1
        self.db.commit()
        with self.assertRaises(HTTPException) as caught:
            asyncio.run(current_user(make_request(token), self.db))
        self.assertEqual(caught.exception.status_code, 401)


if __name__ == "__main__":
    unittest.main()
