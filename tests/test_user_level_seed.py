from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from models import UserLevel
from services.user_quota import SYSTEM_LEVEL_DEFAULTS, ensure_system_levels


def _new_level_session():
    engine = create_engine("sqlite://")
    UserLevel.__table__.create(engine)
    return Session(engine)


def test_system_level_defaults_match_the_initial_catalog():
    assert SYSTEM_LEVEL_DEFAULTS == {
        1: {"name": "会员试用者", "max_recipes": 10, "max_works": 50, "max_views": 10},
        2: {"name": "普通用户", "max_recipes": 1, "max_works": 50, "max_views": 5},
        3: {"name": "会员用户", "max_recipes": 50, "max_works": 100, "max_views": 100},
    }


def test_ensure_system_levels_creates_the_initial_catalog():
    with _new_level_session() as db:
        ensure_system_levels(db)
        levels = db.query(UserLevel).order_by(UserLevel.id).all()

        assert [
            (level.id, level.name, level.max_recipes, level.max_works, level.max_views, level.sort_order)
            for level in levels
        ] == [
            (1, "会员试用者", 10, 50, 10, 1),
            (2, "普通用户", 1, 50, 5, 2),
            (3, "会员用户", 50, 100, 100, 3),
        ]


def test_ensure_system_levels_preserves_admin_edited_quotas():
    with _new_level_session() as db:
        db.add(UserLevel(id=1, name="old name", max_recipes=99, max_works=98, max_views=97))
        db.flush()

        ensure_system_levels(db)
        level = db.get(UserLevel, 1)

        assert level.name == "会员试用者"
        assert (level.max_recipes, level.max_works, level.max_views) == (99, 98, 97)
