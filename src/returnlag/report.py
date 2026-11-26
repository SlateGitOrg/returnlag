"""Markdown tables and the report, rendered from tables already built in DuckDB."""

from __future__ import annotations

import duckdb

from returnlag import config
from returnlag import warehouse as wh

METHOD_LABELS = {
    "naive": "naive (observed rate)",
    "chain_ladder": "chain-ladder",
    "bornhuetter_ferguson": "Bornhuetter-Ferguson",
    "chain_ladder_pooled": "chain-ladder, pooled factors",
}


class MissingBuildError(RuntimeError):
    """Raised when a table the report needs has not been built yet."""


def _table(headers: list[str], rows: list[list[str]], align: str | None = None) -> str:
    align = align or "l" + "r" * (len(headers) - 1)
    rule = ["---:" if a == "r" else ":---" for a in align]
    lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join(rule) + " |"]
    lines += ["| " + " | ".join(row) + " |" for row in rows]
    return "\n".join(lines)


def _pct(value: float) -> str:
    return f"{value * 100:.1f}%"


def _require(con: duckdb.DuckDBPyConnection, *tables: str) -> None:
    present = {row[0] for row in con.execute("SHOW TABLES").fetchall()}
    missing = [t for t in tables if t not in present]
    if missing:
        raise MissingBuildError(
            f"missing {', '.join(missing)}: run `returnlag build` (and `returnlag backtest`) first"
        )


def backtest_table(con: duckdb.DuckDBPyConnection) -> str:
    """MAE in percentage points by method x age band."""
    _require(con, "backtest_scores", "backtest_meta")
    rows = con.execute(
        """
        SELECT method, age_band, avg(abs_error_pp), count(*)
        FROM backtest_scores GROUP BY ALL
        """
    ).fetchall()
    mae = {(m, b): v for m, b, v, _ in rows}
    counts = {b: n for _, b, _, n in rows}
    bands = [band for band, _, _ in config.BACKTEST_AGE_BANDS if band in counts]
    headers = ["method"] + [f"aged {b} wk" for b in bands]
    body = []
    for method, label in METHOD_LABELS.items():
        body.append([label] + [f"{mae[(method, b)]:.2f}" for b in bands])
    body.append(["cohort-category scores per method"] + [str(counts[b]) for b in bands])
    return _table(headers, body)


def holiday_weeks(con: duckdb.DuckDBPyConnection) -> tuple[int, int] | None:
    """Ship weeks of the latest holiday season that has scored cohorts, or None."""
    _require(con, "backtest_scores")
    last = con.execute(
        "SELECT max(ship_week) FROM backtest_scores WHERE segment = 'holiday'"
    ).fetchone()[0]
    if last is None:
        return None
    return last - config.HOLIDAY_SEASON_WEEKS + 1, last


def holiday_caption(con: duckdb.DuckDBPyConnection) -> str:
    weeks = holiday_weeks(con)
    if weeks is None:
        return "No holiday-season cohorts were scored in this backtest."
    return (
        f"Latest holiday season in the backtest (ship weeks {weeks[0]}-{weeks[1]}), "
        "cohorts aged 1-6 weeks."
    )


def holiday_table(con: duckdb.DuckDBPyConnection) -> str:
    """Segmented vs pooled chain-ladder for the latest scored holiday season, ages 1-6."""
    weeks = holiday_weeks(con)
    if weeks is None:
        return "No holiday-season cohorts were scored in this backtest."
    rows = con.execute(
        """
        SELECT method, avg(abs_error_pp), count(*)
        FROM backtest_scores
        WHERE segment = 'holiday' AND ship_week BETWEEN ? AND ?
            AND age_weeks BETWEEN 1 AND 6
            AND method IN ('chain_ladder', 'chain_ladder_pooled')
        GROUP BY method
        """,
        list(weeks),
    ).fetchall()
    by_method = {m: (v, n) for m, v, n in rows}
    body = [
        [label, f"{by_method[m][0]:.2f}", str(by_method[m][1])]
        for m, label in (
            ("chain_ladder", "chain-ladder, segmented factors"),
            ("chain_ladder_pooled", "chain-ladder, pooled factors"),
        )
        if m in by_method
    ]
    return _table(["method", "MAE (pp)", "scores"], body)


