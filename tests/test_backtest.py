"""Backtest: methods are scored by re-running the SQL as of earlier weeks."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from returnlag import backtest as bt
from returnlag import config, report
from returnlag import warehouse as wh
from returnlag.cli import app
from returnlag.generate import generate, write_dataset


def _mae(con, method, where):
    return con.execute(
        f"SELECT avg(abs_error_pp) FROM backtest_scores WHERE method = ? AND {where}",
        [method],
    ).fetchone()[0]


def test_backtest_covers_every_as_of_week_method_and_age(backtest_con):
    rows = backtest_con.execute("SELECT DISTINCT as_of FROM backtest_scores ORDER BY 1").fetchall()
    as_of = [r[0] for r in rows]
    assert as_of == list(range(40, 89, 4))
    methods = {
        r[0] for r in backtest_con.execute("SELECT DISTINCT method FROM backtest_scores").fetchall()
    }
    assert methods == set(bt.METHODS)
    ages = backtest_con.execute(
        "SELECT min(age_weeks), max(age_weeks) FROM backtest_scores"
    ).fetchone()
    assert ages == (0, config.BACKTEST_MAX_AGE)
    n = backtest_con.execute("SELECT count(*) FROM backtest_scores").fetchone()[0]
    assert n == 13 * 6 * 9 * 4


def test_backtest_leaves_the_database_built_as_of_the_final_week(backtest_con):
    assert wh.last_built_week(backtest_con) == 104
    tables = {r[0] for r in backtest_con.execute("SHOW TABLES").fetchall()}
    assert "bt_estimates" not in tables


def test_scores_are_against_the_developed_rate(backtest_con):
    row = backtest_con.execute(
        """
        SELECT s.actual_rate, u.observed_rate
        FROM backtest_scores AS s
        JOIN fct_ultimates AS u USING (ship_week, category)
        WHERE s.method = 'naive' AND s.as_of = 88 AND s.age_weeks = 0 AND s.category = 'tops'
        """
    ).fetchone()
    assert row[0] == row[1]  # age >= 12 in the final build: the developed rate


def test_chain_ladder_error_is_at_most_half_the_naive_error_for_ages_2_to_8(backtest_con):
    where = "age_weeks BETWEEN 2 AND 8"
    assert _mae(backtest_con, "chain_ladder", where) <= 0.5 * _mae(backtest_con, "naive", where)
    for band in ("2-4", "5-8"):
        where = f"age_band = '{band}'"
        assert _mae(backtest_con, "chain_ladder", where) <= 0.5 * _mae(backtest_con, "naive", where)


def test_bornhuetter_ferguson_beats_chain_ladder_for_the_youngest_cohorts(backtest_con):
    where = "age_weeks BETWEEN 0 AND 1"
    bf = _mae(backtest_con, "bornhuetter_ferguson", where)
    cl = _mae(backtest_con, "chain_ladder", where)
    assert bf < cl
    # Chain-ladder multiplies a handful of early returns by a very large factor.
    assert cl > 2 * bf


def test_naive_error_shrinks_as_cohorts_age(backtest_con):
    errors = [
        _mae(backtest_con, "naive", f"age_weeks = {a}") for a in range(config.BACKTEST_MAX_AGE + 1)
    ]
    assert errors == sorted(errors, reverse=True)


def test_segmented_factors_beat_pooled_factors_in_the_second_holiday_season(backtest_con):
    where = "segment = 'holiday' AND ship_week BETWEEN 72 AND 78 AND age_weeks BETWEEN 1 AND 6"
    segmented = _mae(backtest_con, "chain_ladder", where)
    pooled = _mae(backtest_con, "chain_ladder_pooled", where)
    assert segmented < pooled


def test_mae_by_band_has_the_three_age_bands_and_naive_error_falls_with_age(backtest_con):
    mae = bt.mae_by_band(backtest_con)
    assert set(b for _, b in mae) == {"0-1", "2-4", "5-8"}
    assert mae[("naive", "0-1")] > mae[("naive", "5-8")]


def test_backtest_estimates_never_use_later_data(backtest_con, make_con):
    # Re-derive one estimate on a fresh warehouse built as of its week (the shared session
    # warehouse is left untouched) and compare with the stored score.
    stored = backtest_con.execute(
        "SELECT estimate FROM backtest_scores WHERE as_of = 60 AND category = 'denim' "
        "AND ship_week = 58 AND method = 'chain_ladder'"
    ).fetchone()[0]
    rebuilt = (
        make_con(60)
        .execute(
            "SELECT chain_ladder_rate FROM fct_ultimates "
            "WHERE category = 'denim' AND ship_week = 58"
        )
        .fetchone()[0]
    )
    assert stored == rebuilt


@pytest.fixture(scope="module")
def short_con(tmp_path_factory):
    """A warehouse over a 60-week dataset, after a backtest."""
    path = tmp_path_factory.mktemp("short")
    write_dataset(generate(seed=7, weeks=60), path)
    con = wh.connect()
    wh.load_raw(con, path)
    bt.run_backtest(con)
    yield con
    con.close()


def test_backtest_derives_its_final_week_from_the_data(short_con):
    assert short_con.execute("SELECT final_week FROM backtest_meta").fetchone() == (60,)
    as_of = [
        r[0] for r in short_con.execute("SELECT DISTINCT as_of FROM backtest_scores").fetchall()
    ]
    assert sorted(as_of) == [40, 44, 48, 52, 56]  # as-of 60 has no scorable cohort
    assert wh.last_built_week(short_con) == 60
    # Only cohorts that reach development week 12 by week 60 can be scored.
    assert short_con.execute("SELECT max(ship_week) FROM backtest_scores").fetchone()[0] == 48


def test_report_on_a_shorter_dataset_names_its_own_final_week(short_con):
    text = report.build_report(short_con)
    assert "reached by week 60" in text
    assert "week 104" not in text
    assert "aged 5-8 wk" in text
    assert "No holiday-season cohorts were scored" in text


def test_a_dataset_too_short_to_score_fails_with_a_clear_message(tmp_path):
    write_dataset(generate(seed=7, weeks=20), tmp_path)
    con = wh.connect()
    wh.load_raw(con, tmp_path)
    with pytest.raises(bt.BacktestError, match="needs at least 44"):
        bt.run_backtest(con)
    con.close()


def test_cli_backtest_on_the_sample_exits_with_the_message():
    sample = Path(__file__).resolve().parents[1] / "sample"
    result = CliRunner().invoke(app, ["backtest", "--data", str(sample), "--db", ":memory:"])
    assert result.exit_code == 1
    assert "8 ship weeks" in result.output
