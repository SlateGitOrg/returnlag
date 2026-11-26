"""The analysis recovers what the generator injected."""

from __future__ import annotations

import pytest

from returnlag import warehouse as wh
from returnlag.generate import CATEGORIES


def _weighted(con, column, category, lo, hi):
    return con.execute(
        f"SELECT sum({column} * units_shipped) / sum(units_shipped) FROM fct_ultimates "
        "WHERE category = ? AND ship_week BETWEEN ? AND ?",
        [category, lo, hi],
    ).fetchone()[0]


def test_fully_developed_dresses_cohorts_show_the_size_guide_fix(make_con):
    con = make_con(104)
    before = _weighted(con, "observed_rate", "dresses", 60, 83)
    after = _weighted(con, "observed_rate", "dresses", 84, 91)
    assert before == pytest.approx(0.36, abs=0.015)
    assert after == pytest.approx(0.29, abs=0.02)
    ages = con.execute(
        "SELECT min(age_weeks) FROM fct_ultimates WHERE category = 'dresses' "
        "AND ship_week BETWEEN 60 AND 91"
    ).fetchone()[0]
    assert ages >= 13


def test_all_categories_recover_their_true_rate(make_con):
    con = make_con(104)
    for category, spec in CATEGORIES.items():
        if category == "dresses":
            continue
        rate = _weighted(con, "observed_rate", category, 5, 91)
        assert rate == pytest.approx(spec.true_rate, abs=0.012), category


def test_chain_ladder_sees_through_young_dresses_cohorts_as_of_week_96(make_con):
    con = make_con(96)
    ages = con.execute(
        "SELECT min(age_weeks), max(age_weeks) FROM fct_ultimates "
        "WHERE category = 'dresses' AND ship_week BETWEEN 87 AND 93"
    ).fetchone()
    assert ages == (3, 9)
    chain_ladder = _weighted(con, "chain_ladder_rate", "dresses", 87, 93)
    naive = _weighted(con, "observed_rate", "dresses", 87, 93)
    assert chain_ladder == pytest.approx(0.29, abs=0.03)
    assert naive < 0.24


def test_recent_months_look_best_without_development(make_con):
    con = make_con(104)
    rate = {
        week: r
        for week, r in con.execute(
            "SELECT ship_week, sum(observed_returns)::DOUBLE / sum(units_shipped) "
            "FROM fct_ultimates WHERE ship_week IN (60, 98, 102, 104) GROUP BY 1"
        ).fetchall()
    }
    assert rate[104] < 0.5 * rate[60]
    assert rate[102] < rate[98] < rate[60]


def test_segmented_factors_are_slower_for_the_holiday_season(make_con):
    con = make_con(90)
    pct = dict(
        con.execute(
            "SELECT segment, pct_developed FROM int_cdf WHERE category = 'dresses' AND dev_week = 6"
        ).fetchall()
    )
    assert pct["holiday"] < pct["regular"] - 0.10


def test_bf_prior_uses_the_26_most_recent_mature_cohorts_of_the_segment(make_con):
    con = make_con(96)
    prior, n, source = con.execute(
        "SELECT prior_rate, n_cohorts, prior_source FROM int_prior "
        "WHERE category = 'dresses' AND segment = 'regular'"
    ).fetchone()
    assert (n, source) == (26, "segment")
    # Mature = aged >= 13 weeks, i.e. ship week <= 83; regular weeks only.
    expected = con.execute(
        """
        WITH recent AS (
            SELECT units_shipped, cum_returned FROM int_triangle
            WHERE category = 'dresses' AND segment = 'regular' AND dev_week = 12
                AND ship_week <= 83
            ORDER BY ship_week DESC LIMIT 26
        )
        SELECT sum(cum_returned)::DOUBLE / sum(units_shipped) FROM recent
        """
    ).fetchone()[0]
    assert prior == pytest.approx(expected)


