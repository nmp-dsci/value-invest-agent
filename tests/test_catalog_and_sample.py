from datetime import date, datetime, timezone

from value_invest.catalog.build import year_bucket
from value_invest.sample import draw_sample


def test_year_bucket_is_twelve_month_windows():
    since, until = date(2022, 9, 17), date(2026, 9, 17)
    assert year_bucket(date(2022, 9, 17), since, until) == "2022/23"
    assert year_bucket(date(2023, 9, 16), since, until) == "2022/23"
    assert year_bucket(date(2023, 9, 17), since, until) == "2023/24"
    assert year_bucket(date(2026, 9, 17), since, until) == "2025/26"
    assert year_bucket(date(2022, 9, 16), since, until) is None


def _video(con, vid, d, kind="single", ticker="NKE", conf=0.9):
    yb = year_bucket(d, date(2022, 9, 17), date(2026, 9, 17))
    con.execute("INSERT INTO vi.videos (video_id, title, published_at, kind, primary_ticker, year_bucket, catalogued_at) VALUES (?, ?, ?, ?, ?, ?, ?)", [vid, vid, d, kind, ticker, yb, datetime.now(timezone.utc)])
    con.execute("INSERT INTO vi.title_labels VALUES (?, ?, '[]', ?, '', 'llm', 'test', ?)", [vid, kind, conf, datetime.now(timezone.utc)])


def test_sample_is_seeded_stratified_and_extends(con):
    d0 = date(2022, 9, 17)
    n = 0
    for y in range(4):
        for m in range(12):
            for k in range(3):
                n += 1
                _video(con, f"v{n}", date(d0.year + y + (1 if m >= 4 else 0), ((d0.month - 1 + m) % 12) + 1, 1 + k), ticker=f"T{n % 17}")
    _video(con, "macro1", date(2023, 1, 5), kind="macro", ticker=None)
    _video(con, "lowconf", date(2023, 1, 6), conf=0.3)
    r10 = draw_sample(con, per_year=10, seed=42)
    assert r10["sampled"] == 40 and set(r10["per_bucket"].values()) == {10}
    picks10 = dict(con.execute("SELECT video_id, sample_rank FROM vi.videos WHERE in_sample").fetchall())
    assert "macro1" not in picks10 and "lowconf" not in picks10
    # quarters are spread: no window year draws more than 4 from one quarter
    q = con.execute("SELECT year_bucket, (month(published_at)-1)//3, count(*) FROM vi.videos WHERE in_sample GROUP BY 1,2").fetchall()
    assert max(r[2] for r in q) <= 4
    r12 = draw_sample(con, per_year=12, seed=42)
    picks12 = dict(con.execute("SELECT video_id, sample_rank FROM vi.videos WHERE in_sample").fetchall())
    assert r12["sampled"] == 48
    for vid, rank in picks10.items():  # raising per-year only adds; earlier picks keep their rank
        assert picks12[vid] == rank
    draw_sample(con, per_year=10, seed=42)
    assert dict(con.execute("SELECT video_id, sample_rank FROM vi.videos WHERE in_sample").fetchall()) == picks10
