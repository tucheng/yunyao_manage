from database import SessionLocal
from models import Material
from services.material_analysis import composition_fingerprint

db = SessionLocal()

OXIDE_FIELDS = ["sio2","al2o3","fe2o3","tio2","cao","mgo","na2o","k2o",
                "zno","b2o3","p2o5","li2o","mno2","coo","sno2","cuo",
                "cr2o3","pbo","bao","sro","loi"]

groups = {
    1: [62, 1578],
    2: [63, 503],
    3: [86, 493],
    4: [87, 523, 1963],
    5: [89, 1328],
    6: [93, 609],
    7: [96, 2255],
    8: [103, 784, 1558],
    9: [127, 871],
    10: [132, 1444],
    11: [133, 544, 2134],
    12: [136, 1440],
    13: [137, 619],
    14: [138, 766],
    15: [141, 372],
    16: [174, 3340],
    17: [176, 529],
    18: [189, 498, 543, 1589],
    19: [199, 1762],
    20: [201, 1505],
    21: [210, 1459, 3281, 3427],
    22: [216, 1869],
    23: [220, 631],
    24: [227, 802],
    25: [230, 1504, 2735],
    26: [232, 2526, 3280],
    27: [237, 1425],
    28: [241, 1461],
    29: [246, 1568],
    30: [249, 1545],
    31: [256, 536, 804, 1384],
    32: [259, 1040, 1680],
    33: [275, 1775],
    34: [290, 873],
    35: [291, 715],
    36: [314, 646],
    37: [325, 494, 2759],
    38: [328, 1145],
    39: [329, 867, 2376, 2517],
    40: [358, 843],
    41: [388, 2533],
    42: [389, 1491],
    43: [398, 465, 1617],
    44: [411, 1486],
    45: [424, 457, 1179, 2737],
    46: [426, 511],
    47: [427, 506, 1327, 1836],
    48: [434, 579],
    49: [440, 1183],
    50: [447, 2418],
    51: [458, 1081],
    52: [464, 3123],
    53: [483, 1236],
    54: [487, 578],
    55: [489, 2683],
    56: [502, 1069],
    57: [504, 545],
    58: [518, 1216],
    59: [521, 2229],
    60: [522, 1392, 2053, 2281],
    61: [532, 1798],
    62: [535, 1776, 2152],
    63: [647, 680, 2329],
    64: [653, 974],
    65: [654, 789],
    66: [657, 3387],
    67: [672, 1314, 1818, 2210],
    68: [702, 1395],
    69: [704, 1250],
    70: [792, 2610],
    71: [812, 1070],
    72: [852, 2151],
    73: [869, 2338],
    74: [968, 1278],
    75: [995, 2465, 2513],
    76: [1043, 1561],
    77: [1082, 1091],
    78: [1122, 1254],
    79: [1123, 2159],
    80: [1162, 1943],
    81: [1163, 2261],
    82: [1172, 1481],
    83: [1385, 2754],
    84: [1401, 2234],
    85: [1449, 2840],
    86: [1462, 1910],
    87: [1468, 3285],
    88: [1482, 2119],
    89: [1511, 3048],
    90: [1523, 1624],
    91: [1573, 3429],
    92: [1634, 2569],
    93: [1662, 1692],
    94: [1671, 1783],
    95: [1688, 2093],
    96: [1725, 1966],
    97: [1748, 2358],
    98: [1796, 2457],
    99: [1962, 2694],
    100: [2105, 2171],
    101: [2295, 2309],
    102: [2344, 2788, 3341],
    103: [2355, 3284],
    104: [2563, 3158],
    105: [2591, 2698],
    106: [2606, 3142],
    107: [2766, 2832],
    108: [2808, 3282],
    109: [2884, 2885],
    110: [3291, 3400],
}

all_ids = [mid for ids in groups.values() for mid in ids]
materials = {m.id: m for m in db.query(Material).filter(Material.id.in_(all_ids)).all()}

print("=" * 60)
print("每组成分比对结果")
print("=" * 60)

dup_ids = set()

for gid in sorted(groups.keys()):
    mids = groups[gid]
    items = []
    for mid in mids:
        m = materials.get(mid)
        if not m:
            print(f"组{gid}: ID {mid} 不存在!")
            dup_ids.add(mid)
            continue
        fp = m.composition_fingerprint or composition_fingerprint(m)
        oxides = {f: round(getattr(m, f), 4) if getattr(m, f) is not None else None for f in OXIDE_FIELDS}
        has_oxides = any(v is not None for v in oxides.values())
        items.append({"id": m.id, "name": m.name, "name_en": m.name_en, "fp": fp, "has_oxides": has_oxides, "oxides": oxides})

    # Group by fingerprint
    fp_groups = {}
    for item in items:
        fp = item["fp"]
        fp_groups.setdefault(fp, []).append(item["id"])

    fp_groups_list = sorted(fp_groups.items(), key=lambda x: -len(x[1]))

    if len(fp_groups) == len(items):
        # All unique
        dedup_note = "✓ 成分不同"
    else:
        dedup_note = ""
        for fp, id_list in fp_groups_list:
            if len(id_list) > 1:
                keep = id_list[0]
                for rid in id_list[1:]:
                    dup_ids.add(rid)
                dedup_note += f"【重复】同成分IDs={id_list}, 保留{keep}"

    # Also flag items with NO oxides when group has at least one with oxides
    has_any_oxides = any(item["has_oxides"] for item in items)
    if has_any_oxides:
        no_oxide_ids = [item["id"] for item in items if not item["has_oxides"]]
        if no_oxide_ids and len(no_oxide_ids) < len(items):
            for nid in no_oxide_ids:
                if nid not in dup_ids:
                    dup_ids.add(nid)
                    dedup_note += f"【无成分】ID {nid}"

    names = items[0]["name"] if items else ""
    if dedup_note:
        print(f"组{gid:3d} {names:12s}: IDs={mids} {dedup_note}")
    else:
        print(f"组{gid:3d} {names:12s}: IDs={mids} ✓ 成分不同，全部保留")

print()
print("=" * 60)
print("最终结果：多余的ID列表")
print("=" * 60)

for gid in sorted(groups.keys()):
    mids = groups[gid]
    gdup = [mid for mid in mids if mid in dup_ids]
    if gdup:
        keep = [mid for mid in mids if mid not in dup_ids]
        print(f"  组{gid:3d}: 剩余 -> {keep}  删除 -> {gdup}")

print()
print(f"总共 {len(dup_ids)} 个多余ID:")
print(sorted(dup_ids))

db.close()
