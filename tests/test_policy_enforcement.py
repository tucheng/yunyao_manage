import unittest

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database import Base
from models import User
from services.user_quota import consume_quota


class PolicyEnforcementTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine)()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_muted_user_cannot_publish_through_api(self):
        user = User(username="muted", password="", is_muted=True)
        self.db.add(user)
        self.db.commit()
        for kind in ("recipe", "work"):
            with self.assertRaises(HTTPException) as caught:
                consume_quota(self.db, user, kind)
            self.assertEqual(caught.exception.status_code, 403)


if __name__ == "__main__":
    unittest.main()
