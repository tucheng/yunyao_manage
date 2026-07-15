import json
import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database import Base
from models import FiringCurve, Recipe, RecipeIngredient, User
from routes.curves import DEFAULT_USER_CURVES, create_default_user_curves
from schemas import RecipeCreate, RecipeOut, RecipeUpdate


class FiringCurveContractTests(unittest.TestCase):
    def test_new_users_receive_the_two_named_curves_idempotently(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(
            engine,
            tables=[User.__table__, FiringCurve.__table__],
        )
        session = sessionmaker(bind=engine)()
        try:
            create_default_user_curves(session, 42)
            create_default_user_curves(session, 42)
            curves = session.query(FiringCurve).filter_by(user_id=42).order_by(FiringCurve.sort_order).all()
            self.assertEqual(
                [curve.name for curve in curves],
                ["普通中温电窑烧制曲线", "陶泥烧制曲线数据"],
            )
            for curve in curves:
                segments = json.loads(curve.segments)
                self.assertTrue(segments)
                self.assertTrue(all({"temp", "time", "status"} <= set(segment) for segment in segments))
        finally:
            session.close()
            engine.dispose()

    def test_recipe_contract_exposes_optional_curve(self):
        self.assertIn("curve_id", Recipe.__table__.columns)
        self.assertIn("curve_id", RecipeCreate.model_fields)
        self.assertIn("curve_id", RecipeUpdate.model_fields)
        self.assertIn("curve_id", RecipeOut.model_fields)
        self.assertIn("curve_data", RecipeOut.model_fields)

    def test_default_curve_definitions_remain_exactly_two(self):
        self.assertEqual(len(DEFAULT_USER_CURVES), 2)

    def test_encrypted_ingredient_amount_column_has_room_for_ciphertext(self):
        self.assertGreaterEqual(RecipeIngredient.__table__.c.amount.type.length, 500)


if __name__ == "__main__":
    unittest.main()
