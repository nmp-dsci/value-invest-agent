"""EDGAR companyfacts → annual statements: full-year values only, earliest filing wins, outflows negated."""

from datetime import date

from value_invest.market.edgar import annual_statements


def _e(start, end, val, filed, fp="FY", form="10-K"):
    d = {"end": end, "val": val, "filed": filed, "fp": fp, "form": form}
    if start:
        d["start"] = start
    return d


FACTS = {
    "facts": {
        "us-gaap": {
            "Revenues": {
                "units": {
                    "USD": [
                        _e("2021-10-01", "2022-09-30", 100.0, "2022-11-01"),
                        _e(
                            "2021-10-01", "2022-09-30", 101.0, "2023-11-01"
                        ),  # restated later: ignored
                        _e(
                            "2022-07-01", "2022-09-30", 30.0, "2022-11-01"
                        ),  # a quarter inside the FY: ignored
                        _e("2022-10-01", "2023-09-30", 120.0, "2023-11-01"),
                        _e(
                            "2022-10-01", "2023-09-30", 999.0, "2023-11-01", fp="Q4", form="10-Q"
                        ),  # wrong form/fp
                    ]
                }
            },
            "Assets": {
                "units": {
                    "USD": [
                        _e(None, "2022-09-30", 500.0, "2022-11-01"),
                        _e(None, "2023-09-30", 550.0, "2023-11-01"),
                    ]
                }
            },
            "AssetsCurrent": {"units": {"USD": [_e(None, "2023-09-30", 200.0, "2023-11-01")]}},
            "LiabilitiesCurrent": {"units": {"USD": [_e(None, "2023-09-30", 150.0, "2023-11-01")]}},
            "NetCashProvidedByUsedInOperatingActivities": {
                "units": {"USD": [_e("2022-10-01", "2023-09-30", 40.0, "2023-11-01")]}
            },
            "PaymentsToAcquirePropertyPlantAndEquipment": {
                "units": {"USD": [_e("2022-10-01", "2023-09-30", 10.0, "2023-11-01")]}
            },
        }
    }
}


def test_annual_statements_selection_and_derivation():
    df = annual_statements("TEST", FACTS)
    rows = {(r.period_end, r.kind, r.line_item): r for r in df.itertuples()}
    rev22 = rows[(date(2022, 9, 30), "income", "Total Revenue")]
    assert (
        rev22.value == 100.0
        and rev22.filed_at == date(2022, 11, 1)
        and rev22.available_from == date(2022, 11, 1)
    )
    assert rows[(date(2023, 9, 30), "income", "Total Revenue")].value == 120.0
    assert (date(2022, 9, 30), "income", "Total Revenue") in rows and len(
        [k for k in rows if k[2] == "Total Revenue"]
    ) == 2
    assert rows[(date(2023, 9, 30), "cashflow", "Capital Expenditure")].value == -10.0
    assert rows[(date(2023, 9, 30), "cashflow", "Free Cash Flow")].value == 30.0
    assert rows[(date(2023, 9, 30), "balance", "Working Capital")].value == 50.0
    assert set(df["source"]) == {"edgar"}


def test_fiscal_years_view_merges_sources_by_year(con):
    con.executemany(
        "INSERT INTO vi.statements VALUES (?, ?, ?, 'annual', ?, ?, ?, ?, ?)",
        [
            (
                "AAPL",
                date(2025, 9, 30),
                "income",
                "Total Revenue",
                1.0,
                None,
                date(2025, 12, 29),
                "yfinance",
            ),
            (
                "AAPL",
                date(2025, 9, 30),
                "balance",
                "Total Assets",
                1.0,
                None,
                date(2025, 12, 29),
                "yfinance",
            ),
            (
                "AAPL",
                date(2025, 9, 27),
                "income",
                "Total Revenue",
                1.0,
                date(2025, 10, 31),
                date(2025, 10, 31),
                "edgar",
            ),
            (
                "AAPL",
                date(2025, 9, 27),
                "balance",
                "Total Assets",
                1.0,
                date(2025, 10, 31),
                date(2025, 10, 31),
                "edgar",
            ),
        ],
    )
    rows = con.execute(
        "SELECT fy, available_from, complete, from_edgar FROM vi.fiscal_years WHERE ticker='AAPL'"
    ).fetchall()
    assert rows == [
        (2025, date(2025, 10, 31), True, True)
    ]  # one year, visible from the real filing date
