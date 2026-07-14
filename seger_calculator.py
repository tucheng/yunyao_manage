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

from sqlalchemy import func
from sqlalchemy.orm import Session
from security import decrypt
from models import RecipeIngredient, Material, RecipeSeger, Recipe

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
    'li2o': 29.88,
    'mno2': 86.94,
    'coo': 74.93,
    'sno2': 150.71,
    'cuo': 79.55,
    'cr2o3': 151.99,
    'pbo': 223.20,
    'bao': 153.33,
    'sro': 103.62,
}

# ============================================================
# Molecular weights of common mineral formulas (total g/mol)
# ============================================================
MOLECULE_MW = {
    'K2O·Al2O3·6SiO2': 94.20 + 101.96 + 6 * 60.08,
    'Na2O·Al2O3·6SiO2': 61.98 + 101.96 + 6 * 60.08,
    'CaO·Al2O3·2SiO2': 56.08 + 101.96 + 2 * 60.08,
    'CaO·Al2O3·4SiO2': 56.08 + 101.96 + 4 * 60.08,
    'K2O·Al2O3·4SiO2': 94.20 + 101.96 + 4 * 60.08,
    '2CaO·MgO·4SiO2': 2 * 56.08 + 40.30 + 4 * 60.08,
    '3Al2O3·2SiO2': 3 * 101.96 + 2 * 60.08,
    'Al2O3·2SiO2·2H2O': 101.96 + 2 * 60.08 + 2 * 18.015,
    'MgO·SiO2': 40.30 + 60.08,
    'CaO·SiO2': 56.08 + 60.08,
    'CaCO3': 56.08 + 44.01,
    'MgCO3': 40.30 + 44.01,
    'BaO·Al2O3·4SiO2': 153.33 + 101.96 + 4 * 60.08,
    'SrO·Al2O3·4SiO2': 103.62 + 101.96 + 4 * 60.08,
    'Li2O·Al2O3·4SiO2': 29.88 + 101.96 + 4 * 60.08,
    'Li2O·Al2O3·8SiO2': 29.88 + 101.96 + 8 * 60.08,
}

# ============================================================
# Column names in material models that hold oxide percentages
# ============================================================
OXIDE_COLUMNS = ['sio2', 'al2o3', 'fe2o3', 'tio2', 'cao', 'mgo',
                 'na2o', 'k2o', 'zno', 'b2o3', 'p2o5',
                 'li2o', 'mno2', 'coo', 'sno2', 'cuo', 'cr2o3', 'pbo', 'bao', 'sro']

# Oxides classified as RO + R2O (flux / alkaline group)
FLUX_OXIDES = ['na2o', 'k2o', 'cao', 'mgo', 'zno', 'fe2o3',
               'li2o', 'coo', 'cuo', 'pbo', 'bao', 'sro']

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


# ============================================================
# New Analysis Functions
# ============================================================


def _estimate_firing_temp(oxide_moles: dict) -> dict:
    """Estimate firing temperature range based on flux oxide content.

    The total flux (RO+R2O) moles per 'unit batch' tells us how
    much melting aid is present. More flux → lower melting point.
    """
    total_flux = sum(oxide_moles.get(col, 0) for col in FLUX_OXIDES)
    if total_flux <= 0:
        return {"cone": "", "temp_range": "", "note": ""}

    # Rough heuristic based on total flux moles (accumulated from ~100g batch)
    if total_flux > 0.5:
        cone = "06-04"
        temp = "约 980–1060℃"
        note = "熔剂含量高，低温即可熔化"
    elif total_flux > 0.3:
        cone = "04-02"
        temp = "约 1060–1120℃"
        note = "熔剂含量偏高，适合中温"
    elif total_flux > 0.2:
        cone = "02-4"
        temp = "约 1120–1200℃"
        note = "熔剂含量适中，适合中高温"
    elif total_flux > 0.12:
        cone = "4-8"
        temp = "约 1200–1260℃"
        note = "熔剂量中等，适合高温"
    else:
        cone = "8-10"
        temp = "约 1260–1300℃+"
        note = "熔剂含量较低，需要较高温度烧成"

    return {"cone": cone, "temp_range": temp, "note": note}


