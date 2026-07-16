import unittest

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from database import Base
from models import Recipe, User, UserLevel, UserUsageQuota
from services.recipe_access import require_recipe_reader
from services.user_quota import business_today, sync_level_quotas


class RecipeAccessPolicyTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine)()
        self.level = UserLevel(
            id=2,
            name="普通用户",
            max_recipes=1,
            max_works=1,
            max_views=2,
        )
        self.owner = User(username="owner", password="", level_id=2)
        self.viewer = User(username="viewer", password="", level_id=2)
        self.db.add_all([self.level, self.owner, self.viewer])
        self.db.flush()
        self.public_recipe = Recipe(user_id=self.owner.id, title="公开", visibility="public")
        self.second_public_recipe = Recipe(user_id=self.owner.id, title="公开二", visibility="public")
        self.third_public_recipe = Recipe(user_id=self.owner.id, title="公开三", visibility="public")
        self.private_recipe = Recipe(user_id=self.owner.id, title="私密", visibility="private")
        self.db.add_all([
            self.public_recipe,
            self.second_public_recipe,
            self.third_public_recipe,
            self.private_recipe,
        ])
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_private_recipe_is_hidden_from_non_owner(self):
        with self.assertRaises(HTTPException) as caught:
            require_recipe_reader(self.db, self.private_recipe, self.viewer.id, consume_quota=True)
        self.assertEqual(404, caught.exception.status_code)

    def test_public_recipe_consumes_only_one_daily_view(self):
        require_recipe_reader(self.db, self.public_recipe, self.viewer.id, consume_quota=True)
        require_recipe_reader(self.db, self.public_recipe, self.viewer.id, consume_quota=True)
        quota = self.db.query(UserUsageQuota).filter_by(user_id=self.viewer.id).one()
        self.assertEqual(1, quota.recipe_view_remaining)

    def test_owner_read_does_not_consume_view_quota(self):
        require_recipe_reader(self.db, self.private_recipe, self.owner.id, consume_quota=True)
        quota = self.db.query(UserUsageQuota).filter_by(user_id=self.owner.id).first()
        self.assertIsNone(quota)

    def test_new_recipe_view_is_blocked_after_daily_quota_is_exhausted(self):
        require_recipe_reader(self.db, self.public_recipe, self.viewer.id, consume_quota=True)
        require_recipe_reader(self.db, self.second_public_recipe, self.viewer.id, consume_quota=True)

        with self.assertRaises(HTTPException) as caught:
            require_recipe_reader(self.db, self.third_public_recipe, self.viewer.id, consume_quota=True)

        self.assertEqual(403, caught.exception.status_code)
        self.assertEqual("QUOTA_EXHAUSTED", caught.exception.code)
        self.assertEqual("recipe_view", caught.exception.quota_kind)
        self.assertEqual(0, caught.exception.remaining)

    def test_zero_view_level_blocks_even_a_recipe_viewed_earlier_today(self):
        require_recipe_reader(self.db, self.public_recipe, self.viewer.id, consume_quota=True)
        self.level.max_views = 0
        sync_level_quotas(
            self.db,
            self.level.id,
            {"max_recipes": 1, "max_works": 1, "max_views": 2},
            {"max_recipes": 1, "max_works": 1, "max_views": 0},
        )
        self.db.commit()

        with self.assertRaises(HTTPException) as caught:
            require_recipe_reader(self.db, self.public_recipe, self.viewer.id, consume_quota=True)
        self.assertEqual(403, caught.exception.status_code)

    def test_level_limit_change_updates_existing_daily_balance(self):
        self.db.add(UserUsageQuota(
            user_id=self.viewer.id,
            quota_date=business_today(),
            recipe_remaining=1,
            work_remaining=1,
            recipe_view_remaining=1,
        ))
        self.db.flush()
        synced = sync_level_quotas(
            self.db,
            self.level.id,
            {"max_recipes": 1, "max_works": 1, "max_views": 2},
            {"max_recipes": 1, "max_works": 1, "max_views": 4},
        )
        quota = self.db.query(UserUsageQuota).filter_by(user_id=self.viewer.id).one()
        self.assertEqual(1, synced)
        self.assertEqual(3, quota.recipe_view_remaining)


if __name__ == "__main__":
    unittest.main()
