from datetime import datetime

import numpy as np
import pandas as pd
import pytest

from actionzz import maintenance, strategies
from actionzz.config import Config

from .conftest import ROME

DAYS = 400


def frame(closes, end="2026-09-25"):
    idx = pd.bdate_range(end=end, periods=len(closes))
    c = np.asarray(closes, dtype=float)
    return pd.DataFrame({"Open": c, "High": c, "Low": c, "Close": c, "Volume": 1e6, "Dividends": 0.0}, index=idx)


def flat_frames(n=12, days=DAYS):
    return {f"T{i:02d}.DE": frame(np.full(days, 100.0)) for i in range(n)}


def test_dip_grid_counts_a_rebound():
    frames = flat_frames()
    c = np.full(DAYS, 100.0)
    c[300:] = 94.0  # −6% in chiusura
    c[305:] = 104.0  # +10,6% dopo 5 sedute
    frames["A.MI"] = frame(c)
    m = strategies.matrices(frames)
    idx = (1 + m["Close"].pct_change().mean(axis=1).fillna(0)).cumprod().to_numpy()
    grid = strategies.dip_grid(m, idx)
    assert grid["per_dip"][5]["signals"] == 1 and grid["per_dip"][5]["it_share"] == 1.0
    # meno di 20 operazioni: la combinazione non viene pubblicata (troppo poche per una statistica)
    assert not [x for x in grid["combos"] if x["dip"] == 5]


def test_simulate_exits_target_stop_timeout():
    closes = np.array([
        [1.02, 1.11, 1.20],   # obiettivo +10% al secondo giorno
        [0.97, 0.89, 1.30],   # stop −10% al secondo giorno
        [1.01, 1.02, 1.03],   # esce a tempo
    ])
    paths = {"Close": closes}
    market = np.full((3, 3), 1.0)
    r, days, _, outcome = strategies.simulate_exits(paths, market, target=10, stop=10, hold=3)
    assert list(outcome) == [1, -1, 0]
    assert list(days) == [2, 2, 3]
    assert r == pytest.approx([11, -11, 3])


def test_buy_hold_trades_once_and_etf_halloween():
    rng = np.random.default_rng(1)
    frames = {f"T{i:02d}.PA": frame(100 * np.exp(np.cumsum(rng.normal(0.0005, 0.01, DAYS)))) for i in range(10)}
    m = strategies.matrices(frames)
    bh = strategies.weights_strategy(m, lambda i: np.arange(10) if i == strategies.WARMUP else strategies.KEEP, "M", "bh")
    assert sum(y["orders"] for y in bh["yearly"]) == 10  # un acquisto per titolo, poi niente
    assert bh["yearly"][0]["ftt"] > 0  # tassa francese sugli acquisti
    month = m["Close"].index.month
    hw = strategies.index_strategy(m, lambda i: month[i] in (11, 12, 1, 2, 3, 4), "halloween")
    assert 1 <= sum(y["orders"] for y in hw["yearly"]) <= 4
    assert all(y["ftt"] == 0 for y in hw["yearly"])  # ETF: niente Tobin tax


def test_build_on_random_data_has_all_blocks():
    rng = np.random.default_rng(2)
    frames = {f"T{i:02d}.DE": frame(100 * np.exp(np.cumsum(rng.normal(0, 0.03, DAYS)))) for i in range(30)}
    out = strategies.build(frames)
    assert {"buy_hold", "momentum", "low_vol", "dip_5_10", "rsi2", "etf_hold", "halloween"} <= set(out["strategies"])
    assert out["dip"]["combos"] and len(out["dip"]["combos"][0]["q"]) == 21
    assert out["lab"]["diversification"][0]["k"] == 1
    for s in out["strategies"].values():
        assert s["curve"]["v"] and all(0 <= y["invested"] <= 1.0001 for y in s["yearly"])


def test_maintenance_skips_during_market_and_refreshes_old_data(store, monkeypatch):
    calls = []
    monkeypatch.setattr("actionzz.universe.build_universe", lambda cfg, st: calls.append("u"))
    monkeypatch.setattr("actionzz.backtest.run_backtest", lambda cfg, st: calls.append("b"))
    monkeypatch.setattr("actionzz.strategies.run_strategies", lambda cfg, st: calls.append("s"))
    cfg = Config()
    assert maintenance.run_maintenance(cfg, store, datetime(2026, 9, 29, 11, 0, tzinfo=ROME)) == []
    store.write("universe.json", {"generated": datetime.now().astimezone().isoformat()})
    store.write("backtest.json", {"generated": datetime.now().astimezone().isoformat()})
    done = maintenance.run_maintenance(cfg, store, datetime(2026, 9, 29, 21, 0, tzinfo=ROME))
    assert done == ["strategie"] and calls == ["s"]