def _get_surface_prediction(ratio: float) -> dict:
    """Predict glaze surface and potential issues based on SiO₂:Al₂O₃ ratio."""
    if ratio <= 0:
        return {"surface": "", "note": ""}

    if ratio < 4:
        return {"surface": "强哑光", "note": "Al₂O₃ 比例极高，严重哑光，可能出现缩釉、针孔"}
    if ratio < 6:
        return {"surface": "哑光", "note": "Al₂O₃ 偏高，釉面哑光质感，留意缩釉风险"}
    if ratio < 8:
        return {"surface": "半哑光", "note": "半哑光至半光面，质感柔和"}
    if ratio < 10:
        return {"surface": "缎面", "note": "缎面质感，光泽适中，品质较好"}
    if ratio < 12:
        return {"surface": "半光", "note": "半光泽釉面，光泽感强"}
    if ratio < 16:
        return {"surface": "亮光", "note": "釉面光亮，过高易开片"}
    return {"surface": "强亮光", "note": "釉面极亮，热膨胀偏高，极易开裂"}


def _get_thermal_expansion_analysis(oxide_moles: dict, normalized: dict) -> dict:
    """Analyze thermal expansion characteristics.

    - Na₂O expands more than K₂O → high Na₂O/K₂O ratio means crazing risk.
    - CaO helps reduce expansion.
    - High SiO₂ also increases expansion.
    """
    na2o = oxide_moles.get('na2o', 0)
    k2o = oxide_moles.get('k2o', 0)
    cao = oxide_moles.get('cao', 0)
    mgo = oxide_moles.get('mgo', 0)

    # K-Na balance
    total_alkali = na2o + k2o
    if total_alkali > 0:
        na_k_ratio = na2o / total_alkali
    else:
        na_k_ratio = 0

    issues = []
    if na_k_ratio > 0.6 and total_alkali > 0.01:
        issues.append("Na₂O 占比偏高 → 热膨胀偏大，轴面易开裂（开片）")
    elif na_k_ratio < 0.3 and total_alkali > 0.01:
        issues.append("K₂O 占比偏高 → 热膨胀偏小，釉面可能压缩（缩釉）")

    if cao > 0.01:
        issues.append(f"CaO 含量适中 → 有助于降低膨胀、改善坯釉结合")

    if mgo > 0.01:
        issues.append("MgO 存在 → 提升釉面硬度，改善哑光效果")

    if not issues:
        issues.append("碱金属/碱土金属组成较均衡，热膨胀风险较低")

    return {"na_k_ratio": round(na_k_ratio, 4), "details": issues}


