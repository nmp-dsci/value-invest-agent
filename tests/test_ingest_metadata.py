"""vi ingest hands transcript·lab the metadata it already has, so Supadata bills one credit."""

import json


def test_supadata_shaped_metadata_from_ytdlp_cache(tmp_path, monkeypatch):
    from value_invest import config
    from value_invest.ingest import run

    monkeypatch.setattr(
        config, "settings", lambda: config.Settings(supadata_api_key="k", cache_dir=tmp_path)
    )
    monkeypatch.setattr(run, "settings", config.settings)
    (tmp_path / "ytdlp").mkdir()
    (tmp_path / "ytdlp" / "abc123def45.json").write_text(
        json.dumps(
            {
                "id": "abc123def45",
                "title": "Nike Stock",
                "description": "d",
                "timestamp": 1719878400,
                "duration": 600,
                "view_count": 12,
                "channel_id": "UCx",
            }
        )
    )
    import value_invest.catalog.supadata as sd
    import value_invest.catalog.ytdlp as yd

    monkeypatch.setattr(sd, "settings", config.settings)
    monkeypatch.setattr(yd, "settings", config.settings)

    meta = run.supadata_shaped_metadata("abc123def45")
    assert meta["title"] == "Nike Stock"
    assert meta["createdAt"].startswith("2024-07-02")
    assert meta["media"]["duration"] == 600 and meta["stats"]["views"] == 12
    assert meta["additionalData"]["channelId"] == "UCx"
    assert run.supadata_shaped_metadata("nope") is None
