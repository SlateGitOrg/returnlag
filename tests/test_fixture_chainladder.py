"""Hand-computed 3-cohort fixture: the SQL reproduces chain-ladder and BF by hand."""

from __future__ import annotations

import pytest
from conftest import load_triangle_fixture

from returnlag import warehouse as wh

CUMULATIVE = [[10, 18, 20], [12, 21], [15]]


@pytest.fixture
def built(fixture_con):
    load_triangle_fixture(fixture_con, 100, CUMULATIVE)
    wh.build(fixture_con, 3)
    return fixture_con


def test_triangle_holds_only_observable_cells(built):
    rows = built.execute(
        "SELECT ship_week, dev_week, cum_returned FROM int_triangle ORDER BY 1, 2"
    ).fetchall()
    assert rows == [(1, 0, 10), (1, 1, 18), (1, 2, 20), (2, 0, 12), (2, 1, 21), (3, 0, 15)]


def test_age_to_age_factors_are_volume_weighted(built):
    f = dict(
        built.execute("SELECT from_dev, factor FROM int_factors WHERE from_dev <= 3").fetchall()
    )
    assert f[0] == pytest.approx(39 / 22)  # 1.772727
    assert f[1] == pytest.approx(20 / 18)  # 1.111111
    assert f[2] == 1.0 and f[3] == 1.0  # nothing observable: neutral


def test_tail_factor_is_one_after_week_twelve(built):
    row = built.execute("SELECT factor FROM int_factors WHERE from_dev = 12").fetchone()
    assert row == (1.0,)


def test_cumulative_development_factor_is_product_of_factors(built):
    cdf = dict(built.execute("SELECT dev_week, cdf FROM int_cdf").fetchall())
    assert cdf[0] == pytest.approx(1.969697, abs=1e-6)
    assert cdf[1] == pytest.approx(20 / 18)
    assert cdf[2] == pytest.approx(1.0)
    assert cdf[12] == 1.0


def test_chain_ladder_ultimates_match_hand_computation(built):
    rows = built.execute(
        "SELECT ship_week, chain_ladder_rate FROM fct_ultimates ORDER BY ship_week"
    ).fetchall()
    assert [round(r * 100, 2) for _, r in rows] == [20.00, 23.33, 29.55]


def test_bornhuetter_ferguson_with_a_22_percent_prior(built):
    built.execute(
        "CREATE OR REPLACE TABLE int_prior AS SELECT 'dresses' AS category, "
        "'regular' AS segment, 0.22 AS prior_rate, 26 AS n_cohorts, 'segment' AS prior_source"
    )
    wh.build(built, 3, only=["fct_ultimates"])
    bf = dict(built.execute("SELECT ship_week, bf_rate FROM fct_ultimates").fetchall())
    assert bf[1] == pytest.approx(0.20)  # fully developed: the prior has no weight
    assert round(bf[2] * 100, 2) == 23.20
    assert round(bf[3] * 100, 2) == 25.83


def test_credibility_is_the_inverse_of_the_cdf(built):
    for cdf, credibility in built.execute("SELECT cdf, credibility FROM fct_ultimates").fetchall():
        assert credibility == pytest.approx(1 / cdf)


def test_bf_falls_back_to_chain_ladder_without_a_mature_cohort(built):
    assert built.execute("SELECT count(*) FROM int_prior WHERE prior_source = 'none'").fetchone()[0]
    rows = built.execute("SELECT chain_ladder_rate, bf_rate FROM fct_ultimates").fetchall()
    assert all(cl == pytest.approx(bf) for cl, bf in rows)


def test_pooled_factors_equal_segmented_when_one_segment(built):
    seg = [r[0] for r in built.execute("SELECT cdf FROM int_cdf ORDER BY dev_week").fetchall()]
    pooled = [
        r[0] for r in built.execute("SELECT cdf FROM int_cdf_pooled ORDER BY dev_week").fetchall()
    ]
    assert seg == pytest.approx(pooled)


def test_inbound_forecast_splits_the_remaining_returns_by_pattern(built):
    # Cohort 3 (age 0): chain-ladder ultimate 29.545 units, 15 observed, 14.545 still to come.
    # dev 1 gets (1/1.1111 - 1/1.9697) and dev 2 gets (1 - 1/1.1111) of the not-yet-developed share.
    rows = built.execute(
        """
        SELECT forecast_week, sum(expected_returns) FROM fct_inbound_forecast
        WHERE method = 'chain_ladder' AND expected_returns > 1e-9 GROUP BY 1 ORDER BY 1
        """
    ).fetchall()
    by_week = dict(rows)
    assert set(by_week) == {4, 5}  # cohort 3 dev 1, dev 2 (week 4, 5) and cohort 2 dev 2 (week 4)
    remaining_c3 = 100 * (0.2954545 - 0.15)
    share1 = (0.9 - 1 / 1.969697) / (1 - 1 / 1.969697)
    c2_dev2 = 100 * (0.2333333 - 0.21)  # cohort 2: age 1, only dev 2 is left
    assert by_week[4] == pytest.approx(remaining_c3 * share1 + c2_dev2, abs=1e-3)
    assert by_week[5] == pytest.approx(remaining_c3 * (1 - share1), abs=1e-3)
    assert sum(by_week.values()) == pytest.approx(remaining_c3 + c2_dev2, abs=1e-3)
