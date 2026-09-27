import json
from datetime import date, datetime

import numpy as np
import pandas as pd
import pytest

from actionzz.config import Config
from actionzz.crypto import WrongPassword, decrypt_json, encrypt_json
from actionzz.monitor import Monitor
from actionzz.portfolio import (
    Holding, aggregate, build_report, load_report, new_notifications, rsi, sell_signals, verdict,
)

from .conftest import ROME, FakeTelegram, bars, make_universe, market_frames

PWD = "una password lunga"


def test_crypto_roundtrip_and_wrong_password():
    env = encrypt_json({"positions": [{"ticker": "ENEL.MI"}]}, PWD, iterations=1000)
    assert "ENEL" not in json.dumps(env)
    assert decrypt_json(env, PWD)["positions"][0]["ticker"] == "ENEL.MI"
    with pytest.raises(WrongPassword):
        decrypt_json(env, "sbagliata")


def test_aggregate_lots():
    h = aggregate([
        {"ticker": "enel.mi", "quantity": 100, "price": 6.0, "fees": 5, "date": "2024-03-01"},
        {"ticker": "ENEL.MI", "quantity": 100, "price": 8.0, "fees": 5, "date": "2023-01-10"},
        {"ticker": "ENI.MI", "quantity": 0, "price": 12},  # lotto venduto del tutto
    ])
    assert list(h) == ["ENEL.MI"]
    assert h["ENEL.MI"].avg_price == pytest.approx(7.05)
    assert h["ENEL.MI"].first_date == "2023-01-10"


def test_rsi_extremes():
    up = pd.Series(np.linspace(10, 20, 40))
    assert rsi(up) == 100.0
    assert rsi(pd.Series(np.linspace(20, 10, 40))) < 5


IND = {"rsi": 55.0, "sma50": 10.0, "sma200": 10.0, "high_52w": 20.0, "low_52w": 5.0, "max_since_buy": 10.0}


def codes(signals):
    return {s["code"] for s in signals}


def test_take_profit_and_stop_loss():
    h = Holding("A.MI", "A", quantity=10, cost=100)  # prezzo medio 10
    sig, _ = sell_signals(h, 12.6, None, {**IND, "max_since_buy": 12.6}, {}, {}, Config())
    assert "take_profit" in codes(sig)
    sig, _ = sell_signals(h, 8.4, None, IND, {}, {}, Config())
    assert "stop_loss" in codes(sig)
    assert verdict(sig, [])["code"] == "vendi"


def test_trailing_stop_protects_gains():
    h = Holding("A.MI", "A", quantity=10, cost=100)
    sig, _ = sell_signals(h, 11.0, None, {**IND, "max_since_buy": 13.0}, {}, {}, Config())
    ts = [s for s in sig if s["code"] == "trailing_stop"][0]
    assert ts["level"] == "strong"


def test_hold_reasons_reduce_score():
    h = Holding("A.MI", "A", quantity=10, cost=100)
    sig, holds = sell_signals(h, 10.5, -7.0, {**IND, "rsi": 25.0}, {"target_price": 14.0}, {}, Config())
    assert {x["code"] for x in holds} == {"oversold", "upside", "sudden_drop"}
    assert verdict(sig, holds)["code"] == "mantieni"


def test_rsi_and_target_signals():
    h = Holding("A.MI", "A", quantity=10, cost=100)
    sig, _ = sell_signals(h, 11.0, None, {**IND, "rsi": 82.0, "max_since_buy": 11.0}, {"target_price": 10.8}, {}, Config())
    assert {"rsi", "target"} <= codes(sig)
    assert verdict(sig, [])["code"] == "vendi"


def trending(start, end, n=300):
    return bars(list(np.linspace(start, end, n)))


def sample_portfolio():
    return {"positions": [
        {"id": "1", "ticker": "WIN.MI", "name": "Vincente", "quantity": 10, "price": 50, "date": "2025-06-01"},
        {"id": "2", "ticker": "LOSE.L", "name": "Perdente", "quantity": 100, "price": 200, "date": "2025-06-01"},
    ], "settings": {"take_profit_pct": 25}}


