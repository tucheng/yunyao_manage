"""
釉色名称翻译器 — HEX → 中文陶瓷色名
基于 RGB 欧氏距离匹配最近的颜色名
"""
import math

# 陶瓷/釉色常用色名映射表
COLOR_NAMES = [
    # 青瓷系
    ("天青", 0x6B, 0xB7, 0xD2),
    ("粉青", 0x8D, 0xC9, 0xB5),
    ("梅子青", 0x5B, 0x8C, 0x5A),
    ("豆青", 0x9C, 0xB6, 0x7C),
    ("冬青", 0x4F, 0x8A, 0x6B),
    ("翠青", 0x60, 0xC0, 0x80),
    ("影青", 0x9F, 0xC9, 0xAE),
    ("青白", 0xBC, 0xD1, 0xBF),
    ("青绿", 0x5A, 0x9E, 0x6B),
    ("松石绿", 0x49, 0xC2, 0x8D),

    # 青花系
    ("青花蓝", 0x2E, 0x4E, 0x7A),
    ("钴蓝", 0x1D, 0x3B, 0x6E),
    ("霁蓝", 0x0B, 0x23, 0x4B),
    ("宝石蓝", 0x1E, 0x5C, 0x9E),
    ("孔雀蓝", 0x2B, 0x7E, 0xAC),

    # 红釉系
    ("霁红", 0x9B, 0x1B, 0x1E),
    ("郎红", 0x7D, 0x0A, 0x0A),
    ("豇豆红", 0xB8, 0x4A, 0x4A),
    ("胭脂红", 0xAB, 0x33, 0x4D),
    ("矾红", 0xC0, 0x4A, 0x3A),
    ("珊瑚红", 0xD4, 0x5D, 0x42),
    ("铁红", 0x8B, 0x3A, 0x2A),
    ("橘红", 0xC9, 0x5B, 0x3A),
    ("西瓜红", 0xD7, 0x6B, 0x6B),
    ("淡粉", 0xF2, 0xC8, 0xC8),

    # 黑釉系
    ("乌金", 0x1A, 0x1A, 0x1A),
    ("漆黑", 0x0D, 0x0D, 0x0D),
    ("铁黑", 0x2D, 0x2D, 0x2D),
    ("墨色", 0x33, 0x33, 0x33),
    ("灰黑", 0x44, 0x44, 0x44),

    # 白釉系
    ("月白", 0xE6, 0xE9, 0xF0),
    ("甜白", 0xF5, 0xF0, 0xE6),
    ("象牙白", 0xF8, 0xF0, 0xDB),
    ("乳白", 0xF0, 0xEC, 0xDE),
    ("卵白", 0xE8, 0xE0, 0xD0),
    ("高白", 0xF8, 0xF8, 0xF8),
    ("米白", 0xF0, 0xE6, 0xD0),

    # 黄釉系
    ("鳝鱼黄", 0xC4, 0xA4, 0x5A),
    ("鸡油黄", 0xD4, 0xB8, 0x5A),
    ("娇黄", 0xE8, 0xC8, 0x60),
    ("柠檬黄", 0xE6, 0xD6, 0x3A),
    ("米黄", 0xD4, 0xBE, 0x86),
    ("姜黄", 0xD4, 0xAB, 0x4A),
    ("土黄", 0xBE, 0x96, 0x4A),

    # 绿釉系
    ("翠绿", 0x2E, 0xA6, 0x3E),
    ("草绿", 0x6B, 0xB5, 0x5A),
    ("苹果绿", 0x8E, 0xC8, 0x78),
    ("墨绿", 0x1E, 0x5A, 0x2E),
    ("茶绿", 0x5C, 0x7A, 0x4E),

    # 紫釉系
    ("玫瑰紫", 0x8B, 0x4C, 0x7A),
    ("葡萄紫", 0x5E, 0x2C, 0x5E),
    ("茄紫", 0x6E, 0x3A, 0x5E),
    ("紫罗兰", 0x7E, 0x5C, 0xA8),

    # 褐/赭/茶末系
    ("茶叶末", 0x6B, 0x5A, 0x3A),
    ("赭石", 0x7B, 0x4A, 0x2E),
    ("赭色", 0x8B, 0x5A, 0x3A),
    ("褐色", 0x7B, 0x56, 0x3A),
    ("深褐", 0x5A, 0x3A, 0x1A),
    ("栗色", 0x5E, 0x3A, 0x2A),
    ("咖啡", 0x6B, 0x4A, 0x2E),
    ("古铜", 0x8B, 0x6B, 0x4A),
    ("酱色", 0x5E, 0x3E, 0x2A),
    ("沉香", 0x8B, 0x7A, 0x5A),

    # 灰釉系
    ("浅灰", 0xC0, 0xC0, 0xC0),
    ("中灰", 0x90, 0x90, 0x90),
    ("深灰", 0x5A, 0x5A, 0x5A),
    ("灰蓝", 0x6A, 0x7A, 0x8A),
    ("灰绿", 0x7A, 0x8A, 0x6A),
    ("灰紫", 0x8A, 0x7A, 0x8A),
    ("烟灰", 0xAE, 0xAE, 0xAE),

    # 特殊釉色
    ("兔毫", 0x4A, 0x3A, 0x2A),
    ("油滴", 0x3A, 0x3A, 0x3A),
    ("木叶", 0x6B, 0x4E, 0x32),
    ("窑变", 0x5A, 0x3A, 0x5A),
    ("曜变", 0x2A, 0x2A, 0x3A),
    ("结晶", 0x5A, 0x6A, 0x7A),
    ("流釉", 0x6B, 0x5A, 0x4A),

    # 基础通用色
    ("黑色", 0x00, 0x00, 0x00),
    ("白色", 0xFF, 0xFF, 0xFF),
    ("红色", 0xE0, 0x2E, 0x2E),
    ("橙色", 0xE6, 0x8A, 0x2E),
    ("黄色", 0xE0, 0xC0, 0x2E),
    ("绿色", 0x2E, 0xA0, 0x2E),
    ("青色", 0x2E, 0x8A, 0xC0),
    ("蓝色", 0x2E, 0x5A, 0xE0),
    ("紫色", 0x8E, 0x4A, 0xC0),
    ("灰色", 0xB0, 0xB0, 0xB0),
    ("棕色", 0x8B, 0x5A, 0x2E),
    ("粉色", 0xF2, 0xA0, 0xC0),
    ("米色", 0xF2, 0xE8, 0xC8),
    ("卡其", 0xC8, 0xB0, 0x7A),
]


