"""Command line interface, run end to end through typer's test runner."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from returnlag.cli import app

runner = CliRunner()
SAMPLE = Path(__file__).resolve().parents[1] / "sample"


def test_generate_writes_the_three_files(tmp_path):
    result = runner.invoke(app, ["generate", "--seed", "3", "--weeks", "6", "--out", str(tmp_path)])
    assert result.exit_code == 0, result.output
    assert {p.name for p in tmp_path.iterdir()} == {"shipments.csv", "returns.csv", "truth.json"}
    assert "dated before shipment" in result.output


def test_build_reports_staging_and_runs_the_checks(data_dir, tmp_path):
    db = tmp_path / "w.duckdb"
    result = runner.invoke(
        app, ["build", "--as-of", "104", "--data", str(data_dir), "--db", str(db)]
    )
    assert result.exit_code == 0, result.output
    assert "built as of week 104" in result.output
    assert "37 rejected" in result.output
    assert "queries returned zero rows" in result.output


def test_build_works_on_the_committed_sample(tmp_path):
    db = tmp_path / "s.duckdb"
    result = runner.invoke(app, ["build", "--as-of", "8", "--data", str(SAMPLE), "--db", str(db)])
    assert result.exit_code == 0, result.output
    assert "built as of week 8" in result.output


def test_inbound_prints_eight_weeks_and_a_total(data_dir, tmp_path):
    db = tmp_path / "w.duckdb"
    args = ["inbound", "--as-of", "90", "--weeks", "8", "--data", str(data_dir), "--db", str(db)]
    result = runner.invoke(app, args)
    assert result.exit_code == 0, result.output
    rows = [line for line in result.output.splitlines() if line.startswith("| ")]
    body = rows[2:]
    assert len(body) == 9 and body[-1].startswith("| total")
    assert body[0].split("|")[2].strip() == "91"


def test_report_requires_a_build_and_backtest(tmp_path):
    db = tmp_path / "empty.duckdb"
    result = runner.invoke(app, ["report", "--db", str(db), "--out", str(tmp_path / "r.md")])
    assert result.exit_code == 1
    assert "returnlag build" in result.output


def test_backtest_then_report_writes_markdown(data_dir, tmp_path):
    db = tmp_path / "w.duckdb"
    out = tmp_path / "report.md"
    built = runner.invoke(
        app, ["build", "--as-of", "104", "--data", str(data_dir), "--db", str(db)]
    )
    assert built.exit_code == 0, built.output
    backtested = runner.invoke(app, ["backtest", "--data", str(data_dir), "--db", str(db)])
    assert backtested.exit_code == 0, backtested.output
    assert "chain-ladder, pooled factors" in backtested.output
    result = runner.invoke(
        app,
        [
            "report",
            "--db",
            str(db),
            "--out",
            str(out),
            "--category",
            "dresses",
            "--category",
            "denim",
        ],
    )
    assert result.exit_code == 0, result.output
    text = out.read_text()
    for heading in (
        "## Latest cohorts",
        "## Backtest",
        "## Inbound returns, next 8 weeks",
        "## Net return cost",
    ):
        assert heading in text
    assert "| dresses | 104 |" in text and "| denim | 99 |" in text
    assert "| tops | 104 |" not in text
    assert "are assumptions set in" in text