def test_build_report_totals_and_fx():
    hist = {"WIN.MI": trending(40, 70), "LOSE.L": trending(210, 150)}
    fund = {"LOSE.L": {"currency": "GBp"}}
    rates = {"EUR": 1.0, "GBP": 1.2, "GBp": 0.012}
    rep = build_report(sample_portfolio(), hist, fund, rates, Config(), date(2026, 9, 25))
    win = next(r for r in rep["holdings"] if r["ticker"] == "WIN.MI")
    lose = next(r for r in rep["holdings"] if r["ticker"] == "LOSE.L")
    assert win["pnl_pct"] == pytest.approx(40) and win["verdict"]["code"] != "mantieni"
    assert "take_profit" in codes(win["signals"])
    assert lose["value_eur"] == pytest.approx(100 * 150 * 0.012)  # pence -> euro
    assert "stop_loss" in codes(lose["signals"])
    t = rep["totals"]
    assert t["value_eur"] == pytest.approx(700 + 180)
    assert t["tax_if_sold_eur"] == pytest.approx(200 * 0.26)
    assert t["positions"] == 2


def test_notifications_once_per_signal():
    rep = build_report(sample_portfolio(), {"WIN.MI": trending(40, 70)}, {}, {"EUR": 1.0}, Config(), date(2026, 9, 25))
    assert rep["missing"] == ["LOSE.L"]
    first = new_notifications(rep)
    assert [r["ticker"] for r in first] == ["WIN.MI"]
    assert new_notifications(rep) == []


def test_monitor_portfolio_alert_and_encrypted_report(cfg, store, tmp_path):
    frames = market_frames()
    store.write("universe.json", make_universe(sorted(frames)))
    pf_path = tmp_path / "portfolio.enc.json"
    pf_path.write_text(json.dumps(encrypt_json(sample_portfolio(), PWD, iterations=1000)))
    hist = {"WIN.MI": trending(40, 70), "LOSE.L": trending(210, 150), **frames}

    def downloader(tickers, period="1mo", **kw):
        return {t: hist[t] for t in tickers if t in hist}

    tg = FakeTelegram()
    m = Monitor(cfg, store, tg, downloader=downloader, fundamentals=lambda t: {}, news=lambda t: [],
                config_path=tmp_path / "config.json", portfolio_path=pf_path, portfolio_password=PWD)
    m.run_cycle(datetime(2026, 9, 25, 11, 0, tzinfo=ROME))
    cards = [t for t in tg.sent if "segnali di vendita" in t]
    assert len(cards) == 2 and any("WIN.MI" in c for c in cards)

    # il resoconto sul branch pubblico è cifrato
    raw = (store.dir / "portfolio_report.enc.json").read_text()
    assert "WIN.MI" not in raw
    assert load_report(store, PWD)["totals"]["positions"] == 2

    # seconda esecuzione: nessun doppione; il comando /portafoglio risponde
    tg.sent.clear()
    tg.updates = [{"update_id": 1, "message": {"text": "/portafoglio", "chat": {"id": 42}}}]
    m2 = Monitor(cfg, store, tg, downloader=downloader, fundamentals=lambda t: {}, news=lambda t: [],
                 config_path=tmp_path / "config.json", portfolio_path=pf_path, portfolio_password=PWD)
    m2.run_cycle(datetime(2026, 9, 25, 11, 5, tzinfo=ROME))
    assert not [t for t in tg.sent if "segnali di vendita" in t]
    assert any("Il tuo portafoglio" in t for t in tg.sent)


