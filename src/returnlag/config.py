"""Constants shared by the generator, the SQL runner and the backtest."""

from __future__ import annotations

from datetime import date

#: Monday of ship week 1. Every week number in the project is an index from here.
WEEK1_START = date(2024, 7, 1)
N_WEEKS = 104

#: Development weeks run 0..MAX_DEV; the tail factor after MAX_DEV is 1.0.
MAX_DEV = 12

#: ISO weeks 46-52 make the holiday season segment; the gift return window is longer.
HOLIDAY_ISO_FIRST = 46
HOLIDAY_ISO_LAST = 52

#: Bornhuetter-Ferguson prior: the most recent PRIOR_COHORTS cohorts aged >= PRIOR_MIN_AGE weeks.
PRIOR_COHORTS = 26
PRIOR_MIN_AGE = 13

#: Backtest: build as of each of these weeks, score cohorts aged 0..BACKTEST_MAX_AGE.
BACKTEST_AS_OF = tuple(range(40, 89, 4))
BACKTEST_MAX_AGE = 8
BACKTEST_AGE_BANDS = (("0-1", 0, 1), ("2-4", 2, 4), ("5-8", 5, 8))

#: Returns more than this many days after shipment never occur in the data.
MAX_LAG_DAYS = 90


def week_start(week: int) -> date:
    """Monday of the given ship week index."""
    from datetime import timedelta

    return WEEK1_START + timedelta(weeks=week - 1)


#: Width of the holiday segment in ship weeks (ISO weeks 46-52).
HOLIDAY_SEASON_WEEKS = HOLIDAY_ISO_LAST - HOLIDAY_ISO_FIRST + 1

# Disposition economics. These are assumptions of the analysis, not results derived from the
# data: the data carries only a grade per return. Change them here and rebuild.
#: Grade -> (disposition, share of the selling price recovered).
GRADE_RECOVERY = {
    "A": ("restock", 0.92),
    "B": ("outlet", 0.58),
    "C": ("liquidate", 0.12),
}
#: Category -> (unit selling price refunded on a return, handling cost per returned unit).
CATEGORY_ECONOMICS = {
    "dresses": (64.0, 8.5),
    "denim": (72.0, 8.5),
    "footwear": (95.0, 11.0),
    "tops": (34.0, 7.0),
    "outerwear": (148.0, 12.5),
    "accessories": (26.0, 6.0),
}
