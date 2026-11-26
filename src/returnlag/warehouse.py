"""A thin runner: connect, load raw CSVs, set variables, execute ordered SQL files.

All analytical logic lives in the ``sql/`` files. Python only decides which as-of week to set,
runs the files in filename order (each one ``CREATE OR REPLACE``s its tables) and runs the
data-quality queries under ``sql/tests/``.
"""

from __future__ import annotations

from pathlib import Path

import duckdb

from returnlag import config

RAW_SHIPMENTS_COLUMNS = (
    "{'shipment_id': 'INTEGER', 'ship_date': 'DATE', 'category': 'VARCHAR', 'units': 'INTEGER'}"
)
RAW_RETURNS_COLUMNS = (
    "{'return_id': 'INTEGER', 'shipment_id': 'INTEGER', 'return_date': 'DATE', 'grade': 'VARCHAR'}"
)

#: Model tables rebuilt for every as-of week, in dependency order of the SQL files.
MODEL_TABLES = (
    "stg_shipments",
    "stg_returns",
    "dq_rejects",
    "int_triangle",
    "int_factors",
    "int_cdf",
    "int_factors_pooled",
    "int_cdf_pooled",
    "int_prior",
    "fct_ultimates",
    "fct_ultimates_pooled",
    "fct_inbound_forecast",
    "mart_disposition",
    "mart_net_return_cost",
)


def sql_dir() -> Path:
    """Locate ``sql/``: bundled inside an installed package, or at the repository root."""
    package_dir = Path(__file__).resolve().parent
    for candidate in (package_dir / "sql", package_dir.parents[1] / "sql"):
        if candidate.is_dir():
            return candidate
    raise FileNotFoundError("sql directory not found")


def model_files() -> list[Path]:
    """The model SQL files in execution order (numeric filename prefix)."""
    return sorted(sql_dir().glob("[0-9][0-9]_*.sql"))


def check_files() -> list[Path]:
    return sorted((sql_dir() / "tests").glob("*.sql"))


def connect(path: str | Path | None = None) -> duckdb.DuckDBPyConnection:
    """Open a DuckDB database (in memory when ``path`` is None)."""
    if path is None:
        return duckdb.connect()
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    return duckdb.connect(str(path))


def load_raw(con: duckdb.DuckDBPyConnection, data_dir: str | Path) -> None:
    """Load ``shipments.csv`` and ``returns.csv`` from ``data_dir`` into raw tables."""
    data = Path(data_dir)
    con.execute(
        f"CREATE OR REPLACE TABLE raw_shipments AS "
        f"SELECT * FROM read_csv(?, header = true, columns = {RAW_SHIPMENTS_COLUMNS})",
        [str(data / "shipments.csv")],
    )
    con.execute(
        f"CREATE OR REPLACE TABLE raw_returns AS "
        f"SELECT * FROM read_csv(?, header = true, columns = {RAW_RETURNS_COLUMNS})",
        [str(data / "returns.csv")],
    )


def load_reference(con: duckdb.DuckDBPyConnection) -> None:
    """Create the assumption tables (``ref_grade``, ``ref_category_economics``) from config."""
    con.execute(
        "CREATE OR REPLACE TABLE ref_grade "
        "(grade VARCHAR, disposition VARCHAR, recovery_pct DOUBLE)"
    )
    con.executemany(
        "INSERT INTO ref_grade VALUES (?, ?, ?)",
        [(g, d, r) for g, (d, r) in config.GRADE_RECOVERY.items()],
    )
    con.execute(
        "CREATE OR REPLACE TABLE ref_category_economics "
        "(category VARCHAR, unit_price DOUBLE, handling_cost DOUBLE)"
    )
    con.executemany(
        "INSERT INTO ref_category_economics VALUES (?, ?, ?)",
        [(c, p, h) for c, (p, h) in config.CATEGORY_ECONOMICS.items()],
    )


def last_data_week(con: duckdb.DuckDBPyConnection) -> int:
    """The last ship week present in ``raw_shipments`` (the data's own horizon)."""
    row = con.execute(
        "SELECT max((ship_date - CAST(? AS DATE)) // 7 + 1) FROM raw_shipments",
        [config.WEEK1_START.isoformat()],
    ).fetchone()
    return int(row[0])


def set_parameters(con: duckdb.DuckDBPyConnection, as_of: int) -> None:
    """Set the DuckDB variables every model reads. ``asof_week`` is the as-of parameter."""
    values = {
        "asof_week": int(as_of),
        "max_dev": config.MAX_DEV,
        "holiday_iso_first": config.HOLIDAY_ISO_FIRST,
        "holiday_iso_last": config.HOLIDAY_ISO_LAST,
        "prior_cohorts": config.PRIOR_COHORTS,
        "prior_min_age": config.PRIOR_MIN_AGE,
        "backtest_max_age": config.BACKTEST_MAX_AGE,
    }
    for name, value in values.items():
        con.execute(f"SET VARIABLE {name} = {value}")
    con.execute(f"SET VARIABLE week1_start = DATE '{config.WEEK1_START.isoformat()}'")


def run_file(con: duckdb.DuckDBPyConnection, path: Path) -> None:
    con.execute(path.read_text())


def build(con: duckdb.DuckDBPyConnection, as_of: int, only: list[str] | None = None) -> list[str]:
    """Rebuild every model for ``as_of``; ``only`` restricts to files whose stem contains a name.

    Returns the names of the files that ran. Records the as-of week in ``build_meta``.
    """
    set_parameters(con, as_of)
    load_reference(con)
    ran = []
    for path in model_files():
        name = path.stem.split("_", 1)[1]
        if only is not None and name not in only:
            continue
        run_file(con, path)
        ran.append(name)
    con.execute(
        "CREATE OR REPLACE TABLE build_meta AS SELECT ?::INTEGER AS as_of_week", [int(as_of)]
    )
    return ran


def run_checks(con: duckdb.DuckDBPyConnection) -> dict[str, list[tuple]]:
    """Run every ``sql/tests`` query; each must return zero rows. Maps test name to its rows."""
    results = {}
    for path in check_files():
        results[path.stem] = con.execute(path.read_text()).fetchall()
    return results


def last_built_week(con: duckdb.DuckDBPyConnection) -> int | None:
    tables = {row[0] for row in con.execute("SHOW TABLES").fetchall()}
    if "build_meta" not in tables:
        return None
    return con.execute("SELECT as_of_week FROM build_meta").fetchone()[0]
