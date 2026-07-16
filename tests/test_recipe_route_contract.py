import unittest

from routes.recipes import router


EXPECTED_ROUTES = {
    ("POST", "/recipes/init-sequence", "init_recipe_sequence"),
    ("GET", "/recipes/search/config", "recipe_search_config"),
    ("GET", "/recipes/count", "count_recipes"),
    ("GET", "/recipes", "list_recipes"),
    ("GET", "/recipes/", "list_recipes"),
    ("GET", "/recipes/feed/following", "following_recipes"),
    ("GET", "/recipes/mine", "my_recipes"),
    ("POST", "/recipes/{recipe_id}/favorite", "toggle_favorite"),
    ("POST", "/recipes/{recipe_id}/like", "toggle_recipe_like"),
    ("POST", "/recipes/{recipe_id}/view", "record_recipe_view"),
    ("GET", "/recipes/favorites", "favorite_recipes"),
    ("GET", "/recipes/user/{user_id}", "get_user"),
    ("GET", "/recipes/search", "search"),
    ("GET", "/recipes/by-no/{recipe_no}", "get_recipe_by_no"),
    ("GET", "/recipes/{recipe_id}", "get_recipe"),
    ("GET", "/recipes/{recipe_id}/link-preview", "get_recipe_link_preview"),
    ("GET", "/recipes/{recipe_id}/seger", "get_recipe_seger"),
    ("GET", "/recipes/{recipe_id}/versions", "list_recipe_versions"),
    ("GET", "/recipes/{recipe_id}/versions/{version_id}", "get_recipe_version_detail"),
    ("POST", "/recipes/{recipe_id}/versions/{version_id}/restore", "restore_recipe_version"),
    ("POST", "/recipes/", "create_recipe"),
    ("PUT", "/recipes/{recipe_id}", "update_recipe"),
    ("DELETE", "/recipes/{recipe_id}", "delete_recipe"),
    ("POST", "/recipes/review", "create_review"),
    ("GET", "/recipes/{recipe_id}/reviews", "list_reviews"),
}


def iter_routes(current_router, prefix=""):
    """Expand FastAPI 0.139's deferred included-router entries."""
    for route in current_router.routes:
        if hasattr(route, "methods"):
            yield route, f"{prefix}{route.path}"
            continue
        context = route.include_context
        yield from iter_routes(route.original_router, f"{prefix}{context.prefix}")


class RecipeRouteContractTests(unittest.TestCase):
    def test_recipe_route_contract_is_complete_and_unique(self):
        actual = {
            (method, path, route.name)
            for route, path in iter_routes(router)
            for method in route.methods
        }
        self.assertEqual(EXPECTED_ROUTES, actual)
        self.assertEqual(len(EXPECTED_ROUTES), len(actual))

    def test_static_get_routes_are_registered_before_recipe_id_route(self):
        get_paths = [
            path
            for route, path in iter_routes(router)
            if "GET" in route.methods
        ]
        dynamic_index = get_paths.index("/recipes/{recipe_id}")
        for static_path in (
            "/recipes/search/config",
            "/recipes/count",
            "/recipes/feed/following",
            "/recipes/mine",
            "/recipes/favorites",
            "/recipes/search",
            "/recipes/by-no/{recipe_no}",
        ):
            self.assertLess(get_paths.index(static_path), dynamic_index)


if __name__ == "__main__":
    unittest.main()
