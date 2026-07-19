import json
from pathlib import Path

from init_db import MATERIALS_SEED_PATH, init_materials


class _QueryResult:
    def __init__(self, first_value):
        self._first_value = first_value

    def first(self):
        return self._first_value


class _SeedSession:
    def __init__(self, first_value=None):
        self.first_value = first_value
        self.inserted = None
        self.committed = False

    def query(self, _column):
        return _QueryResult(self.first_value)

    def bulk_insert_mappings(self, _model, rows):
        self.inserted = rows

    def commit(self):
        self.committed = True


def test_material_seed_contains_only_system_catalog_rows():
    rows = json.loads(Path(MATERIALS_SEED_PATH).read_text(encoding="utf-8"))

    assert len(rows) == 3438
    assert len({row["id"] for row in rows}) == len(rows)
    assert all("user_id" not in row for row in rows)
    assert all(row["name"].strip() for row in rows)


def test_init_materials_loads_seed_into_an_empty_catalog():
    db = _SeedSession()

    count = init_materials(db)

    assert count == 3438
    assert len(db.inserted) == count
    assert db.committed is True


def test_init_materials_keeps_an_existing_catalog_untouched():
    db = _SeedSession(first_value=(1,))

    count = init_materials(db)

    assert count == 0
    assert db.inserted is None
    assert db.committed is False
