"""
Seger formula calculation for ceramic glaze recipes.
Converts weight-based recipes to unified Seger molecular formula.

Usage:
    from seger_calculator import calculate_seger
    result = calculate_seger(recipe_id, db_session)
"""
import json
import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session
from encryption_utils import decrypt
from models import RecipeIngredient, CeramicMaterial, GlazyMaterial, RecipeSeger, Recipe

logger = logging.getLogger('yunyao')

# ============================================================
# Molecular weights of common oxides (g/mol)
# ============================================================
OXIDE_MW = {
    'sio2': 60.08,
    'al2o3': 101.96,
    'fe2o3': 159.69,
    'tio2': 79.87,
    'cao': 56.08,
    'mgo': 40.30,
    'na2o': 61.98,
    'k2o': 94.20,
    'zno': 81.38,
    'b2o3': 69.62,
    'p2o5': 141.94,
}

# ============================================================
# Molecular weights of common mineral formulas (total g/mol)
# ============================================================
MOLECULE_MW = {
    'K2O·Al2O3·6SiO2': 94.20 + 101.96 + 6 * 60.08,    # Orthoclase feldspar
    'Na2O·Al2O3·6SiO2': 61.98 + 101.96 + 6 * 60.08,    # Albite feldspar
    'CaO·Al2O3·2SiO2': 56.08 + 101.96 + 2 * 60.08,     # Anorthite feldspar
    'CaO·Al2O3·4SiO2': 56.08 + 101.96 + 4 * 60.08,     # 钙长石 low-Si variant
    'K2O·Al2O3·4SiO2': 94.20 + 101.96 + 4 * 60.08,     # 钾长石 low-Si variant
    '2CaO·MgO·4SiO2': 2 * 56.08 + 40.30 + 4 * 60.08,   # Diopside
    '3Al2O3·2SiO2': 3 * 101.96 + 2 * 60.08,             # Mullite
    'Al2O3·2SiO2·2H2O': 101.96 + 2 * 60.08 + 2 * 18.015,  # Kaolinite (approx)
    'MgO·SiO2': 40.30 + 60.08,                           # Enstatite
    'CaO·SiO2': 56.08 + 60.08,                           # Wollastonite
    'CaCO3': 56.08 + 44.01,                              # Calcium carbonate (CaO + CO2)
    'MgCO3': 40.30 + 44.01,                               # Magnesium carbonate
    'BaO·Al2O3·4SiO2': 153.33 + 101.96 + 4 * 60.08,    # Celsian
    'SrO·Al2O3·4SiO2': 103.62 + 101.96 + 4 * 60.08,    # 锶长石
    'Li2O·Al2O3·4SiO2': 29.88 + 101.96 + 4 * 60.08,    # Petalite
    'Li2O·Al2O3·8SiO2': 29.88 + 101.96 + 8 * 60.08,    # Spodumene
}

# ============================================================
# Column names in material models that hold oxide percentages
# ============================================================
OXIDE_COLUMNS = ['sio2', 'al2o3', 'fe2o3', 'tio2', 'cao', 'mgo',
                 'na2o', 'k2o', 'zno', 'b2o3', 'p2o5']

# Oxides classified as RO + R2O (flux / alkaline group)
# In traditional Seger: RO = CaO, MgO, ZnO, FeO, etc.; R2O = Na2O, K2O
# We use Fe2O3 as proxy since FeO data is rarely available separately
FLUX_OXIDES = ['na2o', 'k2o', 'cao', 'mgo', 'zno', 'fe2o3']

# ============================================================
# Helper
# ============================================================


def _get_oxide_value(material, oxide_col: str) -> float:
    """Get oxide percentage from a material ORM object, returning 0 if None."""
    return float(getattr(material, oxide_col, 0) or 0)


