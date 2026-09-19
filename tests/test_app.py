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
    from value_invest.config import settings

    assert f["listed"] == 0 and f["per_year_target"] == settings().sample_per_year
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


def test_evals_endpoints_on_an_empty_and_a_seeded_db(monkeypatch, tmp_path):
    import json
    from datetime import date

    from value_invest import db
    from value_invest.serving import app as appmod

    p = tmp_path / "t.duckdb"
    w = db.connect(p)
    w.execute(
        "INSERT INTO vi.videos (video_id, title, published_at, kind, primary_ticker, year_bucket, in_sample, date_source) VALUES ('v1', 'Apple Stock Intrinsic Value is $105', ?, 'single', 'AAPL', '2024/25', TRUE, 'yt-dlp')",
        [date(2025, 1, 21)],
    )
    w.execute(
        """INSERT INTO vi.evals (video_id, ticker, t0, position, stance_detail, personal_action, expected_return_pct, conviction,
             rule_sensitive, title_says_buy, headline_quote, valuation, iv_weighted_stated, iv_recomputed, price_at_t0, reasons,
             external_facts, critic, checks, extractor_version, model, split, curation_status)
           VALUES ('v1', 'AAPL', ?, 'SELL', 'avoid', 'none', 0, 'high', FALSE, FALSE, 'q', ?, 100, '{}', 222.6, ?, '[]', ?, ?, 'v0', 'sonnet', 'test', 'auto')""",
        [
            date(2025, 1, 21),
            json.dumps({"method": "eps_multiple", "scenarios": []}),
            json.dumps(
                [
                    {
                        "rank": 1,
                        "direction": "for_sell",
                        "category": "valuation",
                        "claim": "c",
                        "quote": "q",
                        "chunk_id": None,
                        "start_s": 1,
                        "feeds": "none",
                        "metrics": [],
                        "data_check": {
                            "reproducible": "derived",
                            "line_items": [],
                            "value_stated": None,
                            "value_as_of": None,
                            "agrees": True,
                            "formula": None,
                            "as_of_period": None,
                            "gap_note": None,
                        },
                    }
                ]
            ),
            json.dumps(
                {
                    "faithful": True,
                    "position_agrees": True,
                    "own_stance_detail": "avoid",
                    "quotes_total": 1,
                    "quotes_verbatim": 1,
                    "invented_reasons": [],
                    "notes": "ok",
                }
            ),
            json.dumps(
                {
                    "reproducible_share": 1.0,
                    "faithful_share": 1.0,
                    "price_check": True,
                    "iv_ok": 2,
                    "iv_compared": 2,
                }
            ),
        ],
    )
    w.execute(
        "INSERT INTO vi.validations VALUES ('v1', 12, ?, ?, -0.05, 0.10, -0.15, 'correct', 'correct', FALSE)",
        [date(2025, 1, 21), date(2026, 1, 21)],
    )
    w.close()
    monkeypatch.setattr(
        db,
        "connect",
        lambda path=None, read_only=False: __import__("duckdb").connect(
            str(p), read_only=read_only
        ),
    )
    client = TestClient(appmod.create_app())
    rows = client.get("/api/evals").json()
    assert (
        len(rows) == 1
        and rows[0]["position"] == "SELL"
        and rows[0]["binary_position"] == "SELL"
        and rows[0]["hurdle_position"] == "SELL"
    )
    assert rows[0]["validations"]["12"]["verdict"] == "correct" and rows[0][
        "reason_categories"
    ] == ["valuation"]
    s = client.get("/api/evals/summary").json()
    assert s["stats"]["n"] == 1 and s["validation"]["overall"]["12"]["hits"]["SELL"] == [1, 1]
    assert {c["rule"] for c in s["cuts"]} == {"C · 3-way", "A · binary", "B · hurdle"}
    d = client.get("/api/evals/v1").json()
    assert (
        d["reasons"][0]["data_check"]["reproducible"] == "derived"
        and d["validations"][0]["horizon_m"] == 12
    )
    assert client.get("/api/evals/nope").status_code == 404
    v = client.get("/api/videos/v1").json()
    assert v["eval"]["position"] == "SELL"
    r = client.post(
        "/api/evals/v1/review",
        json={"curation_status": "reviewed", "note": "ok", "stance_detail": "fair_hold"},
    )
    assert r.status_code == 200 and r.json()["position"] == "HOLD"
    assert client.get("/api/evals/v1").json()["curation_status"] == "reviewed"
