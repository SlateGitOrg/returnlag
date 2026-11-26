"""Command line interface: generate, build, backtest, inbound, report."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from returnlag import backtest as bt
from returnlag import config, report
from returnlag import warehouse as wh
from returnlag.generate import generate as generate_data
from returnlag.generate import write_dataset

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="Return rates by shipment cohort, completed with chain-ladder and Bornhuetter-Ferguson.",
)

DataOpt = Annotated[
    Path, typer.Option("--data", help="Directory with shipments.csv and returns.csv.")
]
DbOpt = Annotated[Path, typer.Option("--db", help="DuckDB database file.")]


@app.command()
def generate(
    seed: Annotated[int, typer.Option(help="Random seed.")] = 7,
    weeks: Annotated[int, typer.Option(help="Number of ship weeks.")] = config.N_WEEKS,
    out: Annotated[Path, typer.Option(help="Output directory.")] = Path("data"),
) -> None:
    """Write shipments.csv, returns.csv and truth.json for a seeded synthetic retailer."""
    data = generate_data(seed=seed, weeks=weeks)
    write_dataset(data, out)
    typer.echo(
        f"wrote {out}: {data.shipment_id.size} shipments, {data.n_shipped} units shipped, "
        f"{data.n_returns} returns, {len(data.truth['bad_scan_return_ids'])} dated before shipment"
    )


@app.command()
def build(
    as_of: Annotated[int, typer.Option("--as-of", help="As-of week (1-based index).")],
    data: DataOpt = Path("data"),
    db: DbOpt = Path("out/returnlag.duckdb"),
) -> None:
    """Build every model as of a week, then run the data-quality queries."""
    con = wh.connect(db)
    wh.load_raw(con, data)
    wh.build(con, as_of)
    staged = con.execute("SELECT count(*) FROM stg_returns").fetchone()[0]
    rejected = con.execute("SELECT count(*) FROM dq_rejects").fetchone()[0]
    typer.echo(f"built as of week {as_of}: {staged} returns staged, {rejected} rejected")
    failed = {name: rows for name, rows in wh.run_checks(con).items() if rows}
    for name, rows in failed.items():
        typer.echo(f"FAILED {name}: {len(rows)} rows", err=True)
    if failed:
        raise typer.Exit(code=1)
    typer.echo(f"{len(wh.check_files())} sql/tests queries returned zero rows")


@app.command()
def backtest(
    data: DataOpt = Path("data"),
    db: DbOpt = Path("out/returnlag.duckdb"),
) -> None:
    """Rebuild as of weeks 40, 44, ..., 88 and score each method against developed rates."""
    con = wh.connect(db)
    wh.load_raw(con, data)
    try:
        n = bt.run_backtest(con)
    except bt.BacktestError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(f"{n} scores over {len(config.BACKTEST_AS_OF)} as-of weeks\n")
    typer.echo("MAE in percentage points\n")
    typer.echo(report.backtest_table(con))
    typer.echo(f"\n{report.holiday_caption(con)}\n")
    typer.echo(report.holiday_table(con))


@app.command()
def inbound(
    as_of: Annotated[int, typer.Option("--as-of", help="As-of week (1-based index).")],
    weeks: Annotated[int, typer.Option(help="Weeks ahead to show.")] = 8,
    data: DataOpt = Path("data"),
    db: DbOpt = Path("out/returnlag.duckdb"),
) -> None:
    """Expected returns arriving in the coming weeks from cohorts already shipped."""
    con = wh.connect(db)
    wh.load_raw(con, data)
    wh.build(con, as_of)
    typer.echo(report.inbound_table(con, weeks))


@app.command(name="report")
def report_command(
    db: DbOpt = Path("out/returnlag.duckdb"),
    out: Annotated[Path, typer.Option(help="Markdown file to write.")] = Path("out/report.md"),
    category: Annotated[
        list[str] | None, typer.Option(help="Limit the cohort table to these categories.")
    ] = None,
    cohorts: Annotated[int, typer.Option(help="Latest cohorts per category.")] = 6,
    weeks: Annotated[int, typer.Option(help="Weeks of inbound forecast.")] = 8,
) -> None:
    """Write the Markdown report from the last build and backtest in the database."""
    con = wh.connect(db)
    try:
        text = report.build_report(con, category, cohorts, weeks)
    except report.MissingBuildError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text)
    typer.echo(f"wrote {out}")


if __name__ == "__main__":
    app()
