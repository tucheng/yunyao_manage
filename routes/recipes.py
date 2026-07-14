from fastapi import APIRouter

from routes.recipe import (
    catalog,
    commands,
    detail,
    feeds,
    interactions,
    reviews,
    sequence,
    versions,
)

router = APIRouter(tags=["釉料配方"])

# Keep fixed GET routes ahead of /{recipe_id}; Starlette matches in registration order.
router.include_router(sequence.router, prefix="/recipes")
router.include_router(catalog.router, prefix="/recipes")
router.include_router(feeds.router, prefix="/recipes")
router.include_router(interactions.router, prefix="/recipes")
router.include_router(detail.router, prefix="/recipes")
router.include_router(versions.router, prefix="/recipes")
router.include_router(commands.router, prefix="/recipes")
router.include_router(reviews.router, prefix="/recipes")
