"""Seeded synthetic generator for an apparel retailer's shipments and returns.

Properties the analysis has to recover:

* 104 weekly ship cohorts from 2024-07-01, six categories, about 150,000 units shipped.
* True ultimate return rates per category (dresses 36 %, denim 24 %, ... accessories 6 %).
* Return lag is a two-part mixture of discretised gamma distributions per category: most
  customers send items back quickly, a minority wait for the end of the 60-day window. About
  3 % of returns land after day 60 (accepted late), none after day 90. Holiday-season cohorts
  have their lags stretched by 1.8.
* Injected events: a dresses size-guide fix from ship week 84 (36 % to 29 %); a summer
  promotion in weeks 52-55 that doubles volume at unchanged rates; scanner clock errors that
  date a few returns before the shipment they belong to.

Each ship week has its own random stream, ``default_rng([seed, week])``, so a shorter run is a
prefix of a longer one.
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

import numpy as np

from returnlag.config import (
    HOLIDAY_ISO_FIRST,
    HOLIDAY_ISO_LAST,
    MAX_LAG_DAYS,
    N_WEEKS,
    WEEK1_START,
    week_start,
)

SLOW_SHAPE = 16.0
SLOW_SCALE = 2.75
FAST_SHAPE = 3.0
MIN_LAG_DAYS = 2
HOLIDAY_LAG_STRETCH = 1.8

DOW_WEIGHTS = np.array([1.15, 1.10, 1.00, 1.00, 1.05, 0.35, 0.35])
DOW_WEIGHTS = DOW_WEIGHTS / DOW_WEIGHTS.sum()

PROMO_WEEKS = (52, 53, 54, 55)
PROMO_MULTIPLIER = 2.0
DRESSES_FIX_WEEK = 84
DRESSES_RATE_AFTER_FIX = 0.29
BAD_SCANS_FULL_RUN = 37

GRADES = ("A", "B", "C")


@dataclass(frozen=True)
class CategorySpec:
    """Generator parameters for one category."""

    weekly_units: float
    true_rate: float
    fast_scale: float
    slow_weight: float
    grade_mix: tuple[float, float, float]
    holiday_volume: float = 1.1


CATEGORIES: dict[str, CategorySpec] = {
    "dresses": CategorySpec(380, 0.36, 2.75, 0.44, (0.55, 0.33, 0.12)),
    "denim": CategorySpec(262, 0.24, 2.6, 0.40, (0.62, 0.28, 0.10)),
    "footwear": CategorySpec(215, 0.22, 2.3, 0.32, (0.70, 0.22, 0.08)),
    "tops": CategorySpec(262, 0.16, 2.4, 0.38, (0.60, 0.30, 0.10)),
    "outerwear": CategorySpec(118, 0.14, 3.9, 0.41, (0.66, 0.26, 0.08), holiday_volume=1.5),
    "accessories": CategorySpec(100, 0.06, 2.3, 0.35, (0.78, 0.17, 0.05), holiday_volume=1.6),
}


@dataclass
class Dataset:
    """Shipments and returns as parallel numpy arrays, plus the injected truth."""

    shipment_id: np.ndarray
    ship_day: np.ndarray  # days since WEEK1_START
    category: np.ndarray
    units: np.ndarray
    return_id: np.ndarray
    return_shipment_id: np.ndarray
    return_day: np.ndarray
    grade: np.ndarray
    truth: dict

    @property
    def n_shipped(self) -> int:
        return int(self.units.sum())

    @property
    def n_returns(self) -> int:
        return int(self.return_id.size)


def is_holiday_week(week: int) -> bool:
    iso_week = week_start(week).isocalendar()[1]
    return HOLIDAY_ISO_FIRST <= iso_week <= HOLIDAY_ISO_LAST


def true_rate(category: str, week: int) -> float:
    """True ultimate return rate of a cohort."""
    if category == "dresses" and week >= DRESSES_FIX_WEEK:
        return DRESSES_RATE_AFTER_FIX
    return CATEGORIES[category].true_rate


def draw_lags(
    rng: np.random.Generator, spec: CategorySpec, stretch: float, caps: np.ndarray
) -> np.ndarray:
    """Return lags in days, one per element of ``caps`` (each lag <= its cap).

    The cap is ``MAX_LAG_DAYS - weekday`` so a return never lands more than 12 calendar weeks
    after the ship week; draws above the cap are redrawn.
    """
    lags = np.zeros(caps.size, dtype=np.int64)
    todo = np.arange(caps.size)
    while todo.size:
        slow = rng.random(todo.size) < spec.slow_weight
        fast_draw = rng.gamma(FAST_SHAPE, spec.fast_scale, todo.size)
        slow_draw = rng.gamma(SLOW_SHAPE, SLOW_SCALE, todo.size)
        days = np.where(slow, slow_draw, fast_draw) * stretch
        cand = np.maximum(np.ceil(days), MIN_LAG_DAYS).astype(np.int64)
        ok = cand <= caps[todo]
        lags[todo[ok]] = cand[ok]
        todo = todo[~ok]
    return lags


def generate(seed: int = 7, weeks: int = N_WEEKS) -> Dataset:
    """Generate shipments and returns for ``weeks`` ship weeks, cut off at the end of the last."""
    ship_ids: list[np.ndarray] = []
    ship_days: list[np.ndarray] = []
    ship_cats: list[np.ndarray] = []
    ship_units: list[np.ndarray] = []
    ret_ship_ids: list[np.ndarray] = []
    ret_days: list[np.ndarray] = []
    ret_grades: list[np.ndarray] = []
    next_id = 1

    for week in range(1, weeks + 1):
        rng = np.random.default_rng([seed, week])
        holiday = is_holiday_week(week)
        for name, spec in CATEGORIES.items():
            volume = spec.weekly_units
            if week in PROMO_WEEKS:
                volume *= PROMO_MULTIPLIER
            if holiday:
                volume *= spec.holiday_volume
            units = rng.poisson(volume * DOW_WEIGHTS)
            dows = np.flatnonzero(units > 0)
            n_batches = dows.size
            ids = np.arange(next_id, next_id + n_batches)
            next_id += n_batches
            batch_units = units[dows]
            batch_days = (week - 1) * 7 + dows
            ship_ids.append(ids)
            ship_days.append(batch_days)
            ship_cats.append(np.full(n_batches, name))
            ship_units.append(batch_units)

            returned = rng.binomial(batch_units, true_rate(name, week))
            total = int(returned.sum())
            if total == 0:
                continue
            owner = np.repeat(np.arange(n_batches), returned)
            caps = MAX_LAG_DAYS - dows[owner]
            stretch = HOLIDAY_LAG_STRETCH if holiday else 1.0
            lags = draw_lags(rng, spec, stretch, caps)
            ret_ship_ids.append(ids[owner])
            ret_days.append(batch_days[owner] + lags)
            ret_grades.append(rng.choice(np.array(GRADES), size=total, p=spec.grade_mix))

    shipment_id = np.concatenate(ship_ids)
    ship_day = np.concatenate(ship_days)
    category = np.concatenate(ship_cats)
    units_arr = np.concatenate(ship_units)
    r_ship = np.concatenate(ret_ship_ids)
    r_day = np.concatenate(ret_days)
    r_grade = np.concatenate(ret_grades)

    # Data cut-off: nothing dated after the last day of the last ship week exists yet.
    keep = r_day <= weeks * 7 - 1
    r_ship, r_day, r_grade = r_ship[keep], r_day[keep], r_grade[keep]

    # Scanner clock errors: a few returns carry a date before their shipment.
    n_bad = round(BAD_SCANS_FULL_RUN * weeks / N_WEEKS)
    day_of_shipment = dict(zip(shipment_id.tolist(), ship_day.tolist(), strict=True))
    shipped_on = np.array([day_of_shipment[s] for s in r_ship.tolist()])
    bad_rng = np.random.default_rng([seed, 0])
    candidates = np.flatnonzero(shipped_on >= 7)
    bad = bad_rng.choice(candidates, size=n_bad, replace=False)
    r_day[bad] = shipped_on[bad] - bad_rng.integers(1, 6, size=n_bad)

    order = np.lexsort((r_ship, r_day))
    r_ship, r_day, r_grade = r_ship[order], r_day[order], r_grade[order]
    return_id = np.arange(1, r_ship.size + 1)
    bad_ids = np.sort(return_id[np.isin(order, bad)]).tolist()

    truth = {
        "seed": seed,
        "weeks": weeks,
        "week1_start": WEEK1_START.isoformat(),
        "true_ultimate_rates": {k: v.true_rate for k, v in CATEGORIES.items()},
        "dresses_size_guide_fix": {
            "from_ship_week": DRESSES_FIX_WEEK,
            "rate_before": CATEGORIES["dresses"].true_rate,
            "rate_after": DRESSES_RATE_AFTER_FIX,
        },
        "promotion": {"weeks": list(PROMO_WEEKS), "volume_multiplier": PROMO_MULTIPLIER},
        "holiday_lag_stretch": HOLIDAY_LAG_STRETCH,
        "bad_scan_return_ids": bad_ids,
    }
    return Dataset(
        shipment_id=shipment_id,
        ship_day=ship_day,
        category=category,
        units=units_arr,
        return_id=return_id,
        return_shipment_id=r_ship,
        return_day=r_day,
        grade=r_grade,
        truth=truth,
    )


def _iso(days: int) -> str:
    return (WEEK1_START + timedelta(days=int(days))).isoformat()


def write_dataset(data: Dataset, out_dir: str | Path) -> None:
    """Write ``shipments.csv``, ``returns.csv`` and ``truth.json`` into ``out_dir``."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    with open(out / "shipments.csv", "w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["shipment_id", "ship_date", "category", "units"])
        for sid, day, cat, units in zip(
            data.shipment_id.tolist(),
            data.ship_day.tolist(),
            data.category.tolist(),
            data.units.tolist(),
            strict=True,
        ):
            writer.writerow([sid, _iso(day), cat, units])
    with open(out / "returns.csv", "w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["return_id", "shipment_id", "return_date", "grade"])
        for rid, sid, day, grade in zip(
            data.return_id.tolist(),
            data.return_shipment_id.tolist(),
            data.return_day.tolist(),
            data.grade.tolist(),
            strict=True,
        ):
            writer.writerow([rid, sid, _iso(day), grade])
    with open(out / "truth.json", "w") as fh:
        json.dump(data.truth, fh, indent=2, sort_keys=True)
        fh.write("\n")
