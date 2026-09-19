from fastapi.testclient import TestClient


def test_health_and_funnel(monkeypatch, tmp_path):
    from value_invest import db
    from value_invest.serving import app as appmod

    p = tmp_path / "t.duckdb"
    db.connect(p).close()
    monkeypatch.setattr(
        db,
        "connect",
        lambda path=None, read_only=False: __import__("duckdb").connect(
            str(p), read_only=read_only
        ),
    )
    client = TestClient(appmod.create_app())
    h = client.get("/api/health").json()
    assert h["ok"] and "videos" in h["tables"]
    f = client.get("/api/funnel").json()
    assert f["listed"] == 0 and f["per_year_target"] == 10
    assert client.get("/api/videos/nope").status_code == 404


def test_sql_endpoint_takes_a_json_body(monkeypatch, tmp_path):
    from value_invest import db
    from value_invest.serving import app as appmod

    p = tmp_path / "t.duckdb"
    db.connect(p).close()
    monkeypatch.setattr(
        db,
        "connect",
        lambda path=None, read_only=False: __import__("duckdb").connect(
            str(p), read_only=read_only
        ),
    )
    client = TestClient(appmod.create_app())
    r = client.post("/api/sql", json={"sql": "SELECT 1 AS one"})
    assert r.status_code == 200 and r.json()["rows"] == [[1]]
    assert client.post("/api/sql", json={"sql": "DELETE FROM vi.videos"}).status_code == 400
    assert "vi.videos" in [t["name"] for t in client.get("/api/sql/catalog").json()["tables"]]