def _get_acid_base_note(ratio: float) -> str:
    """Generate acid-base note based on SiO2/Al2O3 ratio."""
    if ratio <= 0:
        return ""
    if ratio < 5:
        return "碱性偏强，釉面偏哑光，可能出现缩釉、针孔等问题"
    if ratio < 8:
        return "中性偏碱，半哑光至半光面效果"
    if ratio < 12:
        return "中性偏酸，釉面光亮，质感较好"
    if ratio < 16:
        return "酸性较强，釉面过亮，易出现开裂（开片）"
    return "酸性过强，釉面极易开裂，热膨胀系数偏高"


def _format_seger_unified(
    ro_r2o: float,
    al2o3: float,
    sio2: float,
    oxide_moles: dict,
    norm_factor: float,
) -> str:
    """Format the unified Seger formula string, e.g. '0.3K2O + 0.7CaO : 0.5Al2O3 : 4.0SiO2'."""
    if ro_r2o <= 0 or norm_factor <= 0:
        return ""

    ordered_labels = [
        ('na2o', 'Na₂O'), ('k2o', 'K₂O'), ('cao', 'CaO'),
        ('mgo', 'MgO'), ('zno', 'ZnO'), ('fe2o3', 'Fe₂O₃'),
    ]

    ro_parts = []
    for col, label in ordered_labels:
        moles = oxide_moles.get(col, 0) * norm_factor
        if moles > 0.001:
            ro_parts.append(f"{moles:.4f}{label}")

    if not ro_parts:
        ro_parts.append(f"{ro_r2o:.4f}RO")

    ro_str = " + ".join(ro_parts)
    al2o3_str = f"{al2o3:.4f}Al₂O₃"
    sio2_str = f"{sio2:.4f}SiO₂"

    return f"{ro_str} : {al2o3_str} : {sio2_str}"


def _empty_seger_result(reason: str = ""):
    """Return a dict representing an empty / failed Seger calculation."""
    return {
        'seger_unified': '',
        'seger_al2o3': None,
        'seger_sio2': None,
        'seger_ro': None,
        'acid_base_ratio': None,
        'acid_base_note': reason,
        'seger_detail': json.dumps({}, ensure_ascii=False),
        'calculated_at': datetime.now(timezone.utc),
    }


# ============================================================
# DB persistence helpers
# ============================================================


def _save_seger(db: Session, recipe_id: int, data: dict) -> None:
    """Save or update a RecipeSeger record."""
    existing = db.query(RecipeSeger).filter(
        RecipeSeger.recipe_id == recipe_id
    ).first()

    if existing:
        existing.seger_unified = data['seger_unified']
        existing.seger_al2o3 = data['seger_al2o3']
        existing.seger_sio2 = data['seger_sio2']
        existing.seger_ro = data['seger_ro']
        existing.acid_base_ratio = data['acid_base_ratio']
        existing.acid_base_note = data['acid_base_note']
        existing.seger_detail = data['seger_detail']
        existing.calculated_at = data['calculated_at']
    else:
        seger = RecipeSeger(
            recipe_id=recipe_id,
            seger_unified=data['seger_unified'],
            seger_al2o3=data['seger_al2o3'],
            seger_sio2=data['seger_sio2'],
            seger_ro=data['seger_ro'],
            acid_base_ratio=data['acid_base_ratio'],
            acid_base_note=data['acid_base_note'],
            seger_detail=data['seger_detail'],
            calculated_at=data['calculated_at'],
        )
        db.add(seger)
    db.commit()


def _save_seger_empty(db: Session, recipe_id: int, reason: str) -> dict:
    """Save a placeholder empty result and return it."""
    data = _empty_seger_result(reason)
    _save_seger(db, recipe_id, data)
    return data


# ============================================================
# Main calculation entry point
# ============================================================


