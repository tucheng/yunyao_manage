"""Compute material substitution similarities and store in DB.
Uses weighted cosine similarity on all oxide columns."""
import math
import sys
sys.path.insert(0, '.')
from database import SessionLocal
from models import Material, MaterialSubstitution

# All oxide columns used for similarity calculation (weighted equally per column)
OXIDE_COLS = ['sio2', 'al2o3', 'fe2o3', 'tio2', 'cao', 'mgo',
              'na2o', 'k2o', 'zno', 'b2o3', 'p2o5',
              'li2o', 'mno2', 'coo', 'sno2', 'cuo', 'cr2o3', 'pbo', 'bao', 'sro']

TOP_N = 8  # Keep top N substitutes per material

def get_oxide_vector(material):
    """Extract oxide vector, filling None with 0."""
    return [float(getattr(material, col, 0) or 0) for col in OXIDE_COLS]

def cosine_similarity(v1, v2):
    """Weighted cosine similarity. Returns 0-100 score."""
    dot = sum(a * b for a, b in zip(v1, v2))
    n1 = math.sqrt(sum(a * a for a in v1))
    n2 = math.sqrt(sum(b * b for b in v2))
    if n1 == 0 or n2 == 0:
        return 0.0
    return round(dot / (n1 * n2) * 100, 2)

db = SessionLocal()
try:
    # Load all materials with oxide data
    all_mats = db.query(Material).all()
    print(f"Total materials: {len(all_mats)}")

    # Pre-compute vectors
    mat_data = []
    for m in all_mats:
        vec = get_oxide_vector(m)
        has_oxides = any(v > 0 for v in vec)
        mat_data.append((m.id, m.name, m.source, vec, has_oxides))

    # Count how many have at least one oxide
    with_data = sum(1 for _, _, _, _, h in mat_data if h)
    print(f"Materials with oxide data: {with_data}")

    # Compute substitutions: for each material, find top-N most similar others
    total_pairs = 0
    for i, (mid, mname, msrc, mvec, mhas) in enumerate(mat_data):
        if not mhas:
            continue

        scores = []
        for j, (oid, oname, osrc, ovec, ohas) in enumerate(mat_data):
            if i == j:
                continue  # skip self
            if not ohas:
                continue

            score = cosine_similarity(mvec, ovec)
            if score > 0:
                scores.append((score, oid, oname, osrc))

        # Sort by score descending, take top N
        scores.sort(key=lambda x: -x[0])
        top = scores[:TOP_N]

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
