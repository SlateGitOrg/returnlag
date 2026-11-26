"""No later data leaks into an as-of build, and the SQL data-quality queries bite."""

from __future__ import annotations

import pytest

from returnlag import config
from returnlag import warehouse as wh

AS_OF = 80
LAST_DAY = f"(DATE '{config.WEEK1_START}' + {AS_OF * 7 - 1})"


def _rounded(rows):
    """Parallel float sums can differ in the last bit between runs: compare to 9 places."""
    return [tuple(round(v, 9) if isinstance(v, float) else v for v in row) for row in rows]


def _snapshot(con):
    return {
        table: _rounded(con.execute(f"SELECT * FROM {table} ORDER BY ALL").fetchall())
        for table in wh.MODEL_TABLES
    }


def test_changing_returns_dated_after_week_80_leaves_every_table_unchanged(make_con):
    con = make_con(AS_OF)
    before = _snapshot(con)
    assert all(before[t] for t in ("stg_returns", "int_triangle", "fct_ultimates"))

    con.execute(f"UPDATE raw_returns SET grade = 'C' WHERE return_date > {LAST_DAY}")
    con.execute(
        f"UPDATE raw_returns SET return_date = return_date + 4 WHERE return_date > {LAST_DAY}"
    )
    con.execute(f"DELETE FROM raw_returns WHERE return_date > {LAST_DAY} AND return_id % 3 = 0")
    con.execute(
        "INSERT INTO raw_returns SELECT 900000 + row_number() OVER (), shipment_id, "
        f"{LAST_DAY} + 9, 'B' FROM raw_shipments WHERE ship_date <= {LAST_DAY} - 30 LIMIT 40"
    )
    changed = con.execute(
        f"SELECT count(*) FROM raw_returns WHERE return_date > {LAST_DAY}"
    ).fetchone()
    assert changed[0] > 1000
    wh.build(con, AS_OF)
    assert _snapshot(con) == before


def test_changing_shipments_dated_after_week_80_leaves_every_table_unchanged(make_con):
    con = make_con(AS_OF)
    before = _snapshot(con)
    con.execute(f"UPDATE raw_shipments SET units = units * 3 WHERE ship_date > {LAST_DAY}")
    wh.build(con, AS_OF)
    assert _snapshot(con) == before


def test_the_leakage_comparison_would_notice_a_change_inside_the_window(make_con):
    con = make_con(AS_OF)
    before = _snapshot(con)
    con.execute(
        f"UPDATE raw_returns SET return_date = return_date - 7 "
        f"WHERE return_date <= {LAST_DAY} AND return_date > {LAST_DAY} - 21 AND return_id % 2 = 0"
    )
    wh.build(con, AS_OF)
    assert _snapshot(con)["int_triangle"] != before["int_triangle"]


@pytest.mark.parametrize("as_of", [40, 80, 104])
def test_all_sql_checks_return_zero_rows(make_con, as_of):
    con = make_con(as_of)
    results = wh.run_checks(con)
    assert len(results) >= 4
    assert {name: rows for name, rows in results.items() if rows} == {}


def test_cumulative_check_flags_a_decreasing_triangle(make_con):
    con = make_con(80)
    con.execute(
        "UPDATE int_triangle SET cum_returned = cum_returned - 5 "
        "WHERE category = 'tops' AND ship_week = 50 AND dev_week = 3"
    )
    rows = wh.run_checks(con)["cumulative_non_decreasing"]
    assert rows and rows[0][:3] == ("tops", 50, 2)


def test_cdf_and_ultimate_checks_flag_bad_values(make_con):
    con = make_con(80)
    con.execute("UPDATE int_cdf SET cdf = 0.9 WHERE category = 'denim' AND dev_week = 5")
    con.execute(
        "UPDATE fct_ultimates SET chain_ladder_rate = observed_rate / 2 WHERE ship_week = 40"
    )
    results = wh.run_checks(con)
    assert results["cdf_at_least_one"]
    assert results["ultimate_at_least_observed"]


def test_before_shipment_check_flags_an_unstaged_scan(make_con):
    con = make_con(80)
    con.execute("UPDATE stg_returns SET return_date = ship_date - 2 WHERE return_id = 100")
    rows = wh.run_checks(con)["no_return_before_shipment"]
    assert [r[0] for r in rows] == [100]