def test_wrong_password_skips_portfolio(cfg, store, tmp_path):
    pf_path = tmp_path / "portfolio.enc.json"
    pf_path.write_text(json.dumps(encrypt_json(sample_portfolio(), PWD, iterations=1000)))
    m = Monitor(cfg, store, FakeTelegram(), downloader=lambda *a, **k: {}, config_path=tmp_path / "c.json",
                portfolio_path=pf_path, portfolio_password="altra")
    assert m.update_portfolio(datetime(2026, 9, 25, 11, 0, tzinfo=ROME)) is None


def telegram_monitor(cfg, store, tmp_path, hist, updates, pwd=PWD):
    tg = FakeTelegram(updates=updates)
    m = Monitor(cfg, store, tg, downloader=lambda tickers, period="1mo", **kw: {t: hist[t] for t in tickers if t in hist},
                fundamentals=lambda t: {"target_price": 9.0}, news=lambda t: [], config_path=tmp_path / "config.json",
                portfolio_path=tmp_path / "portfolio.enc.json", portfolio_password=pwd)
    return m, tg


def msg(uid, text):
    return {"update_id": uid, "message": {"text": text, "chat": {"id": 42}}}


def test_buy_sends_sell_plan_and_saves_encrypted(cfg, store, tmp_path):
    hist = {"ENEL.MI": trending(6.0, 6.6)}
    m, tg = telegram_monitor(cfg, store, tmp_path, hist, [msg(1, "/compra enel.mi 100 6,50 5")])
    m.process_commands()
    assert "Acquisto registrato" in tg.sent[0]
    plan = tg.sent[1]
    assert "Piano di vendita" in plan
    assert "Sopra 8,19" in plan  # (650 + 5) / 100 = 6,55 → +25%
    assert "Sotto 5,57" in plan  # −15%
    assert m.portfolio_changed
    raw = (tmp_path / "portfolio.enc.json").read_text()
    assert "ENEL" not in raw
    assert decrypt_json(json.loads(raw), PWD)["positions"][0]["quantity"] == 100
    # il ciclo successivo non rimanda la scheda dei segnali per lo stesso titolo
    m.update_portfolio(datetime(2026, 9, 25, 11, 0, tzinfo=ROME))
    assert not [t for t in tg.sent if "segnali di vendita" in t]


def test_sell_fifo_and_plan_commands(cfg, store, tmp_path):
    hist = {"ENEL.MI": trending(6.0, 8.0)}
    m, tg = telegram_monitor(cfg, store, tmp_path, hist, [
        msg(1, "/compra ENEL.MI 100 6"), msg(2, "/compra ENEL.MI 100 7"),
        msg(3, "/vendi ENEL.MI 150 8"), msg(4, "/piano ENEL.MI"), msg(5, "/vendi ENEL.MI 999 8"),
        msg(6, "/obiettivo 30"),
    ])
    m.process_commands()
    sale_msg = next(t for t in tg.sent if "Vendita registrata" in t)
    assert "Plusvalenza: <b>250,00 EUR</b>" in sale_msg  # 150×8 − (100×6 + 50×7)
    assert "Te ne restano 50" in sale_msg
    assert any("Piano di vendita" in t and "50 azioni a 7,00" in t for t in tg.sent)
    assert any("ne possiedi solo 50" in t for t in tg.sent)
    pf = decrypt_json(json.loads((tmp_path / "portfolio.enc.json").read_text()), PWD)
    assert pf["settings"]["take_profit_pct"] == 30 and pf["sales"][0]["realized"] == 250


def test_buy_without_password_or_bad_ticker(cfg, store, tmp_path):
    m, tg = telegram_monitor(cfg, store, tmp_path, {}, [msg(1, "/compra ENEL.MI 10 6"), msg(2, "/compra")], pwd="")
    m.process_commands()
    assert "PORTFOLIO_PASSWORD" in tg.sent[0] and "Uso: /compra" in tg.sent[1]
    m, tg = telegram_monitor(cfg, store, tmp_path, {}, [msg(10, "/compra XXX.MI 10 6")])
    m.process_commands()
    assert "Non trovo dati" in tg.sent[0]
