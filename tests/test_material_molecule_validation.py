import unittest
from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database import Base
from models import Material
from routes.materials import _has_oxide_data, submit_material_molecule, update_material_molecule


class MaterialMoleculeValidationTests(unittest.TestCase):
    def test_requires_a_positive_oxide_value(self):
        self.assertFalse(_has_oxide_data({}))
        self.assertFalse(_has_oxide_data({"sio2": None, "al2o3": 0}))
        self.assertTrue(_has_oxide_data({"sio2": 0, "al2o3": 12.5}))

    def test_loi_does_not_count_as_oxide_data(self):
        self.assertFalse(_has_oxide_data({"loi": 8.5}))

    def test_edit_marks_material_modified_before_submission(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        db = sessionmaker(bind=engine)()
        try:
            material = Material(user_id=7, name="测试料", status="initial", is_active=True)
            db.add(material)
            db.commit()
            request = SimpleNamespace(state=SimpleNamespace(user_id=7))

            result = update_material_molecule(
                material.id, {"name": "测试料", "sio2": 55}, request, db,
            )
            self.assertEqual(result["status"], "modified")

            submit_result = submit_material_molecule(material.id, request, db)
            self.assertEqual(submit_result["status"], "submitted")
        finally:
            db.close()
            engine.dispose()


if __name__ == "__main__":
    unittest.main()
