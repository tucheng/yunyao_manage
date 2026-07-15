import unittest

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from database import Base
from models import Recipe, User, UserLevel, UserUsageQuota
from services.recipe_access import require_recipe_reader


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
        self.private_recipe = Recipe(user_id=self.owner.id, title="私密", visibility="private")
        self.db.add_all([self.public_recipe, self.private_recipe])
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


if __name__ == "__main__":
    unittest.main()

