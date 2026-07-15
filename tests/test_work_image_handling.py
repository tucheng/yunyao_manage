import unittest

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database import Base
from models import Recipe, User, UserLevel, Work
from routes.works import _sanitize_work_images, _set_work_recipe


class WorkImageHandlingTests(unittest.TestCase):
    def test_uses_uploaded_image_when_primary_is_blob(self):
        primary, images = _sanitize_work_images(
            "blob:http://127.0.0.1:5173/temporary",
            [
                "blob:http://127.0.0.1:5173/temporary",
                "/uploads/works/persisted.png",
            ],
        )

        self.assertEqual(primary, "/uploads/works/persisted.png")
        self.assertEqual(images, ["/uploads/works/persisted.png"])

    def test_preserves_durable_primary_and_deduplicates(self):
        primary, images = _sanitize_work_images(
            "https://cdn.example.com/works/cover.webp",
            [
                "https://cdn.example.com/works/cover.webp",
                "/media/works/detail.jpg",
            ],
        )

        self.assertEqual(primary, "https://cdn.example.com/works/cover.webp")
        self.assertEqual(
            images,
            [
                "https://cdn.example.com/works/cover.webp",
                "/media/works/detail.jpg",
            ],
        )

    def test_rejects_only_temporary_images(self):
        self.assertEqual(
            _sanitize_work_images(
                "blob:http://localhost/temp",
                ["data:image/png;base64,abc"],
            ),
            ("", []),
        )


class WorkRecipeLinkTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine)()
        self.db.add(UserLevel(id=2, name="普通用户", max_recipes=10, max_works=10, max_views=10))
        self.owner = User(username="recipe-owner", password="", level_id=2)
        self.viewer = User(username="work-owner", password="", level_id=2)
        self.db.add_all([self.owner, self.viewer])
        self.db.commit()
        self.public_recipe = Recipe(user_id=self.owner.id, title="公开配方", visibility="public", work_count=0)
        self.second_recipe = Recipe(user_id=self.owner.id, title="另一个配方", visibility="showoff", work_count=0)
        self.private_recipe = Recipe(user_id=self.owner.id, title="私密配方", visibility="private", work_count=0)
        self.work = Work(user_id=self.viewer.id, image="/uploads/works/a.jpg")
        self.db.add_all([self.public_recipe, self.second_recipe, self.private_recipe, self.work])
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_viewable_other_users_recipe_can_be_linked_without_double_counting(self):
        _set_work_recipe(self.db, self.work, self.public_recipe.id, self.viewer.id)
        _set_work_recipe(self.db, self.work, self.public_recipe.id, self.viewer.id)
        self.assertEqual(self.work.recipe_id, self.public_recipe.id)
        self.assertEqual(self.public_recipe.work_count, 1)

        _set_work_recipe(self.db, self.work, self.second_recipe.id, self.viewer.id)
        self.assertEqual(self.public_recipe.work_count, 0)
        self.assertEqual(self.second_recipe.work_count, 1)

        _set_work_recipe(self.db, self.work, None, self.viewer.id)
        self.assertIsNone(self.work.recipe_id)
        self.assertEqual(self.second_recipe.work_count, 0)

    def test_unviewable_private_recipe_cannot_be_linked(self):
        with self.assertRaises(HTTPException) as caught:
            _set_work_recipe(self.db, self.work, self.private_recipe.id, self.viewer.id)
        self.assertEqual(caught.exception.status_code, 404)


if __name__ == "__main__":
    unittest.main()
