from datetime import date

import pytest

from value_invest.serving import sql as v


def test_validate_select_accepts_select_with_from():
    assert v.validate_select("select 1;") == "select 1"
    assert v.validate_select("WITH x AS (SELECT 1 a) SELECT * FROM x").startswith("WITH")
    assert v.validate_select("from vi.videos").startswith("from")


@pytest.mark.parametrize(
    "bad",
    [
        "",
        "DELETE FROM vi.videos",
        "SELECT 1; SELECT 2",
        "INSERT INTO vi.videos VALUES (1)",
        "SELECT 1 FROM x; ATTACH 'y'",
        "COPY vi.videos TO 'x.csv'",
        "PRAGMA database_size",
        "CREATE TABLE t AS SELECT 1",
    ],
)
def test_validate_select_rejects(bad):
    with pytest.raises(v.SqlError):
        v.validate_select(bad)


def test_run_select_caps_rows_and_is_read_only(con, tmp_path):
    con.executemany(
        "INSERT INTO vi.prices VALUES ('X', ?, 1,1,1,1,1,1)",
        [(date(2024, 1, i + 1),) for i in range(12)],
    )
    con.close()
    import duckdb

    ro = duckdb.connect(str(tmp_path / "t.duckdb"), read_only=True)
    r = v.run_select(ro, "SELECT * FROM vi.prices ORDER BY date", max_rows=10)
    assert r["row_count"] == 10 and r["truncated"] and r["columns"][0] == "ticker"
    assert isinstance(r["rows"][0][1], str)  # dates serialised
    with pytest.raises(v.SqlError):
        v.run_select(ro, "DELETE FROM vi.prices")
    with pytest.raises(
        v.SqlError
    ):  # even a valid-looking statement cannot write: the engine is read-only
        v.run_select(
            ro,
            "SELECT * FROM (INSERT INTO vi.prices VALUES ('Y', DATE '2024-01-01',1,1,1,1,1,1) RETURNING *)",
        )
    cat = v.catalog(ro)
    assert any(t["name"] == "vi.prices" and t["rows"] == 12 for t in cat["tables"])
    assert any(t["name"] == "vi.fiscal_years" and t["kind"] == "view" for t in cat["tables"])
