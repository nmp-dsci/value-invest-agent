from __future__ import annotations

import pytest

from value_invest import db


@pytest.fixture()
def con(tmp_path):
    return db.connect(tmp_path / "t.duckdb")