def calculate_seger(recipe_id: int, db: Session) -> dict:
    """
    Calculate Seger formula for a glaze recipe and persist the result.

    Workflow
    --------
    1. Fetch all RecipeIngredient rows for *recipe_id*.
    2. Decrypt each ingredient's `name` (AES) and `amount`.
    3. Look up oxide composition from **ceramic_materials** first, then
       **glazy_materials** (matched by ``name_en``, ``name``, or ``name_cn``).
    4. Convert each ingredient's weight → oxide moles:
       ``amount(g) × oxide% / molecular_weight``.
    5. Sum oxide moles across all ingredients.
    6. Group into **RO+R₂O** (flux), **Al₂O₃**, and **SiO₂**.
    7. Normalise so that RO+R₂O = 1.0.
    8. Format the unified Seger string and compute the acid/base ratio.
    9. Persist to **recipe_seger** table.
    10. Return a full result dict.

    Edge Cases
    ----------
    - No ingredients / empty names → empty result with explanatory note.
    - Missing material lookup → ingredient is skipped (logged).
    - All oxide moles zero → empty result with explanatory note.
    - Division by zero (no flux) → zeros in normalised values.

    Parameters
    ----------
    recipe_id : int
        Recipe primary key.
    db : sqlalchemy.orm.Session
        Active database session.

    Returns
    -------
    dict
        Seger calculation result with keys:
        ``seger_unified``, ``seger_al2o3``, ``seger_sio2``, ``seger_ro``,
        ``acid_base_ratio``, ``acid_base_note``, ``seger_detail`` (JSON),
        ``calculated_at``.
    """
    # ----- 1. Fetch recipe & ingredients -----------------------------------
    recipe = db.query(Recipe).filter(Recipe.id == recipe_id).first()
    if not recipe:
        logger.warning("Recipe %s not found for Seger calculation", recipe_id)
        return _empty_seger_result("配方不存在")

    ingredients = (
        db.query(RecipeIngredient)
        .filter(RecipeIngredient.recipe_id == recipe_id)
        .order_by(RecipeIngredient.sort_order, RecipeIngredient.id)
        .all()
    )

    if not ingredients:
        logger.info(
            "Recipe %s has no ingredients — skipping Seger calculation",
            recipe_id,
        )
        return _save_seger_empty(db, recipe_id, "暂无配料数据，无法计算 Seger 式")

    # ----- 2. Decrypt & parse ----------------------------------------------
    ingredient_data = []
    for ing in ingredients:
        decrypted_name = decrypt(ing.name) if ing.name else ""
        if not decrypted_name:
            continue

        raw_amount = decrypt(ing.amount) if ing.amount else "0"
        try:
            amount_val = float(raw_amount)
        except (ValueError, TypeError):
            amount_val = 0.0

        ingredient_data.append({
            'name': decrypted_name,
            'name_en': (ing.name_en or "").strip(),
            'amount': amount_val,
            'unit': (ing.unit or "").strip().lower(),
            'is_additional': ing.is_additional,
        })

    if not ingredient_data:
        return _save_seger_empty(
            db, recipe_id, "所有配料名称均为空，无法匹配材料",
        )

    # ----- 3. Determine scaling factor -------------------------------------
    # If any ingredient is in %, treat the total as 100 g
    has_percentage = any(d['unit'] == '%' for d in ingredient_data)
    total_raw = sum(d['amount'] for d in ingredient_data)

    if has_percentage and total_raw > 0:
        scale = 100.0 / total_raw
    else:
        scale = 1.0

    # ----- 4. Accumulate oxide moles ---------------------------------------
    oxide_moles_total = {col: 0.0 for col in OXIDE_COLUMNS}
    ingredient_details = []
    unmatched_names = []

    for d in ingredient_data:
        name = d['name']
        name_en = d['name_en']
        scaled_amount = d['amount'] * scale

        if d['is_additional']:
            continue  # skip additional / extra ingredients

        # --- Look up material ---
        material = None
        matched_by = ""

        # a) name_en → ceramic_materials
        if name_en:
            material = (
                db.query(CeramicMaterial)
                .filter(CeramicMaterial.name_en == name_en)
                .first()
            )
            if material:
                matched_by = f"ceramic_materials.name_en='{name_en}'"

        # b) decrypted name → ceramic_materials.name
        if not material:
            material = (
                db.query(CeramicMaterial)
                .filter(CeramicMaterial.name == name)
                .first()
            )
            if material:
                matched_by = f"ceramic_materials.name='{name}'"

        # c) decrypted name → glazy_materials.name
        if not material:
            material = (
                db.query(GlazyMaterial)
                .filter(GlazyMaterial.name == name)
                .first()
            )
            if material:
                matched_by = f"glazy_materials.name='{name}'"

        # d) decrypted name → glazy_materials.name_cn
        if not material:
            material = (
                db.query(GlazyMaterial)
                .filter(GlazyMaterial.name_cn == name)
                .first()
            )
            if material:
                matched_by = f"glazy_materials.name_cn='{name}'"

        if not material:
            unmatched_names.append(name)
            logger.warning("No material found for ingredient '%s'", name)
            continue

        # --- Calculate oxide moles ---
        detail = {
            'ingredient': name,
            'amount': round(scaled_amount, 4),
            'unit': d['unit'],
            'matched_by': matched_by,
        }

        for oxide_col in OXIDE_COLUMNS:
            oxide_pct = _get_oxide_value(material, oxide_col)
            if oxide_pct == 0:
                continue
            mw = OXIDE_MW.get(oxide_col)
            if not mw or mw == 0:
                continue

            # weight of this oxide = ingredient weight × oxide% / 100
            oxide_weight = scaled_amount * oxide_pct / 100.0
            moles = oxide_weight / mw
            oxide_moles_total[oxide_col] += moles
            detail[oxide_col] = round(moles, 6)

        ingredient_details.append(detail)

    # ----- 5. Guard: no calculable oxides ----------------------------------
    if all(v == 0 for v in oxide_moles_total.values()):
        return _save_seger_empty(
            db, recipe_id,
            "无法计算氧化物摩尔数：未匹配到任何含有氧化物数据的材料",
        )

    # ----- 6. Group & normalise --------------------------------------------
    ro_r2o_moles = sum(oxide_moles_total.get(col, 0) for col in FLUX_OXIDES)
    al2o3_moles = oxide_moles_total.get('al2o3', 0)
    sio2_moles = oxide_moles_total.get('sio2', 0)

    if ro_r2o_moles > 0:
        norm_factor = 1.0 / ro_r2o_moles
        seger_al2o3 = al2o3_moles * norm_factor
        seger_sio2 = sio2_moles * norm_factor
        seger_ro = 1.0
    else:
        norm_factor = 1.0
        seger_al2o3 = 0.0
        seger_sio2 = 0.0
        seger_ro = 0.0

    # ----- 7. Format string & acid-base ratio ------------------------------
    seger_unified = _format_seger_unified(
        seger_ro, seger_al2o3, seger_sio2, oxide_moles_total, norm_factor,
    )

    acid_base_ratio = round(seger_sio2 / seger_al2o3, 4) if seger_al2o3 > 0 else 0.0
    acid_base_note = _get_acid_base_note(acid_base_ratio)

    # ----- 8. Build detail JSON --------------------------------------------
    seger_detail = {
        'oxide_moles': {
            k: round(v, 6) for k, v in oxide_moles_total.items() if v != 0
        },
        'normalized': {
            'ro_r2o': round(seger_ro, 4),
            'al2o3': round(seger_al2o3, 4),
            'sio2': round(seger_sio2, 4),
        },
        'norm_factor': round(norm_factor, 6),
        'ingredient_details': ingredient_details,
        'unmatched': unmatched_names,
        'total_grams': round(total_raw, 2),
        'scale': round(scale, 6),
    }

    result = {
        'recipe_id': recipe_id,
        'seger_unified': seger_unified,
        'seger_al2o3': round(seger_al2o3, 4),
        'seger_sio2': round(seger_sio2, 4),
        'seger_ro': round(seger_ro, 4),
        'acid_base_ratio': acid_base_ratio,
        'acid_base_note': acid_base_note,
        'seger_detail': json.dumps(seger_detail, ensure_ascii=False),
        'calculated_at': datetime.now(timezone.utc),
    }

    # ----- 9. Persist & return ---------------------------------------------
    _save_seger(db, recipe_id, result)
    return result
