import json

from sqlalchemy.orm import Session

from color_names import color_name_in_range, get_color_range_config
from models import Recipe, Work
from services.settings_store import get_json_setting

TEMPERATURE_RANGE_CONFIG = [
    {"value": "low", "label": "低温", "min": 0, "max": 1099,
     "description": "低于 1100℃，常见于低温釉、彩绘和二次烧成。"},
    {"value": "middle", "label": "中温", "min": 1100, "max": 1249,
     "description": "1100-1249℃，常见于中温釉和日用陶瓷烧成。"},
    {"value": "high", "label": "高温", "min": 1250, "max": 1450,
     "description": "1250℃ 及以上，常见于高温瓷、青瓷和部分还原烧。"},
]
SURFACE_OPTIONS = ["亮光", "丝光", "蜡光", "柔光", "无光", "磨砂"]
TRANSPARENCY_OPTIONS = ["高透", "微透", "半透", "不透"]
KILN_TYPE_OPTIONS = ["电窑", "气窑", "柴窑", "乐烧"]
HAS_RECIPE_OPTIONS = [
    {"value": "yes", "label": "有配方"},
    {"value": "no", "label": "无配方"},
]


def temperature_value(raw: str):
    if not raw:
        return None
    digits = ""
    for char in str(raw):
        if char.isdigit() or (char == "." and "." not in digits):
            digits += char
        elif digits:
            break
    try:
        return float(digits) if digits else None
    except ValueError:
        return None


def get_temperature_ranges(db: Session) -> list:
    return get_json_setting(db, "work_search_temperature_ranges", TEMPERATURE_RANGE_CONFIG)


def get_color_ranges(db: Session) -> list:
    return get_json_setting(db, "work_search_color_ranges", get_color_range_config())


def temperature_in_range(raw: str, range_value: str, temperature_ranges: list) -> bool:
    temperature = temperature_value(raw)
    if temperature is None:
        return False
    return any(
        item["min"] <= temperature <= item["max"]
        for item in temperature_ranges if item["value"] == range_value
    )


def color_name_in_ranges(name: str, range_value: str, color_ranges: list) -> bool:
    if not name or not range_value:
        return False
    for item in color_ranges:
        if item.get("value") == range_value:
            return name in (item.get("names") or [])
    return color_name_in_range(name, range_value)


def work_has_color_range(work: Work, range_value: str, color_ranges: list) -> bool:
    if not range_value:
        return True
    try:
        colors = json.loads(work.glaze_colors) if work.glaze_colors else []
    except (TypeError, ValueError):
        colors = []
    return isinstance(colors, list) and any(
        color_name_in_ranges((item or {}).get("name", ""), range_value, color_ranges)
        for item in colors if isinstance(item, dict)
    )


def same_filter_value(raw: str, selected: str) -> bool:
    selected_value = str(selected or "").strip()
    if not selected_value:
        return True
    return str(raw or "").strip() == selected_value


def work_matches_search_filters(
    work: Work,
    recipe: Recipe | None,
    category: str,
    atmosphere: str,
    body_material: str,
    kiln_type: str,
    temperature: str,
    temperature_range: str,
    surface: str,
    transparency: str,
    color_range: str,
    has_recipe: str,
    temperature_ranges: list,
    color_ranges: list,
) -> bool:
    values = (
        (work.category, category),
        (work.atmosphere, atmosphere),
        (work.body_material, body_material),
        (work.kiln_type, kiln_type),
        (work.surface, surface),
        (work.transparency, transparency),
        (work.temperature, temperature),
    )
    if any(selected and not same_filter_value(raw, selected) for raw, selected in values):
        return False
    if temperature_range and not temperature_in_range(work.temperature, temperature_range, temperature_ranges):
        return False
    if color_range and not work_has_color_range(work, color_range, color_ranges):
        return False
    if has_recipe == "yes" and recipe is None:
        return False
    if has_recipe == "no" and recipe is not None:
        return False
    return True


def distinct_work_values(db: Session, column) -> list[str]:
    return [row[0] for row in db.query(column).filter(
        column != "", column.isnot(None),
    ).distinct().order_by(column).all()]