def _get_color_analysis(oxide_moles: dict) -> dict:
    """Analyze coloring oxide presence and suggest possible glaze colors."""
    fe2o3 = oxide_moles.get('fe2o3', 0)
    tio2 = oxide_moles.get('tio2', 0)
    zno = oxide_moles.get('zno', 0)
    b2o3 = oxide_moles.get('b2o3', 0)
    p2o5 = oxide_moles.get('p2o5', 0)
    cao = oxide_moles.get('cao', 0)
    mgo = oxide_moles.get('mgo', 0)
    coo = oxide_moles.get('coo', 0)
    cuo = oxide_moles.get('cuo', 0)
    cr2o3 = oxide_moles.get('cr2o3', 0)
    mno2 = oxide_moles.get('mno2', 0)
    li2o = oxide_moles.get('li2o', 0)

    hints = []

    # Iron + Titanium → celadon / tenmoku
    if fe2o3 > 0.001:
        if tio2 > 0 and fe2o3 / tio2 > 3:
            hints.append(f"Fe₂O₃({fe2o3:.4f}mol)+TiO₂ → 还原气氛可能产生青瓷/天目效果")
        elif fe2o3 > 0.01:
            hints.append(f"Fe₂O₃({fe2o3:.4f}mol)含量显著 → 影响釉色发色")

    # CoO → 蓝色系
    if coo > 0.001:
        hints.append(f"CoO({coo:.4f}mol)存在 → 产生蓝色调，用量极微即可显色")

    # CuO → 绿色/铜红
    if cuo > 0.001:
        hints.append(f"CuO({cuo:.4f}mol)存在 → 氧化焰呈绿色，还原焰可能出铜红")

    # Cr2O3 → 绿色/粉红
    if cr2o3 > 0.001:
        hints.append(f"Cr₂O₃({cr2o3:.4f}mol)存在 → 氧化焰呈绿色，与锡合用出粉红")

    # MnO2 → 紫褐/铁锈
    if mno2 > 0.005:
        hints.append(f"MnO₂({mno2:.4f}mol)含量较高 → 产生紫褐/铁锈色调")

    # P2O5 + CaO → 骨灰系
    if p2o5 > 0.001 and cao > 0.01:
        hints.append("P₂O₅+CaO → 骨灰系效果，可能产生哑光乳浊")

    # ZnO
    if zno > 0.001:
        hints.append("ZnO 存在 → 影响结晶釉效果，改善乳浊度")

    # B2O3
    if b2o3 > 0.001:
        hints.append("B₂O₃ 存在 → 降低熔点，改善釉面流动性和光泽")

    # Li2O
    if li2o > 0.001:
        hints.append("Li₂O 存在 → 强熔剂，改善釉面流动性和光泽")

    if not hints:
        hints.append("无色系釉料基础成分，颜色取决于添加的色料")

    return {"hints": hints}


def _get_oxide_contributions(ingredient_details: list) -> dict:
    """For each oxide, list which ingredients contributed and what percentage."""
    # Collect per-oxide contributions
    oxide_sources = {}
    for ing in ingredient_details:
        name = ing['ingredient']
        for k, v in ing.items():
            if k in OXIDE_COLUMNS and v and v > 0:
                if k not in oxide_sources:
                    oxide_sources[k] = []
                oxide_sources[k].append({"ingredient": name, "moles": round(v, 6)})

    # Calculate percentage share per oxide
    result = {}
    for oxide, sources in oxide_sources.items():
        total = sum(s['moles'] for s in sources)
        if total > 0:
            label = oxide.upper()  # e.g. 'sio2' → 'SiO₂'
            result[oxide] = [
                {
                    "ingredient": s['ingredient'],
                    "pct": round(s['moles'] / total * 100, 1),
                }
                for s in sorted(sources, key=lambda x: -x['moles'])
            ]
    return result


# ============================================================
# Formatting
# ============================================================