def cohort_table(
    con: duckdb.DuckDBPyConnection, categories: list[str] | None = None, n: int = 6
) -> str:
    """The latest ``n`` cohorts per category: observed, chain-ladder and BF ultimate rates."""
    _require(con, "fct_ultimates", "build_meta")
    as_of = wh.last_built_week(con)
    rows = con.execute(
        """
        SELECT category, ship_week, age_weeks, units_shipped, observed_rate,
               chain_ladder_rate, bf_rate
        FROM fct_ultimates
        WHERE age_weeks < ?
        ORDER BY category, ship_week
        """,
        [n],
    ).fetchall()
    body = [
        [
            cat,
            str(week),
            config.week_start(week).isoformat(),
            str(age),
            str(units),
            _pct(obs),
            _pct(cl),
            _pct(bf),
        ]
        for cat, week, age, units, obs, cl, bf in rows
        if categories is None or cat in categories
    ]
    headers = ["category", "ship week", "week of", "age", "units", "observed", "chain-ladder", "BF"]
    text = _table(headers, body, "lrlrrrrr")
    return f"As of week {as_of}.\n\n{text}"


def inbound_table(con: duckdb.DuckDBPyConnection, weeks: int = 8) -> str:
    """Expected returns arriving in each of the next ``weeks`` weeks from shipped cohorts."""
    _require(con, "fct_inbound_forecast", "build_meta")
    as_of = wh.last_built_week(con)
    rows = con.execute(
        """
        SELECT weeks_ahead, forecast_week,
               sum(expected_returns) FILTER (method = 'chain_ladder'),
               sum(expected_returns) FILTER (method = 'bornhuetter_ferguson')
        FROM fct_inbound_forecast
        WHERE weeks_ahead <= ?
        GROUP BY ALL ORDER BY weeks_ahead
        """,
        [weeks],
    ).fetchall()
    body = [
        [str(ahead), str(week), config.week_start(week).isoformat(), f"{cl:.0f}", f"{bf:.0f}"]
        for ahead, week, cl, bf in rows
    ]
    body.append(
        ["total", "", "", f"{sum(r[2] for r in rows):.0f}", f"{sum(r[3] for r in rows):.0f}"]
    )
    headers = ["weeks ahead", "week", "week of", "chain-ladder", "BF"]
    return f"Cohorts shipped by week {as_of}, units arriving.\n\n" + _table(headers, body, "rrlrr")


def disposition_table(con: duckdb.DuckDBPyConnection) -> str:
    """Net return cost per category: refund less recovered value plus handling."""
    _require(con, "mart_net_return_cost")
    rows = con.execute(
        """
        SELECT category, returns, recovery_pct, net_cost, net_cost_per_return
        FROM mart_net_return_cost ORDER BY net_cost_per_return DESC
        """
    ).fetchall()
    body = [
        [cat, f"{n:,}", _pct(rec), f"{cost:,.0f}", f"{per:.2f}"] for cat, n, rec, cost, per in rows
    ]
    headers = ["category", "returns", "value recovered", "net cost", "net cost per return"]
    return _table(headers, body)


def build_report(
    con: duckdb.DuckDBPyConnection,
    categories: list[str] | None = None,
    n_cohorts: int = 6,
    weeks: int = 8,
) -> str:
    """The full Markdown report."""
    _require(con, "backtest_meta")
    final_week = con.execute("SELECT final_week FROM backtest_meta").fetchone()[0]
    recovery = ", ".join(
        f"{g} {disp} {share:.0%}" for g, (disp, share) in config.GRADE_RECOVERY.items()
    )
    parts = [
        "# Return rates by shipment cohort",
        "## Latest cohorts\n\nRates are returned units as a share of units shipped.\n\n"
        + cohort_table(con, categories, n_cohorts),
        "## Backtest\n\nMean absolute error in percentage points against the rate each cohort "
        f"reached by week {final_week}, with every build restricted to data dated on or before "
        "its as-of week.\n\n" + backtest_table(con),
        "### Season segmentation\n\n" + holiday_caption(con) + "\n\n" + holiday_table(con),
        f"## Inbound returns, next {weeks} weeks\n\n" + inbound_table(con, weeks),
        "## Net return cost\n\nCounts and grades come from the data. Unit prices, handling "
        "costs and the share of price recovered per grade are assumptions set in "
        f"`config.py` ({recovery}), not estimates. Net cost = refund - recovered value + "
        "handling, for returns received by the as-of week.\n\n" + disposition_table(con),
    ]
    return "\n\n".join(parts) + "\n"
