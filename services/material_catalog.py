import math

from fastapi import HTTPException, Request
from sqlalchemy.orm import Session

from models import Material
from services.material_analysis import normalize_material_name

MOLECULE_FLOAT_FIELDS = (
    "sio2", "al2o3", "fe2o3", "tio2", "cao", "mgo", "na2o", "k2o",
    "zno", "b2o3", "p2o5", "li2o", "mno2", "coo", "sno2", "cuo",
    "cr2o3", "pbo", "bao", "sro", "loi", "thermal_expansion",
)
MOLECULE_TEXT_FIELDS = ("name_en", "formula", "molecular_weight", "category")


def catalog_payload(material: Material) -> dict:
    fields = (
        "id", "name", "normalized_name", "name_en", "normalized_name_en", "source", "source_id", "formula",
        "molecular_weight", "category", "sio2", "al2o3", "fe2o3", "tio2",
        "cao", "mgo", "na2o", "k2o", "zno", "b2o3", "p2o5", "li2o",
        "mno2", "coo", "sno2", "cuo", "cr2o3", "pbo", "bao", "sro",
        "loi", "thermal_expansion", "status", "created_from", "submitted_at", "reviewed_at",
        "review_note", "recalculated_at",
    )
    result = {field: getattr(material, field, None) for field in fields}
    for field in ("name_en", "source", "formula", "molecular_weight", "category"):
        result[field] = result[field] or ""
    result["is_analysis"] = bool(material.is_analysis)
    result["is_primitive"] = bool(material.is_primitive)
    return result


def request_user_id(request: Request) -> int:
    user_id = getattr(request.state, "user_id", None)
    if not user_id:
        raise HTTPException(status_code=401, detail="请先登录")
    return user_id


def normalized_material_name(name: str) -> str:
    return normalize_material_name(name)


def material_name_conflict(
    db: Session, name: str, name_en: str = "", exclude_id: int | None = None,
) -> Material | None:
    from services.material_analysis import find_material_name_conflict

    return find_material_name_conflict(
        db, name=name, name_en=name_en, exclude_id=exclude_id,
    )


def clean_molecule_data(data: dict, *, partial: bool = False) -> dict:
    cleaned = {}
    if not partial or "name" in data:
        name = str(data.get("name", "")).strip()
        if not normalized_material_name(name):
            raise HTTPException(status_code=400, detail="材料名不能为空")
        if len(name) > 200:
            raise HTTPException(status_code=400, detail="材料名不能超过200个字符")
        cleaned["name"] = name
    max_lengths = {"name_en": 200, "formula": 200, "molecular_weight": 50, "category": 50}
    for field in MOLECULE_TEXT_FIELDS:
        if field not in data:
            continue
        value = str(data.get(field) or "").strip()
        if len(value) > max_lengths[field]:
            raise HTTPException(status_code=400, detail=f"{field}内容过长")
        cleaned[field] = value
    for field in MOLECULE_FLOAT_FIELDS:
        if field not in data:
            continue
        raw = data.get(field)
        if raw in (None, ""):
            cleaned[field] = None
            continue
        try:
            value = float(raw)
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=f"{field}必须是数字") from exc
        if not math.isfinite(value):
            raise HTTPException(status_code=400, detail=f"{field}必须是有效数字")
        if field != "thermal_expansion" and not 0 <= value <= 100:
            raise HTTPException(status_code=400, detail=f"{field}必须在0到100之间")
        cleaned[field] = value
    return cleaned
