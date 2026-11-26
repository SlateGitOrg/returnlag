"""Shared fixtures: one generated dataset per session, cheap in-memory warehouses on top of it."""

from __future__ import annotations

import pytest

from returnlag import backtest as bt
from returnlag import warehouse as wh
from returnlag.generate import generate, write_dataset

SEED = 7


@pytest.fixture(scope="session")
def dataset():
    return generate(seed=SEED)


@pytest.fixture(scope="session")
def data_dir(dataset, tmp_path_factory):
    path = tmp_path_factory.mktemp("data")
    write_dataset(dataset, path)
    return path


@pytest.fixture
def make_con(data_dir):
    """Factory: an in-memory warehouse with the raw tables loaded, built as of a week."""
    opened = []

    def factory(as_of: int | None = None):
        con = wh.connect()
        wh.load_raw(con, data_dir)
        if as_of is not None:
            wh.build(con, as_of)
        opened.append(con)
        return con

    yield factory
    for con in opened:
        con.close()


@pytest.fixture(scope="session")
def backtest_con(data_dir):
    """A warehouse after a full backtest (left built as of week 104)."""
    con = wh.connect()
    wh.load_raw(con, data_dir)
    wh.build(con, 104)
    bt.run_backtest(con)
    yield con
    con.close()


@pytest.fixture
def fixture_con():
    """An empty warehouse with the raw tables created, for hand-built fixtures."""
    con = wh.connect()
    con.execute(
        "CREATE TABLE raw_shipments (shipment_id INTEGER, ship_date DATE, "
        "category VARCHAR, units INTEGER)"
    )
    con.execute(
        "CREATE TABLE raw_returns (return_id INTEGER, shipment_id INTEGER, "
        "return_date DATE, grade VARCHAR)"
    )
    yield con
    con.close()


def load_triangle_fixture(con, shipped, cumulative, category="dresses"):
    """Insert cohorts that ship in weeks 1..n with the given cumulative returns per cohort.

    ``shipped`` is units per cohort, ``cumulative`` a list of cumulative-return lists (cohort k
    ships in week k+1 and has ``len(cumulative[k])`` observed development weeks). Returns are
    dated on the Monday of the week they arrive in.
    """
    return_id = 1
    for k, cum in enumerate(cumulative):
        shipment_id = k + 1
        con.execute(
            "INSERT INTO raw_shipments VALUES (?, DATE '2024-07-01' + ?, ?, ?)",
            [shipment_id, 7 * k, category, shipped],
        )
        previous = 0
        for dev, total in enumerate(cum):
            for _ in range(total - previous):
                con.execute(
                    "INSERT INTO raw_returns VALUES (?, ?, DATE '2024-07-01' + ?, 'A')",
                    [return_id, shipment_id, 7 * (k + dev)],
                )
                return_id += 1
            previous = total
