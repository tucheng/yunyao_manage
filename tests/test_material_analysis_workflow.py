import unittest
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database import Base
from models import Material, MaterialRecalculationLog, Recipe, RecipeIngredient, RecipeSeger
from security import encrypt
from seger_calculator import calculate_seger
from services.material_analysis import (
    find_material_name_conflict,
    normalize_material_name,
    prepare_material,
    recalculate_material_recipes,
    resolve_material,
)


class MaterialAnalysisWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine)()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def add_material(self, name, name_en="", **values):
        material = Material(name=name, name_en=name_en, status="recalculated", **values)
        prepare_material(self.db, material)
        self.db.flush()
        return material

    def test_normalization_removes_whitespace_only(self):
        self.assertEqual(normalize_material_name(" Ferro\u3000熔块 4113 "), "Ferro熔块4113")
        self.assertNotEqual(normalize_material_name("Céradel"), normalize_material_name("Ceradel"))
        self.assertNotEqual(normalize_material_name("Ferro"), normalize_material_name("ferro"))

    def test_both_names_must_match_when_both_are_supplied(self):
        first = self.add_material("长 石", "Feldspar A")
        second = self.add_material("长石", "Feldspar B")
        material, created = resolve_material(
            self.db, name="长石", name_en="Feldspar B", create_missing=False,
        )
        self.assertFalse(created)
        self.assertEqual(material.id, second.id)
        self.assertNotEqual(material.id, first.id)

    def test_single_name_matches_its_own_language_column(self):
        chinese = self.add_material("高 岭 土", "Kaolin")
        english = self.add_material("另一材料", "English Only")
        by_chinese, _ = resolve_material(self.db, name="高岭土", create_missing=False)
        by_english, _ = resolve_material(self.db, name="", name_en="EnglishOnly", create_missing=False)
        self.assertEqual(by_chinese.id, chinese.id)
        self.assertEqual(by_english.id, english.id)

    def test_missing_material_is_created_once_and_owned_by_recipe_user(self):
        first, created = resolve_material(
            self.db, name="测试 长石", name_en="Test Feldspar", owner_user_id=7, created_from="frontend",
        )
        self.db.flush()
        second, created_again = resolve_material(
            self.db, name="测试长石", name_en="TestFeldspar", owner_user_id=99,
        )
        self.assertTrue(created)
        self.assertFalse(created_again)
        self.assertEqual(second.id, first.id)
        self.assertEqual(first.user_id, 7)
        self.assertEqual(first.status, "initial")

    def test_duplicate_validation_uses_joint_chinese_and_english_names(self):
        original = self.add_material("氧 化 铝", "Alumina")
        self.assertEqual(
            find_material_name_conflict(self.db, name="氧化铝", name_en="Alumina").id,
            original.id,
        )
        self.assertIsNone(find_material_name_conflict(self.db, name="氧化铝", name_en="Aluminium Oxide"))

    def test_seger_excludes_initial_material_then_uses_recalculated_material(self):
        material = self.add_material("测试料", sio2=60, al2o3=20, cao=20)
        material.status = "initial"
        recipe = Recipe(user_id=1, title="测试配方", recipe_no="T001")
        self.db.add(recipe)
        self.db.flush()
        self.db.add(RecipeIngredient(
            recipe_id=recipe.id, material_id=material.id, name=encrypt("测试料"),
            amount=encrypt("100"), unit="%",
        ))
        self.db.commit()
        self.assertEqual(calculate_seger(recipe.id, self.db)["calculation_status"], "pending_material")
        material.status = "recalculated"
        self.db.commit()
        result = calculate_seger(recipe.id, self.db)
        self.assertEqual(result["calculation_status"], "complete")
        self.assertTrue(result["seger_unified"])
        self.assertEqual(self.db.query(RecipeSeger).filter_by(recipe_id=recipe.id).one().calculation_status, "complete")

    def test_recalculation_creates_one_summary_log(self):
        material = self.add_material("日志测试料", sio2=100)
        recipe = Recipe(user_id=1, title="日志配方", recipe_no="L001")
        self.db.add(recipe)
        self.db.flush()
        self.db.add(RecipeIngredient(
            recipe_id=recipe.id, material_id=material.id, name=encrypt("日志测试料"),
            amount=encrypt("100"), unit="%",
        ))
        self.db.commit()
        with patch("seger_calculator.calculate_seger", return_value={"calculation_status": "complete"}):
            result = recalculate_material_recipes(self.db, material, admin_user_id=9)
        self.assertEqual(result["total"], 1)
        log = self.db.query(MaterialRecalculationLog).one()
        self.assertEqual(log.material_id, material.id)
        self.assertEqual(log.admin_id, 9)
        self.assertEqual(log.affected_recipe_count, 1)
        self.assertEqual(log.success_count, 1)


if __name__ == "__main__":
    unittest.main()
