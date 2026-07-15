import os
import unittest

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("AUTH_SECRET", "test-secret-that-is-at-least-32-bytes")

from challenge_store import ChallengeStore


class ChallengeStoreTests(unittest.TestCase):
    def test_one_time_code_can_only_be_consumed_once(self):
        store = ChallengeStore("test", redis_url="")
        store.set("email:user@example.com", "123456", 60)
        self.assertTrue(store.verify("email:user@example.com", "123456"))
        self.assertFalse(store.verify("email:user@example.com", "123456"))

    def test_non_consuming_check_keeps_code_for_next_instance(self):
        store = ChallengeStore("test", redis_url="")
        store.set("captcha-id", "AB12", 60)
        self.assertTrue(store.verify("captcha-id", "AB12", consume=False))
        self.assertTrue(store.verify("captcha-id", "AB12"))

    def test_wrong_code_does_not_consume_correct_code(self):
        store = ChallengeStore("test", redis_url="")
        store.set("phone:13800000000", "654321", 60)
        self.assertFalse(store.verify("phone:13800000000", "000000"))
        self.assertTrue(store.verify("phone:13800000000", "654321"))


if __name__ == "__main__":
    unittest.main()