def _format_seger_unified(
    ro_r2o: float,
    al2o3: float,
    sio2: float,
    oxide_moles: dict,
    norm_factor: float,
) -> str:
    """Format the unified Seger formula string."""
    if ro_r2o <= 0 or norm_factor <= 0:
        return ""

    ordered_labels = [
        ('na2o', 'Na₂O'), ('k2o', 'K₂O'), ('cao', 'CaO'),
        ('mgo', 'MgO'), ('zno', 'ZnO'), ('fe2o3', 'Fe₂O₃'),
        ('li2o', 'Li₂O'), ('coo', 'CoO'), ('cuo', 'CuO'),
        ('pbo', 'PbO'), ('bao', 'BaO'), ('sro', 'SrO'),
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
        'surface_prediction': {"surface": "", "note": ""},
        'firing_temp': {"cone": "", "temp_range": "", "note": ""},
        'thermal_expansion': {"na_k_ratio": 0, "details": []},
        'color_analysis': {"hints": []},
        'oxide_contributions': {},
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
    3. Look up oxide composition from the unified **materials** catalog
       (matched by ``name_en`` or ``name``).
    4. Convert each ingredient's weight → oxide moles:
       ``amount(g) × oxide% / molecular_weight``.
    5. Sum oxide moles across all ingredients.
    6. Group into **RO+R₂O** (flux), **Al₂O₃**, and **SiO₂**.
    7. Normalise so that RO+R₂O = 1.0.
    8. Format the unified Seger string and compute the acid/base ratio.
    9. Compute additional analyses: surface prediction, firing temp estimate,
       thermal expansion analysis, color analysis, oxide contributions.
    10. Persist to **recipe_seger** table.
    11. Return a full result dict.
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
        # 金额可能含单位后缀如 "45.3%"，去掉非数字字符
        clean_amount = raw_amount.replace('%', '').replace('g', '').replace('G', '').strip()
        try:
            amount_val = float(clean_amount)
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
    included_additional = []
    found_no_oxides = []

    for d in ingredient_data:
        name = d['name']
        name_en = d['name_en']
        scaled_amount = d['amount'] * scale

        if d['is_additional']:
            included_additional.append(name)
            # 仍参与 Seger 计算，附加材料也可能含氧化物

        # --- Look up material ---
        material = None
        matched_by = ""

        # a) decrypted name → materials.name (去空格匹配，数据优先)
        name_clean = name.replace(' ', '')
        material = (
            db.query(Material)
            .filter(func.replace(Material.name, ' ', '') == name_clean)
            .order_by(
                func.coalesce(Material.sio2, 0).desc(),
                Material.source.desc(),
            )
            .first()
        )
        if material:
            matched_by = f"materials.name='{name}'"

        # b) name_en → materials.name_en (去空格匹配，数据优先)
        if not material and name_en:
            name_en_clean = name_en.replace(' ', '')
            material = (
                db.query(Material)
                .filter(func.replace(Material.name_en, ' ', '') == name_en_clean)
                .order_by(
                    func.coalesce(Material.sio2, 0).desc(),
                    Material.source.desc(),
                )
                .first()
            )
            if material:
                matched_by = f"materials.name_en='{name_en}'"

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

            oxide_weight = scaled_amount * oxide_pct / 100.0
            moles = oxide_weight / mw
            oxide_moles_total[oxide_col] += moles
            detail[oxide_col] = round(moles, 6)

        # Track materials found but with no oxide data
        # detail starts with 4 base keys (ingredient, amount, unit, matched_by)
        # if no oxide columns were added, it means this material has no oxide data
        if len(detail) <= 4:
            found_no_oxides.append(name)

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

    # ----- 8. Additional analyses ------------------------------------------
    surface_prediction = _get_surface_prediction(acid_base_ratio)
    firing_temp = _estimate_firing_temp(oxide_moles_total)
    thermal_expansion = _get_thermal_expansion_analysis(oxide_moles_total, {
        'ro_r2o': seger_ro, 'al2o3': seger_al2o3, 'sio2': seger_sio2,
    })
    color_analysis = _get_color_analysis(oxide_moles_total)
    oxide_contributions = _get_oxide_contributions(ingredient_details)

    # ----- 9. Build detail JSON --------------------------------------------
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
        'included_additional': included_additional,
        'found_no_oxides': found_no_oxides,
        'total_grams': round(total_raw, 2),
        'scale': round(scale, 6),
        # 扩展分析
        'surface_prediction': surface_prediction,
        'firing_temp': firing_temp,
        'thermal_expansion': thermal_expansion,
        'color_analysis': color_analysis,
        'oxide_contributions': oxide_contributions,
    }

    result = {
        'recipe_id': recipe_id,
        'seger_unified': seger_unified,
        'seger_al2o3': round(seger_al2o3, 4),
        'seger_sio2': round(seger_sio2, 4),
        'seger_ro': round(seger_ro, 4),
        'acid_base_ratio': acid_base_ratio,
        'acid_base_note': acid_base_note,
        'surface_prediction': surface_prediction,
        'firing_temp': firing_temp,
        'thermal_expansion': thermal_expansion,
        'color_analysis': color_analysis,
        'oxide_contributions': oxide_contributions,
        'seger_detail': json.dumps(seger_detail, ensure_ascii=False),
        'calculated_at': datetime.now(timezone.utc),
    }

    # ----- 10. Persist & return --------------------------------------------
    _save_seger(db, recipe_id, result)
    return result
