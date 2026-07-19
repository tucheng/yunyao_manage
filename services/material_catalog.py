import math

from fastapi import HTTPException, Request
from sqlalchemy.orm import Session

from models import Material
from seger_calculator import OXIDE_MW
from services.material_analysis import normalize_material_name

MOLECULE_FLOAT_FIELDS = (
    "sio2", "al2o3", "fe2o3", "tio2", "cao", "mgo", "na2o", "k2o",
    "zno", "b2o3", "p2o5", "li2o", "mno2", "coo", "sno2", "cuo",
    "cr2o3", "pbo", "bao", "sro", "loi", "thermal_expansion",
)
MOLECULE_TEXT_FIELDS = ("name_en", "formula", "molecular_weight", "category")
OXIDE_FORMULAS = {
    "sio2": "SiO2", "al2o3": "Al2O3", "fe2o3": "Fe2O3", "tio2": "TiO2",
    "cao": "CaO", "mgo": "MgO", "na2o": "Na2O", "k2o": "K2O",
    "zno": "ZnO", "b2o3": "B2O3", "p2o5": "P2O5", "li2o": "Li2O",
    "mno2": "MnO2", "coo": "CoO", "sno2": "SnO2", "cuo": "CuO",
    "cr2o3": "Cr2O3", "pbo": "PbO", "bao": "BaO", "sro": "SrO",
}


def derive_molecular_properties(values) -> tuple[str, str]:
    """Derive a normalized oxide formula and effective molar mass from weight percentages."""
    get_value = values.get if isinstance(values, dict) else lambda field: getattr(values, field, None)
    components = []
    total_mass = 0.0
    total_moles = 0.0
    for field, molecular_weight in OXIDE_MW.items():
        try:
            mass = float(get_value(field) or 0)
        except (TypeError, ValueError):
            continue
        if not math.isfinite(mass) or mass <= 0:
            continue
        moles = mass / molecular_weight
        components.append((field, moles))
        total_mass += mass
        total_moles += moles
    if not components or total_moles <= 0:
        return "", ""

    formula_parts = []
    formula_length = 0
    for field, moles in components:
        coefficient = moles / total_moles
        coefficient_text = f"{coefficient:.3f}".rstrip("0").rstrip(".")
        part = OXIDE_FORMULAS[field] if coefficient_text == "1" else f"{coefficient_text}{OXIDE_FORMULAS[field]}"
        added_length = len(part) + (1 if formula_parts else 0)
        if formula_length + added_length > 200:
            break
        formula_parts.append(part)
        formula_length += added_length

    effective_weight = total_mass / total_moles
    molecular_weight_text = f"{effective_weight:.4f}".rstrip("0").rstrip(".")
    return "·".join(formula_parts), molecular_weight_text


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
