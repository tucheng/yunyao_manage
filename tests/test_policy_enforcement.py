import unittest

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database import Base
from models import Recipe, User, UserLevel, UserUsageQuota
from routes.recipe.commands import create_recipe
from schemas import RecipeCreate
from services.business_errors import QuotaExceeded
from services.user_quota import business_today, consume_quota


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

    def test_create_recipe_is_blocked_when_daily_quota_is_exhausted(self):
        level = UserLevel(id=2, name="普通用户", max_recipes=1, max_works=1, max_views=1)
        user = User(username="quota-used", password="", level_id=2)
        self.db.add_all([level, user])
        self.db.flush()
        self.db.add(UserUsageQuota(
            user_id=user.id,
            quota_date=business_today(),
            recipe_remaining=0,
            work_remaining=1,
            recipe_view_remaining=1,
        ))
        self.db.commit()

        with self.assertRaises(QuotaExceeded) as caught:
            create_recipe(RecipeCreate(title="不应创建"), user.id, self.db)

        self.assertEqual(403, caught.exception.status_code)
        self.assertEqual("QUOTA_EXHAUSTED", caught.exception.code)
        self.assertEqual("recipe", caught.exception.quota_kind)
        self.assertEqual(0, self.db.query(Recipe).count())


if __name__ == "__main__":
    unittest.main()
