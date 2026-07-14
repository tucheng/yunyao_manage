import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from models import RecipeSequence
from services.recipe_number import generate_recipe_no


class RecipeNumberTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        RecipeSequence.__table__.create(self.engine)
        self.session = sessionmaker(bind=self.engine)()

    def tearDown(self):
        self.session.close()
        self.engine.dispose()

    def test_generates_consecutive_recipe_numbers(self):
        self.assertEqual("A001", generate_recipe_no(self.session))
        self.assertEqual("A002", generate_recipe_no(self.session))

    def test_rolls_from_z999_to_four_digit_a_sequence(self):
        self.session.add(RecipeSequence(letter="Z", counter=999, digits=3))
        self.session.flush()

        self.assertEqual("A0001", generate_recipe_no(self.session))

        sequence = self.session.query(RecipeSequence).one()
        self.assertEqual(("A", 1, 4), (sequence.letter, sequence.counter, sequence.digits))


if __name__ == "__main__":
    unittest.main()
