import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database import Base
from models import Material, MaterialFamily, Recipe, RecipeIngredient, RecipeSeger
from security import encrypt
from seger_calculator import calculate_seger
from services.material_analysis import (
    composition_fingerprint,
    normalize_material_name,
    merge_materials,
    resolve_material,
    rollback_material_merge,
)


class MaterialAnalysisWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine)()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_normalizes_unicode_width_case_and_whitespace(self):
        self.assertEqual(normalize_material_name(" Ｆerro\u3000熔块 4113 "), "ferro熔块4113")
        self.assertEqual(normalize_material_name("Céradel"), normalize_material_name("Ceradel"))

    def test_missing_material_is_created_once_and_owned_by_recipe_user(self):
        first, created = resolve_material(
            self.db, name="测试 长石", owner_user_id=7, created_from="glazy",
        )
        self.db.flush()
        second, created_again = resolve_material(
            self.db, name="测试长石", owner_user_id=99, created_from="frontend",
        )
        self.assertTrue(created)
        self.assertFalse(created_again)
        self.assertEqual(second.id, first.id)
        self.assertEqual(first.user_id, 7)
        self.assertEqual(first.status, "initial")

    def test_conflicting_family_without_default_is_not_guessed(self):
        family = MaterialFamily(canonical_name="钾长石", normalized_name="钾长石")
        self.db.add(family)
        self.db.flush()
        left = Material(family_id=family.id, name="钾长石", normalized_name="钾长石", sio2=64, status="recalculated")
        right = Material(family_id=family.id, name="钾 长石", normalized_name="钾长石", sio2=71, status="recalculated")
        self.db.add_all((left, right))
        self.db.flush()
        material, created = resolve_material(self.db, name="钾长石", create_missing=False)
        self.assertIsNone(material)
        self.assertFalse(created)

    def test_fingerprint_distinguishes_unknown_from_zero(self):
        unknown = Material(name="A", sio2=None)
        explicit_zero = Material(name="A", sio2=0)
        self.assertNotEqual(composition_fingerprint(unknown), composition_fingerprint(explicit_zero))

    def test_seger_excludes_unreviewed_material_then_uses_approved_variant(self):
        family = MaterialFamily(canonical_name="测试料", normalized_name="测试料")
        self.db.add(family)
        self.db.flush()
        material = Material(
            family_id=family.id, name="测试料", normalized_name="测试料",
            status="initial", sio2=60, al2o3=20, cao=20,
        )
        recipe = Recipe(user_id=1, title="测试配方", recipe_no="T001")
        self.db.add_all((material, recipe))
        self.db.flush()
        self.db.add(RecipeIngredient(
            recipe_id=recipe.id, material_id=material.id, name=encrypt("测试料"),
            amount=encrypt("100"), unit="%",
        ))
        self.db.commit()

        pending = calculate_seger(recipe.id, self.db)
        self.assertEqual(pending["calculation_status"], "pending_material")

        material = self.db.query(Material).filter(Material.id == material.id).first()
        material.status = "recalculated"
        self.db.commit()
        complete = calculate_seger(recipe.id, self.db)
        self.assertEqual(complete["calculation_status"], "complete")
        self.assertTrue(complete["seger_unified"])
        saved = self.db.query(RecipeSeger).filter(RecipeSeger.recipe_id == recipe.id).one()
        self.assertEqual(saved.calculation_status, "complete")

    def test_soft_merge_can_restore_recipe_ingredient_links(self):
        family = MaterialFamily(canonical_name="石英", normalized_name="石英")
        self.db.add(family)
        self.db.flush()
        source = Material(family_id=family.id, name="石 英", normalized_name="石英", sio2=99, status="recalculated")
        target = Material(family_id=family.id, name="石英", normalized_name="石英", sio2=99, status="recalculated")
        recipe = Recipe(user_id=1, title="合并测试", recipe_no="M001")
        self.db.add_all((source, target, recipe))
        self.db.flush()
        ingredient = RecipeIngredient(
            recipe_id=recipe.id, material_id=source.id, name=encrypt("石英"), amount=encrypt("100"), unit="%",
        )
        self.db.add(ingredient)
        self.db.commit()
        log = merge_materials(
            self.db, source=source, target=target, admin_user_id=None,
            reason="test", require_exact=True,
        )
        self.db.commit()
        self.assertEqual(self.db.get(RecipeIngredient, ingredient.id).material_id, target.id)
        self.assertFalse(self.db.get(Material, source.id).is_active)

        rollback_material_merge(self.db, log)
        self.assertEqual(self.db.get(RecipeIngredient, ingredient.id).material_id, source.id)
        self.assertTrue(self.db.get(Material, source.id).is_active)


if __name__ == "__main__":
    unittest.main()