COLOR_RANGE_CONFIG = [
    {
        "value": "cyan",
        "label": "青色",
        "names": ["天青", "粉青", "梅子青", "豆青", "冬青", "翠青", "影青", "青白", "青绿", "松石绿", "青色"],
        "description": "青瓷、青白、青绿等偏青釉色。",
    },
    {
        "value": "blue",
        "label": "蓝色",
        "names": ["青花蓝", "钴蓝", "霁蓝", "宝石蓝", "孔雀蓝", "灰蓝", "蓝色"],
        "description": "青花、钴蓝、霁蓝、孔雀蓝等蓝釉色。",
    },
    {
        "value": "red",
        "label": "红色",
        "names": ["霁红", "郎红", "豇豆红", "胭脂红", "矾红", "珊瑚红", "铁红", "橘红", "西瓜红", "淡粉", "红色", "粉色"],
        "description": "红釉、铁红、胭脂红和粉红色系。",
    },
    {
        "value": "black",
        "label": "黑色",
        "names": ["乌金", "漆黑", "铁黑", "墨色", "灰黑", "黑色"],
        "description": "乌金、铁黑、墨色等黑釉色。",
    },
    {
        "value": "white",
        "label": "白色",
        "names": ["月白", "甜白", "象牙白", "乳白", "卵白", "高白", "米白", "白色", "米色"],
        "description": "白釉、月白、乳白、米白等浅色釉。",
    },
    {
        "value": "yellow",
        "label": "黄色",
        "names": ["鳝鱼黄", "鸡油黄", "娇黄", "柠檬黄", "米黄", "姜黄", "土黄", "黄色", "卡其"],
        "description": "黄釉、米黄、姜黄和卡其色系。",
    },
    {
        "value": "green",
        "label": "绿色",
        "names": ["翠绿", "草绿", "苹果绿", "墨绿", "茶绿", "灰绿", "绿色"],
        "description": "翠绿、草绿、墨绿、茶绿等绿釉色。",
    },
    {
        "value": "purple",
        "label": "紫色",
        "names": ["玫瑰紫", "葡萄紫", "茄紫", "紫罗兰", "灰紫", "紫色"],
        "description": "玫瑰紫、葡萄紫、茄紫等紫釉色。",
    },
    {
        "value": "brown",
        "label": "棕褐色",
        "names": ["茶叶末", "赭石", "赭色", "褐色", "深褐", "栗色", "咖啡", "古铜", "酱色", "沉香", "棕色", "橙色"],
        "description": "茶叶末、赭石、褐色、咖啡等棕褐釉色。",
    },
    {
        "value": "gray",
        "label": "灰色",
        "names": ["浅灰", "中灰", "深灰", "烟灰", "灰色"],
        "description": "浅灰、中灰、深灰和烟灰釉色。",
    },
]


