import os
import unittest

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("AUTH_SECRET", "test-secret-that-is-at-least-32-bytes")

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from auth_utils import hash_password, verify_password
from database import Base
from models import User
from routes.auth import ChangePasswordRequest, change_password


class ChangePasswordTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine)()
        self.user = User(username="owner", password=hash_password("old-pass"))
        self.db.add(self.user)
        self.db.commit()
        self.db.refresh(self.user)

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_change_password_checks_old_password_and_revokes_tokens(self):
        previous_version = self.user.token_version or 0
        result = change_password(
            ChangePasswordRequest(
                old_password="old-pass",
                new_password="new-pass",
                confirm_password="new-pass",
            ),
            self.user,
            self.db,
        )
        self.assertEqual(result["message"], "密码修改成功")
        self.assertTrue(verify_password("new-pass", self.user.password)[0])
        self.assertEqual(self.user.token_version, previous_version + 1)

    def test_change_password_rejects_wrong_old_password(self):
        with self.assertRaises(HTTPException) as caught:
            change_password(
                ChangePasswordRequest(
                    old_password="wrong-pass",
                    new_password="new-pass",
                    confirm_password="new-pass",
                ),
                self.user,
                self.db,
            )
        self.assertEqual(caught.exception.detail, "旧密码错误")


if __name__ == "__main__":
    unittest.main()
