from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_admin_exposes_atmosphere_work_attribute_category():
    script = (ROOT / "static" / "admin" / "work-attributes.js").read_text(encoding="utf-8")

    assert "atmosphere: '气氛'" in script


def test_default_work_attributes_include_atmosphere_values():
    source = (ROOT / "init_db.py").read_text(encoding="utf-8")

    assert '"atmosphere": ["氧化", "还原", "中性"]' in source