def test_inbound_forecast_matches_actual_arrivals_as_of_week_90(make_con):
    con = make_con(90)
    forecast = {
        method: total
        for method, total in con.execute(
            "SELECT method, sum(expected_returns) FROM fct_inbound_forecast "
            "WHERE forecast_week BETWEEN 91 AND 98 GROUP BY method"
        ).fetchall()
    }
    actual = con_actual_arrivals(make_con)
    assert actual > 800
    for method, total in forecast.items():
        assert total == pytest.approx(actual, rel=0.08), method


def con_actual_arrivals(make_con) -> int:
    full = make_con(104)
    return full.execute(
        "SELECT count(*) FROM stg_returns WHERE ship_week <= 90 AND return_week BETWEEN 91 AND 98"
    ).fetchone()[0]


def test_inbound_forecast_covers_the_remaining_development_horizon(make_con):
    con = make_con(104)
    weeks = con.execute(
        "SELECT min(weeks_ahead), max(weeks_ahead) FROM fct_inbound_forecast "
        "WHERE expected_returns > 1e-9"
    ).fetchone()
    assert weeks == (1, 12)
    first, last = con.execute(
        "SELECT sum(expected_returns) FILTER (weeks_ahead = 1), "
        "sum(expected_returns) FILTER (weeks_ahead = 12) FROM fct_inbound_forecast "
        "WHERE method = 'bornhuetter_ferguson'"
    ).fetchone()
    assert first > 10 * last


def test_disposition_grade_mix_and_recovery(make_con):
    con = make_con(104)
    rows = con.execute(
        "SELECT category, grade, share_of_category, recovery_pct FROM mart_disposition"
    ).fetchall()
    assert len(rows) == 18
    recovery = {g: r for _, g, _, r in rows}
    assert recovery == {"A": 0.92, "B": 0.58, "C": 0.12}
    for category, grade, share, _ in rows:
        expected = dict(zip("ABC", CATEGORIES[category].grade_mix, strict=True))[grade]
        assert share == pytest.approx(expected, abs=0.04), (category, grade)


def test_net_return_cost_is_refund_minus_recovery_plus_handling(make_con):
    con = make_con(104)
    price = dict(con.execute("SELECT category, unit_price FROM ref_category_economics").fetchall())
    handling = dict(
        con.execute("SELECT category, handling_cost FROM ref_category_economics").fetchall()
    )
    recovery = dict(con.execute("SELECT grade, recovery_pct FROM ref_grade").fetchall())
    counts = con.execute(
        "SELECT category, grade, count(*) FROM stg_returns GROUP BY ALL"
    ).fetchall()
    expected = {}
    for category, grade, n in counts:
        unit = price[category] * (1 - recovery[grade]) + handling[category]
        expected[category] = expected.get(category, 0.0) + n * unit
    got = dict(con.execute("SELECT category, net_cost FROM mart_net_return_cost").fetchall())
    assert got == pytest.approx(expected)
    per_return = dict(
        con.execute("SELECT category, net_cost_per_return FROM mart_net_return_cost").fetchall()
    )
    assert max(per_return, key=per_return.get) == "outerwear"
    assert min(per_return, key=per_return.get) == "accessories"


def test_models_run_in_filename_order_and_rebuild_cleanly(make_con):
    con = make_con()
    first = wh.build(con, 70)
    second = wh.build(con, 70)
    assert first == second
    assert first[0] == "stg_shipments" and first[-1] == "mart_disposition"


def test_disposition_economics_come_from_config(make_con, monkeypatch):
    from returnlag import config

    con = make_con(104)
    base = dict(con.execute("SELECT category, net_cost FROM mart_net_return_cost").fetchall())
    monkeypatch.setitem(config.GRADE_RECOVERY, "C", ("liquidate", 0.0))
    wh.build(con, 104)
    assert con.execute("SELECT recovery_pct FROM ref_grade WHERE grade = 'C'").fetchone() == (0.0,)
    changed = dict(con.execute("SELECT category, net_cost FROM mart_net_return_cost").fetchall())
    assert all(changed[c] > base[c] for c in base)
