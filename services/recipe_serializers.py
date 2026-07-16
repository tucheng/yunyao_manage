from image_utils import normalize_image_url, parse_image_list
from models import Recipe, Review, User, Work


def user_names(user: User | None) -> dict[str, str]:
    return {
        "username": (user.username or "") if user else "",
        "nickname": (user.nickname or "") if user else "",
    }


def review_payload(
    review: Review,
    user: User | None,
    *,
    replies: list | None = None,
    recipe_title: str | None = None,
) -> dict:
    payload = {
        "id": review.id,
        "parent_id": review.parent_id,
        "user_id": review.user_id,
        "recipe_id": review.recipe_id,
        "rating": review.rating,
        "content": review.content or "",
        "image": review.image or "",
        "body_material": review.body_material or "",
        "kiln_type": review.kiln_type or "",
        "kiln_type_other": review.kiln_type_other or "",
        "temperature": review.temperature or "",
        "created_at": review.created_at,
        **user_names(user),
        "replies": replies or [],
    }
    if recipe_title is not None:
        payload["recipe_title"] = recipe_title
    return payload


def search_review_payload(
    review: Review,
    user: User | None,
    recipe: Recipe | None,
) -> dict:
    return {
        "id": review.id,
        "recipe_id": review.recipe_id,
        "user_id": review.user_id,
        "image": review.image,
        "content": review.content or "",
        "body_material": review.body_material or "",
        "kiln_type": review.kiln_type or "",
        "temperature": review.temperature or "",
        "recipe_title": recipe.title if recipe else "",
        "nickname": user.nickname if user else f"用户{review.user_id}",
        "created_at": review.created_at,
    }


def favorite_recipe_payload(recipe: Recipe, user: User | None) -> dict:
    return {
        "id": recipe.id,
        "user_id": recipe.user_id,
        "type": "recipe",
        "title": recipe.title,
        "recipe_no": recipe.recipe_no or "",
        "category": recipe.category or "",
        "cover": normalize_image_url(recipe.cover) or (parse_image_list(recipe.images) or [""])[0],
        "author_name": user.nickname if user else "",
        "created_at": recipe.created_at.isoformat() if recipe.created_at else "",
    }


def favorite_work_payload(work: Work, user: User | None) -> dict:
    return {
        "id": work.id,
        "user_id": work.user_id,
        "type": "work",
        "title": (work.description or "作品").split("\n")[0][:30],
        "cover": normalize_image_url(work.image),
        "author_name": user.nickname if user else "",
        "body_material": work.body_material or "",
        "created_at": work.created_at.isoformat() if work.created_at else "",
    }
