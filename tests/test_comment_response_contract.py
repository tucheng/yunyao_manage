import unittest
from types import SimpleNamespace

from routes.recipe.reviews import _user_names as recipe_user_names
from routes.work_comments import _user_names as work_user_names
from schemas import ReviewOut, WorkCommentOut


class CommentResponseContractTests(unittest.TestCase):
    def test_recipe_comments_return_both_user_names(self):
        user = SimpleNamespace(username="login_name", nickname="")
        self.assertEqual(
            {"username": "login_name", "nickname": ""},
            recipe_user_names(user),
        )
        self.assertIn("username", ReviewOut.model_fields)
        self.assertIn("nickname", ReviewOut.model_fields)

    def test_work_comments_return_both_user_names(self):
        user = SimpleNamespace(username="login_name", nickname="display_name")
        self.assertEqual(
            {"username": "login_name", "nickname": "display_name"},
            work_user_names(7, {7: user}),
        )
        self.assertIn("username", WorkCommentOut.model_fields)
        self.assertIn("nickname", WorkCommentOut.model_fields)


if __name__ == "__main__":
    unittest.main()
