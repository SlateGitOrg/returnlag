"""Staging: as-of filtering, season segments and rejected returns."""

from __future__ import annotations

from returnlag import warehouse as wh
from returnlag.generate import is_holiday_week


def test_staging_rejects_exactly_the_37_returns_dated_before_shipment(make_con, dataset):
    con = make_con(104)
    rejects = con.execute("SELECT return_id, reason FROM dq_rejects ORDER BY return_id").fetchall()
    assert len(rejects) == 37
    assert {reason for _, reason in rejects} == {"returned_before_shipment"}
    assert [rid for rid, _ in rejects] == dataset.truth["bad_scan_return_ids"]
    staged = con.execute("SELECT count(*) FROM stg_returns").fetchone()[0]
    assert staged == dataset.n_returns - 37


def test_as_of_week_caps_every_staged_date(make_con):
    con = make_con(50)
    ship_max, return_max = con.execute(
        "SELECT max(ship_week), (SELECT max(return_week) FROM stg_returns) FROM stg_shipments"
    ).fetchone()
    assert ship_max == 50 and return_max == 50
    deepest = con.execute("SELECT max(ship_week + dev_week) FROM int_triangle").fetchone()[0]
    assert deepest == 50


def test_season_segment_follows_iso_weeks_46_to_52(make_con):
    con = make_con(104)
    rows = con.execute(
        "SELECT DISTINCT ship_week, segment FROM stg_shipments ORDER BY ship_week"
    ).fetchall()
    assert len(rows) == 104
    for week, segment in rows:
        assert segment == ("holiday" if is_holiday_week(week) else "regular")
    assert [w for w, s in rows if s == "holiday"] == list(range(20, 27)) + list(range(72, 79))


def test_unmatched_and_out_of_window_returns_are_rejected_with_reasons(fixture_con):
    fixture_con.execute(
        "INSERT INTO raw_shipments VALUES (1, DATE '2024-07-01', 'tops', 50), "
        "(2, DATE '2024-07-29', 'tops', 50)"
    )
    fixture_con.execute(
        """
        INSERT INTO raw_returns VALUES
            (1, 1, DATE '2024-07-10', 'A'),
            (2, 1, DATE '2024-06-28', 'A'),
            (3, 2, DATE '2024-07-08', 'A'),
            (4, 1, DATE '2024-10-14', 'A'),
            (5, 9, DATE '2024-07-09', 'A')
        """
    )
    wh.build(fixture_con, 5)  # week 5 ends 2024-08-04: shipment 2 (week 5) is known
    reasons = dict(fixture_con.execute("SELECT return_id, reason FROM dq_rejects").fetchall())
    assert reasons == {
        2: "returned_before_shipment",
        3: "returned_before_shipment",
        5: "no_shipment_by_as_of",
    }
    assert fixture_con.execute("SELECT return_id FROM stg_returns").fetchall() == [(1,)]
    # Return 4 is dated in week 16: outside the as-of window, not yet visible.
    wh.build(fixture_con, 16)
    reasons = dict(fixture_con.execute("SELECT return_id, reason FROM dq_rejects").fetchall())
    assert reasons[4] == "beyond_development_window"


def test_units_shipped_per_cohort_are_summed_across_days(make_con, dataset):
    con = make_con(104)
    total = con.execute(
        "SELECT sum(units_shipped) FROM (SELECT DISTINCT * FROM int_triangle WHERE dev_week = 0)"
    ).fetchone()[0]
    assert total == dataset.n_shipped


def test_as_of_week_must_be_set_through_a_duckdb_variable(make_con):
    con = make_con(60)
    assert con.execute("SELECT getvariable('asof_week')").fetchone()[0] == 60
    assert wh.last_built_week(con) == 60
    wh.build(con, 61)
    assert con.execute("SELECT max(ship_week) FROM stg_shipments").fetchone()[0] == 61


def test_required_sql_checks_are_present():
    names = {p.stem for p in wh.check_files()}
    assert {
        "cumulative_non_decreasing",
        "cdf_at_least_one",
        "ultimate_at_least_observed",
        "no_return_before_shipment",
    } <= names
