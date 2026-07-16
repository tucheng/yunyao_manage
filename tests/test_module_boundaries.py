import ast
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class ModuleBoundaryTests(unittest.TestCase):
    def test_recipe_routes_do_not_use_wildcard_imports(self):
        for path in (ROOT / "routes" / "recipe").glob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            wildcard_imports = [
                node for node in ast.walk(tree)
                if isinstance(node, ast.ImportFrom)
                and any(alias.name == "*" for alias in node.names)
            ]
            self.assertEqual([], wildcard_imports, path.name)

    def test_large_route_modules_delegate_to_services(self):
        expectations = {
            "works.py": ("services.work_search", "services.work_recipe", "services.work_images"),
            "materials.py": ("services.material_catalog", "services.user_materials"),
            "admin.py": ("services.settings_store",),
        }
        for filename, modules in expectations.items():
            source = (ROOT / "routes" / filename).read_text(encoding="utf-8")
            for module in modules:
                self.assertIn(f"from {module} import", source, filename)

    def test_recipe_routes_use_explicit_architecture_boundaries(self):
        expectations = {
            "catalog.py": ("services.recipe_queries", "services.recipe_serializers"),
            "commands.py": ("services.recipe_access", "services.recipe_version"),
            "detail.py": ("services.recipe_access",),
            "feeds.py": ("services.recipe_serializers",),
            "reviews.py": ("services.recipe_access", "services.recipe_serializers"),
        }
        recipe_routes = ROOT / "routes" / "recipe"
        for filename, modules in expectations.items():
            source = (recipe_routes / filename).read_text(encoding="utf-8")
            for module in modules:
                self.assertIn(f"from {module} import", source, filename)


if __name__ == "__main__":
    unittest.main()
