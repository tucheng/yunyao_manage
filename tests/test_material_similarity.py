import unittest

from services.material_similarity import oxide_similarity


class MaterialSimilarityTests(unittest.TestCase):
    def test_identical_profiles_are_exactly_100(self):
        self.assertEqual(oxide_similarity((60, 25, 15), (60, 25, 15)), 100.0)

    def test_different_actual_amounts_are_not_100(self):
        score = oxide_similarity((0, 99, 0), (0, 65.4, 34.6))
        self.assertEqual(score, 65.73)

    def test_non_identical_profiles_never_round_to_100(self):
        self.assertEqual(oxide_similarity((100,), (99.999,)), 99.99)

    def test_empty_profiles_have_no_similarity(self):
        self.assertEqual(oxide_similarity((0, 0), (0, 0)), 0.0)


if __name__ == "__main__":
    unittest.main()
