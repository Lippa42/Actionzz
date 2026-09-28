from datetime import datetime

import numpy as np
import pandas as pd
import pytest

from actionzz.backtest import run_frames
from actionzz.config import Config
from actionzz.data import parse_news_item, split_download
from actionzz.markets import exchange_info, is_summary_due, is_trading_window
from actionzz.messages import fmt_big, fmt_num, fmt_pct
from actionzz.telegram import split_message
from actionzz.universe import active_items, compute_metrics, select

from .conftest import ROME


def test_italian_number_format():
    assert fmt_num(1234.5) == "1.234,50"
    assert fmt_pct(-6.26) == "−6,3%"
    assert fmt_pct(1.0) == "+1,0%"
    assert fmt_big(2.1e11) == "210,0 mld"


def test_exchange_info():
    assert exchange_info("NESN.SW") == ("Svizzera", "CHF", "SIX")
    assert exchange_info("BT-A.L")[1] == "GBp"


def test_trading_window():
    cfg = Config()
    assert is_trading_window(cfg, datetime(2026, 9, 25, 9, 0, tzinfo=ROME))
    assert is_trading_window(cfg, datetime(2026, 9, 25, 17, 55, tzinfo=ROME))
    assert not is_trading_window(cfg, datetime(2026, 9, 25, 8, 55, tzinfo=ROME))
    assert not is_trading_window(cfg, datetime(2026, 9, 25, 18, 5, tzinfo=ROME))
    assert not is_trading_window(cfg, datetime(2026, 9, 27, 12, 0, tzinfo=ROME))  # domenica
    assert is_summary_due(cfg, datetime(2026, 9, 25, 18, 0, tzinfo=ROME))


def series(vol, days=1300, seed=1):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range(end="2026-09-25", periods=days)
    return pd.Series(100 * np.exp(np.cumsum(rng.normal(0, vol, days))), index=idx)


def test_universe_picks_lowest_volatility():
    metrics = {
        "CALM.MI": compute_metrics(series(0.005)),
        "MID.MI": compute_metrics(series(0.01)),
        "WILD.MI": compute_metrics(series(0.03)),
        "NEW.MI": compute_metrics(series(0.004, days=200)),  # quotata da poco
    }
    cfg = Config(universe_size=2)
    items, rejected = select(metrics, {}, cfg, today="2026-09-26")
    assert [i["ticker"] for i in items] == ["CALM.MI", "MID.MI"]
    assert rejected["storico_breve"] == 1
    assert 5 < metrics["CALM.MI"]["vol"] < 11  # 0,5% al giorno ≈ 8% annuo

    cfg = Config(universe_size=2, include=["WILD.MI"], exclude=["CALM.MI"])
    items, _ = select(metrics, {}, cfg, today="2026-09-26")
    assert {i["ticker"] for i in items} == {"MID.MI", "WILD.MI"}


def test_active_items_adds_manual_tickers():
    cfg = Config(include=["ENEL.MI"], exclude=["A.MI"])
    universe = {"items": [{"ticker": "A.MI"}, {"ticker": "B.MI"}]}
    assert [i["ticker"] for i in active_items(universe, cfg)] == ["B.MI", "ENEL.MI"]


def test_backtest_finds_drop_and_forward_return():
    idx = pd.bdate_range(end="2026-09-25", periods=120)
    close = pd.DataFrame({f"T{i}": np.full(120, 100.0) for i in range(10)}, index=idx)
    close.iloc[50:, 0] = 90.0  # T0 perde il 10% al giorno 50...
    close.iloc[75:, 0] = 99.0  # ...e recupera dopo 25 giorni
    result = run_frames(close, close.copy(), Config(drop_threshold_pct=5))
    assert result["main"]["signals"] == 1
    ev = result["events"][0]
    assert ev["ticker"] == "T0" and ev["close_pct"] == pytest.approx(-10)
    assert ev["ret5"] == pytest.approx(0) and ev["ret60"] == pytest.approx(10)
    assert result["sweep"][0]["threshold"] == 3


def test_split_download_multiindex():
    idx = pd.bdate_range(end="2026-09-25", periods=3)
    cols = pd.MultiIndex.from_product([["A.MI", "B.MI"], ["Open", "High", "Low", "Close", "Volume", "Dividends"]])
    raw = pd.DataFrame(np.ones((3, 12)), index=idx, columns=cols)
    raw[("B.MI", "Close")] = np.nan  # ticker senza dati
    out = split_download(raw, ["A.MI", "B.MI", "C.MI"])
    assert list(out) == ["A.MI"]


def test_news_formats():
    new = {"content": {"title": "Utili in calo", "provider": {"displayName": "Reuters"},
                       "canonicalUrl": {"url": "https://x"}, "pubDate": "2026-09-25T10:00:00Z"}}
    old = {"title": "Vecchio", "publisher": "AP", "link": "https://y", "providerPublishTime": 0}
    assert parse_news_item(new)["publisher"] == "Reuters"
    assert parse_news_item(old)["url"] == "https://y"


def test_split_message():
    text = "\n".join(["riga " * 50] * 100)
    parts = split_message(text, 1000)
    assert all(len(p) <= 1000 for p in parts)
    assert "".join(p.replace("\n", "") for p in parts) == text.replace("\n", "")


def test_backtest_ignores_price_glitches():
    idx = pd.bdate_range(end="2026-09-25", periods=120)
    close = pd.DataFrame({f"T{i}": np.full(120, 100.0) for i in range(10)}, index=idx)
    close.iloc[40, 1] = 0.1  # errore di Yahoo: prezzo diviso per 1000 per un giorno
    close.iloc[60:, 2] = 30.0  # scorporo: -70% "finto"
    close.iloc[30:, 3] = 93.0  # calo vero del 7%
    result = run_frames(close, close.copy(), Config(drop_threshold_pct=5))
    assert [e["ticker"] for e in result["events"]] == ["T3"]
    assert result["main"]["horizons"]["20"]["return"]["mean"] == pytest.approx(0)


def test_flat_series_rejected():
    s = series(0.01)
    s.iloc[-250:] = 50.0  # prezzo fermo per un anno
    items, rejected = select({"FLAT.AS": compute_metrics(s)}, {}, Config(), today="2026-09-26")
    assert items == [] and rejected["dati_anomali"] == 1


def test_session_status():
    from actionzz.markets import session_status

    cfg = Config()
    at = lambda d, h, m: datetime(2026, 9, d, h, m, tzinfo=ROME)  # noqa: E731
    assert session_status(cfg, at(28, 7, 30)) == "before"  # lunedì mattina
    assert session_status(cfg, at(28, 8, 55)) == "open"
    assert session_status(cfg, at(28, 18, 5)) == "open"  # c'è ancora il riepilogo delle 18
    assert session_status(cfg, at(28, 18, 20)) == "closed"
    assert session_status(cfg, at(27, 12, 0)) == "closed"  # domenica


def test_listen_processes_commands_until_deadline(cfg, store, tmp_path):
    from actionzz.monitor import Monitor

    from .conftest import FakeTelegram

    tg = FakeTelegram(updates=[{"update_id": 1, "message": {"text": "/pausa", "chat": {"id": 42}}}])
    m = Monitor(cfg, store, tg, config_path=tmp_path / "c.json")
    m.listen(2)
    assert m.cfg.paused and m.config_changed and "pausa" in tg.sent[0]
