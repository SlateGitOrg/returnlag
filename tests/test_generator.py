"""The generator produces the documented properties and is deterministic."""

from __future__ import annotations

import csv
import json

import numpy as np
import pytest

from returnlag.generate import CATEGORIES, PROMO_WEEKS, generate, is_holiday_week


@pytest.fixture(scope="module")
def lags(dataset):
    """Per-return arrays: category, ship week, lag in days (negative for scanner errors)."""
    ship = {
        int(s): (int(d), c)
        for s, d, c in zip(dataset.shipment_id, dataset.ship_day, dataset.category, strict=True)
    }
    ship_day = np.array([ship[int(s)][0] for s in dataset.return_shipment_id])
    category = np.array([ship[int(s)][1] for s in dataset.return_shipment_id])
    return {
        "category": category,
        "ship_day": ship_day,
        "ship_week": ship_day // 7 + 1,
        "lag": dataset.return_day - ship_day,
    }


def test_volumes_match_the_brief(dataset):
    assert 140_000 <= dataset.n_shipped <= 155_000
    assert 31_000 <= dataset.n_returns <= 35_000
    assert dataset.ship_day.max() // 7 + 1 == 104


def test_same_seed_gives_identical_data_and_other_seeds_differ(dataset):
    again = generate(seed=7, weeks=20)
    first_weeks = dataset.ship_day < 20 * 7
    assert np.array_equal(again.units, dataset.units[first_weeks])
    other = generate(seed=8, weeks=20)
    assert not np.array_equal(other.units, again.units)


def test_true_return_rates_are_recovered(dataset, lags):
    shipped = {}
    ship_week = dataset.ship_day // 7 + 1
    for cat in CATEGORIES:
        mask = (dataset.category == cat) & (ship_week >= 5) & (ship_week <= 83)
        shipped[cat] = dataset.units[mask].sum()
    for cat, spec in CATEGORIES.items():
        mask = (lags["category"] == cat) & (lags["ship_week"] >= 5) & (lags["ship_week"] <= 83)
        rate = mask.sum() / shipped[cat]
        assert rate == pytest.approx(spec.true_rate, abs=0.012), cat


def test_dresses_rate_drops_after_the_size_guide_fix(dataset, lags):
    def rate(lo, hi):
        shipped = dataset.units[
            (dataset.category == "dresses")
            & (dataset.ship_day // 7 + 1 >= lo)
            & (dataset.ship_day // 7 + 1 <= hi)
        ].sum()
        returned = (
            (lags["category"] == "dresses") & (lags["ship_week"] >= lo) & (lags["ship_week"] <= hi)
        ).sum()
        return returned / shipped

    assert rate(60, 83) == pytest.approx(0.36, abs=0.015)
    assert rate(84, 91) == pytest.approx(0.29, abs=0.02)


@pytest.mark.parametrize(
    ("category", "median"), [("footwear", 9), ("dresses", 14), ("outerwear", 18)]
)
def test_median_return_lag_by_category(dataset, lags, category, median):
    holiday = np.array([is_holiday_week(int(w)) for w in lags["ship_week"]])
    mask = (lags["category"] == category) & ~holiday & (lags["lag"] >= 0)
    assert np.median(lags["lag"][mask]) == pytest.approx(median, abs=1.0)


def test_holiday_lags_are_stretched(lags):
    holiday = np.array([is_holiday_week(int(w)) for w in lags["ship_week"]])
    mask = (lags["category"] == "dresses") & (lags["lag"] >= 0)
    ratio = np.median(lags["lag"][mask & holiday]) / np.median(lags["lag"][mask & ~holiday])
    # The stretch is 1.8, trimmed by the 90-day ceiling on the long tail.
    assert 1.3 <= ratio <= 1.9


def test_late_returns_are_three_percent_and_none_after_day_90(lags):
    holiday = np.array([is_holiday_week(int(w)) for w in lags["ship_week"]])
    regular = lags["lag"][~holiday & (lags["lag"] >= 0)]
    assert 0.015 <= (regular > 60).mean() <= 0.04
    assert lags["lag"].max() <= 90


def test_no_return_lands_more_than_twelve_calendar_weeks_after_the_ship_week(dataset, lags):
    valid = lags["lag"] >= 0
    dev = dataset.return_day // 7 - lags["ship_day"] // 7
    assert dev[valid].max() == 12


def test_no_return_is_dated_after_the_cutoff(dataset):
    assert dataset.return_day.max() <= 104 * 7 - 1


def test_promotion_doubles_volume_at_unchanged_rates(dataset, lags):
    week = dataset.ship_day // 7 + 1
    weekly = np.bincount(week, weights=dataset.units, minlength=105)
    promo = weekly[list(PROMO_WEEKS)].mean()
    around = np.concatenate([weekly[46:52], weekly[58:64]]).mean()
    assert 1.8 <= promo / around <= 2.2
    promo_returns = np.isin(lags["ship_week"], PROMO_WEEKS).sum()
    assert promo_returns / weekly[list(PROMO_WEEKS)].sum() == pytest.approx(0.225, abs=0.03)


def test_exactly_37_returns_are_dated_before_their_shipment(dataset, lags):
    bad_ids = dataset.return_id[lags["lag"] < 0]
    assert len(bad_ids) == 37
    assert bad_ids.tolist() == dataset.truth["bad_scan_return_ids"]


def test_csv_files_round_trip(data_dir, dataset):
    with open(data_dir / "shipments.csv") as fh:
        rows = list(csv.DictReader(fh))
    assert len(rows) == dataset.shipment_id.size
    assert sum(int(r["units"]) for r in rows) == dataset.n_shipped
    assert rows[0]["ship_date"] == "2024-07-01"
    with open(data_dir / "returns.csv") as fh:
        header = next(csv.reader(fh))
    assert header == ["return_id", "shipment_id", "return_date", "grade"]
    truth = json.loads((data_dir / "truth.json").read_text())
    assert truth["true_ultimate_rates"]["dresses"] == 0.36
    assert truth["dresses_size_guide_fix"]["from_ship_week"] == 84