def get_color_range_config() -> list:
    """Return glaze color range groups based on COLOR_NAMES names."""
    return COLOR_RANGE_CONFIG


def color_name_in_range(name: str, range_value: str) -> bool:
    """Whether a glaze color name belongs to a configured color range."""
    if not name or not range_value:
        return False
    for item in COLOR_RANGE_CONFIG:
        if item["value"] == range_value:
            return name in item["names"]
    return False


def hex_to_rgb(hex_str: str) -> tuple:
    """#RRGGBB → (R, G, B)"""
    h = hex_str.lstrip("#")
    if len(h) != 6:
        return (0, 0, 0)
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


def color_distance(r1, g1, b1, r2, g2, b2) -> float:
    """RGB 欧氏距离"""
    return math.sqrt((r1 - r2) ** 2 + (g1 - g2) ** 2 + (b1 - b2) ** 2)


_WEIGHTED_LUM = 0.3  # 亮度权重防误匹配


def color_distance_weighted(r1, g1, b1, r2, g2, b2) -> float:
    """加权距离：人眼对亮度差异更敏感"""
    dr = r1 - r2
    dg = g1 - g2
    db = b1 - b2
    return math.sqrt(
        (1 + _WEIGHTED_LUM) * dr * dr +
        (1) * dg * dg +
        (1 + 1 - _WEIGHTED_LUM) * db * db
    )


def find_color_name(hex_str: str) -> str:
    """
    根据 HEX 色值返回最近的中文颜色名
    例: find_color_name("#8B5A2E") → "棕色"
    """
    r, g, b = hex_to_rgb(hex_str)
    best_name = "未知"
    best_dist = float("inf")

    for name, nr, ng, nb in COLOR_NAMES:
        dist = color_distance_weighted(r, g, b, nr, ng, nb)
        if dist < best_dist:
            best_dist = dist
            best_name = name

    return best_name


def get_glaze_colors_data(hex_colors: list) -> list:
    """
    输入 HEX 列表，返回带名称的完整颜色数据
    例: get_glaze_colors_data(["#2E4E7A", "#8B5A2E"])
     → [{"hex":"#2e4e7a","r":46,"g":78,"b":122,"name":"青花蓝"},
         {"hex":"#8b5a2e","r":139,"g":90,"b":46,"name":"棕色"}]
    """
    result = []
    for h in hex_colors:
        h = h.strip().lower()
        if not h.startswith("#"):
            h = "#" + h
        if len(h) != 7:
            continue
        r, g, b = hex_to_rgb(h)
        name = find_color_name(h)
        result.append({
            "hex": h,
            "r": r,
            "g": g,
            "b": b,
            "name": name,
        })
    return result
