"""Backtest: re-run the same SQL as of earlier weeks and score each method's ultimates.

For each as-of week the whole model is rebuilt, so the factors, priors and ultimates only see
data dated on or before that week. Cohorts aged 0..8 weeks at that point are scored against
the rate they actually reached (all development weeks observed in the final build).
"""

from __future__ import annotations

import duckdb

from returnlag import config
from returnlag import warehouse as wh

METHODS = ("naive", "chain_ladder", "bornhuetter_ferguson", "chain_ladder_pooled")


class BacktestError(RuntimeError):
    """Raised when the data is too short to score any cohort."""


def minimum_weeks() -> int:
    """Shortest dataset (in ship weeks) that scores at least one cohort at the first as-of week.

    The youngest scored cohort at the first as-of week must itself reach development week
    ``MAX_DEV`` by the final week.
    """
    return min(config.BACKTEST_AS_OF) - config.BACKTEST_MAX_AGE + config.MAX_DEV


def run_backtest(
    con: duckdb.DuckDBPyConnection,
    as_of_weeks: tuple[int, ...] = config.BACKTEST_AS_OF,
    final_week: int | None = None,
) -> int:
    """Fill ``backtest_scores`` in ``con`` and return its row count.

    ``final_week`` is the last ship week in the data unless given; as-of weeks beyond it are
    skipped, and :class:`BacktestError` is raised if nothing can be scored.

    The model tables are left as they were found: if a build existed before, it is rebuilt as
    of that week at the end.
    """
    if final_week is None:
        final_week = wh.last_data_week(con)
    as_of_weeks = tuple(w for w in as_of_weeks if w <= final_week)
    if not as_of_weeks or final_week < minimum_weeks():
        raise BacktestError(
            f"the data covers {final_week} ship weeks; the backtest needs at least "
            f"{minimum_weeks()} (as-of weeks start at {min(config.BACKTEST_AS_OF)})"
        )
    previous = wh.last_built_week(con)
    wh.build(con, final_week)
    con.execute(
        """
        CREATE OR REPLACE TABLE bt_actuals AS
        SELECT ship_week, category, observed_rate AS actual_rate
        FROM fct_ultimates
        WHERE age_weeks >= getvariable('max_dev')
        """
    )
    con.execute(
        """
        CREATE OR REPLACE TABLE bt_estimates (
            as_of INTEGER, ship_week INTEGER, category VARCHAR, segment VARCHAR,
            age_weeks INTEGER, method VARCHAR, estimate DOUBLE
        )
        """
    )
    collect = (wh.sql_dir() / "backtest" / "collect.sql").read_text()
    for week in as_of_weeks:
        wh.build(con, week)
        con.execute(collect)
    wh.build(con, previous if previous is not None else final_week)
    con.execute((wh.sql_dir() / "backtest" / "scores.sql").read_text())
    con.execute("DROP TABLE bt_estimates")
    con.execute(
        "CREATE OR REPLACE TABLE backtest_meta AS SELECT ?::INTEGER AS final_week", [final_week]
    )
    return con.execute("SELECT count(*) FROM backtest_scores").fetchone()[0]


def mae_by_band(con: duckdb.DuckDBPyConnection) -> dict[tuple[str, str], float]:
    """MAE in percentage points keyed by (method, age band)."""
    rows = con.execute(
        """
        SELECT method, age_band, avg(abs_error_pp)
        FROM backtest_scores
        GROUP BY method, age_band
        """
    ).fetchall()
    return {(m, b): v for m, b, v in rows}
