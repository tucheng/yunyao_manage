"""Compute material similarities from actual oxide percentage differences."""
import sys
sys.path.insert(0, '.')
from database import SessionLocal
from models import Material, MaterialSubstitution
from services.material_similarity import (
    TOP_SIMILAR_MATERIALS,
    has_oxide_data,
    oxide_profile,
    oxide_similarity,
)

db = SessionLocal()
try:
    # Load all materials with oxide data
    all_mats = db.query(Material).all()
    print(f"Total materials: {len(all_mats)}")

    # Pre-compute vectors
    mat_data = []
    for m in all_mats:
        vec = oxide_profile(m)
        has_oxides = has_oxide_data(vec)
        mat_data.append((m.id, m.name, m.source, vec, has_oxides))

    # Count how many have at least one oxide
    with_data = sum(1 for _, _, _, _, h in mat_data if h)
    print(f"Materials with oxide data: {with_data}")

    # Compute substitutions: for each material, find top-N most similar others
    total_pairs = 0
    for i, (mid, mname, msrc, mvec, mhas) in enumerate(mat_data):
        if not mhas:
            db.query(MaterialSubstitution).filter(
                MaterialSubstitution.source_material_id == mid,
            ).delete(synchronize_session=False)
            continue

        scores = []
        for j, (oid, oname, osrc, ovec, ohas) in enumerate(mat_data):
            if i == j:
                continue  # skip self
            if not ohas:
                continue

            score = oxide_similarity(mvec, ovec)
            if score > 0:
                scores.append((score, oid, oname, osrc))

        # Sort by score descending, take top N
        scores.sort(key=lambda x: -x[0])
        top = scores[:TOP_SIMILAR_MATERIALS]
        top_target_ids = {target_id for _, target_id, _, _ in top}

        # Remove relations that are no longer in this material's current top N.
        existing_relations = db.query(MaterialSubstitution).filter(
            MaterialSubstitution.source_material_id == mid,
        ).all()
        for relation in existing_relations:
            if relation.target_material_id not in top_target_ids:
                db.delete(relation)

        for score, oid, oname, osrc in top:
            # Upsert: if same pair exists, update score
            existing = db.query(MaterialSubstitution).filter(
                MaterialSubstitution.source_material_id == mid,
                MaterialSubstitution.target_material_id == oid
            ).first()
            if existing:
                existing.similarity_score = score
            else:
                sub = MaterialSubstitution(
                    source_material_id=mid,
                    target_material_id=oid,
                    similarity_score=score,
                    note=''
                )
                db.add(sub)
            total_pairs += 1

        if (i + 1) % 200 == 0:
            db.commit()
            print(f"  Processed {i+1}/{len(mat_data)} materials, {total_pairs} pairs so far")

    db.commit()
    print(f"\nDone! Total substitution pairs stored: {total_pairs}")
    print(f"Top scores preview:")
    preview = db.query(MaterialSubstitution).order_by(MaterialSubstitution.similarity_score.desc()).limit(10).all()
    for p in preview:
        src = db.query(Material).filter(Material.id == p.source_material_id).first()
        tgt = db.query(Material).filter(Material.id == p.target_material_id).first()
        print(f"  {src.name} ({src.source}) → {tgt.name} ({tgt.source}): {p.similarity_score}%")

finally:
    db.close()
