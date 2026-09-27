import json
from datetime import datetime

import pytest

from actionzz.config import Config
from actionzz.crypto import decrypt_json
from actionzz.monitor import Monitor
from actionzz.simulator import (
    broker_settings, buy_quote, commission, default_settings, load_brokers, market_of, new_sim, normalize, process,
)

from .conftest import ROME, FakeTelegram, bars, make_universe

NOW = datetime(2026, 9, 25, 11, 0, tzinfo=ROME)  # venerdì, borsa aperta
RATES = {"EUR": 1.0, "GBp": 0.0115, "GBP": 1.15, "USD": 0.9}


def sim_with(orders, budget=10_000, broker="fineco_trading"):
    sim = new_sim(budget, "2026-09-01")
    sim["settings"] = broker_settings(broker)
    for i, o in enumerate(orders):
        sim["orders"].append({"id": f"o{i}", "created": f"2026-09-25T10:{i:02d}:00+02:00", "validity": "day",
                              "valid_until": "2026-09-25", **o})
    return sim


def run(sim, quotes, state=None, now=NOW):
    return process(sim, state, quotes, RATES, {}, Config(), now)


def test_broker_catalog_and_markets():
    ids = {b["id"] for b in load_brokers()}
    assert {"trade_republic", "degiro", "fineco_trading", "directa_fixed", "ibkr_tiered"} <= ids
    assert market_of("ENEL.MI") == "it" and market_of("SAP.DE") == "eu" and market_of("AAPL") == "us"
    fin = broker_settings("fineco_trading")
    assert commission(500, fin, "it") == 2.95 and commission(5_000, fin, "it") == 9.5 and commission(50_000, fin, "it") == 19
    assert commission(10_000, broker_settings("degiro"), "us") == 2.0
    assert commission(3_000, broker_settings("directa_fixed"), "eu") == 9.0
    assert default_settings()["broker"] == "fineco_trading"


def test_buy_costs_italy_with_tobin_tax():
    q = buy_quote("ENEL.MI", 100, 10.0, 1.0, broker_settings("fineco_trading"))
    assert q["gross"] == pytest.approx(1000.5)  # +0,05% di scostamento
    assert q["commission"] == 2.95
    assert q["transaction_tax"] == pytest.approx(2.0)  # Tobin tax 0,2% dal 2026
    assert q["fx_cost"] == 0


def test_buy_uk_stamp_duty_and_fx():
    q = buy_quote("ULVR.L", 10, 4000.0, 0.0115, broker_settings("degiro"))  # pence
    assert q["gross"] == pytest.approx(10 * 4002 * 0.0115)
    assert q["transaction_tax"] == pytest.approx(round(q["gross"] * 0.005, 2))
    assert q["fx_cost"] == pytest.approx(round(q["gross"] * 0.0025, 2))
    assert q["commission"] == 2.0


def test_buy_then_sell_with_capital_gains_tax():
    quotes = {"ENEL.MI": bars([9.8, 10.0])}
    sim = sim_with([{"ticker": "ENEL.MI", "side": "buy", "quantity": 100}])
    state, events = run(sim, quotes)
    assert events[0]["type"] == "buy"
    cash_after_buy = state["cash"]
    assert cash_after_buy == pytest.approx(10_000 - 1000.5 - 2.95 - 2.0)
    pos = state["positions"]["ENEL.MI"]
    assert pos["cost_eur"] == pytest.approx(1000.5 + 2.95)  # la Tobin tax non entra nel costo fiscale

    sim["orders"].append({"id": "s1", "created": "2026-09-25T11:30:00+02:00", "ticker": "ENEL.MI", "side": "sell",
                          "all": True, "valid_until": "2026-09-25"})
    state, events = run(sim, {"ENEL.MI": bars([9.8, 12.0])}, state, NOW.replace(hour=12))
    sell = events[0]
    proceeds = 100 * 12 * 0.9995 - 2.95
    gain = proceeds - (1000.5 + 2.95)
    assert sell["gain"] == pytest.approx(gain)
    assert sell["capital_gains_tax"] == pytest.approx(round(gain * 0.26, 2))
    assert state["cash"] == pytest.approx(cash_after_buy + proceeds - round(gain * 0.26, 2))
    assert state["positions"] == {}


def test_losses_offset_future_gains():
    sim = sim_with([{"ticker": "A.MI", "side": "buy", "quantity": 100}, {"ticker": "B.MI", "side": "buy", "quantity": 100}])
    state, _ = run(sim, {"A.MI": bars([10, 10]), "B.MI": bars([10, 10])})
    sim["orders"] += [
        {"id": "s1", "created": "2026-09-25T12:00:00+02:00", "ticker": "A.MI", "side": "sell", "all": True, "valid_until": "2026-09-25"},
        {"id": "s2", "created": "2026-09-25T12:01:00+02:00", "ticker": "B.MI", "side": "sell", "all": True, "valid_until": "2026-09-25"},
    ]
    state, events = run(sim, {"A.MI": bars([10, 8]), "B.MI": bars([10, 13])}, state, NOW.replace(hour=13))
    loss_ev, gain_ev = events
    assert loss_ev["gain"] < 0 and loss_ev["capital_gains_tax"] == 0
    assert gain_ev["losses_used"] == pytest.approx(-loss_ev["gain"])
    assert gain_ev["capital_gains_tax"] == pytest.approx(round((gain_ev["gain"] + loss_ev["gain"]) * 0.26, 2))


def test_regime_dichiarativo_pays_tax_next_june():
    sim = sim_with([{"ticker": "SAP.DE", "side": "buy", "quantity": 10}], broker="degiro")
    state, _ = run(sim, {"SAP.DE": bars([100, 100])})
    assert any(t["type"] == "fee" for t in state["transactions"])  # connessione a Xetra, 2,50 €
    sim["orders"].append({"id": "s1", "created": "2026-09-25T12:00:00+02:00", "ticker": "SAP.DE", "side": "sell",
                          "all": True, "valid_until": "2026-09-25"})
    state, events = run(sim, {"SAP.DE": bars([100, 150])}, state, NOW.replace(hour=12))
    tax = events[0]["capital_gains_tax"]
    assert tax > 0 and events[0]["tax_withheld"] is False
    assert state["totals"]["tax_due"] == pytest.approx(tax)
    cash = state["cash"]
    later = datetime(2027, 7, 1, 11, 0, tzinfo=ROME)
    state, _ = run(sim, {}, state, later)
    assert state["cash"] == pytest.approx(cash - tax - 0)  # nessun titolo: niente bollo
    assert state["tax_due"] == []


def test_rejections_limits_and_pending():
    sim = sim_with([
        {"ticker": "A.MI", "side": "buy", "quantity": 10_000},  # troppo caro
        {"ticker": "A.MI", "side": "buy", "quantity": 10, "limit": 9.0},  # limite non raggiunto
        {"ticker": "A.MI", "side": "sell", "quantity": 5},  # non possiedo
        {"ticker": "A.MI", "side": "buy", "amount": 1000},  # a importo
    ])
    state, events = run(sim, {"A.MI": bars([10, 10])})
    kinds = [(e["type"], e.get("reason", "")[:10]) for e in events]
    assert kinds[0] == ("rejected", "liquidità ")
    assert kinds[1][0] == "rejected" and "non possiedi" in events[1]["reason"]
    buy = events[2]
    assert buy["type"] == "buy" and -buy["total"] <= 1000 and buy["qty"] == 99
    assert "o1" not in state["orders"]  # limite: resta in attesa
    # il giorno dopo l'ordine con limite scade
    state, events = run(sim, {"A.MI": bars([10, 10], end=datetime(2026, 9, 28).date())}, state,
                        datetime(2026, 9, 28, 10, 0, tzinfo=ROME))
    assert state["orders"]["o1"]["status"] == "expired"


def test_market_closed_keeps_order_pending():
    sim = sim_with([{"ticker": "A.MI", "side": "buy", "quantity": 10}])
    state, events = run(sim, {"A.MI": bars([10, 10])}, now=NOW.replace(hour=20))
    assert events == [] and state["orders"] == {}


def test_dividend_net_of_withholding_and_tax():
    sim = sim_with([{"ticker": "SAN.PA", "side": "buy", "quantity": 100}], broker="trade_republic")
    state, _ = run(sim, {"SAN.PA": bars([90, 90])})
    later = datetime(2026, 10, 2, 11, 0, tzinfo=ROME)
    df = bars([90, 90, 90, 90, 90, 90], end=later.date(), dividends=[0, 0, 0, 3.0, 0, 0])
    state, events = run(sim, {"SAN.PA": df}, state, later)
    div = next(e for e in events if e["type"] == "dividend")
    gross = 300.0
    assert div["withholding"] == pytest.approx(gross * 0.128)
    assert div["total"] == pytest.approx(gross * (1 - 0.128) * 0.74)
    assert state["costs"]["stamp_duty"] > 0  # bollo maturato in 7 giorni


def test_epoch_reset_and_old_settings_migration():
    old = normalize({"epoch": "x", "settings": {"commission_pct": 0.1, "commission_min": 1, "commission_max": 10,
                                                   "commission_fixed": 0}})
    assert old["settings"]["fees"]["us"] == {"fixed": 0, "pct": 0.1, "min": 1, "max": 10}
    sim = sim_with([])
    state, _ = run(sim, {})
    assert state["cash"] == 10_000
    sim2 = new_sim(5_000, "2026-09-25")
    state2, _ = run(sim2, {}, state)
    assert state2["cash"] == 5_000 and state2["epoch"] == sim2["epoch"]


def test_telegram_sim_flow(cfg, store, tmp_path):
    quotes = {"ENEL.MI": bars([8.5, 8.9])}
    store.write("universe.json", make_universe(["ENEL.MI"]))
    upd = lambda i, t: {"update_id": i, "message": {"text": t, "chat": {"id": 42}}}  # noqa: E731
    tg = FakeTelegram(updates=[upd(1, "/simnuovo 5000"), upd(2, "/simbroker degiro"), upd(3, "/simcompra ENEL.MI 100"),
                               upd(4, "/simversa 1000")])
    m = Monitor(cfg, store, tg, downloader=lambda ts, period="1mo", **k: {t: quotes[t] for t in ts if t in quotes},
                fundamentals=lambda t: {}, news=lambda t: [], config_path=tmp_path / "c.json",
                portfolio_path=tmp_path / "pf.enc.json", portfolio_password="passwordlunga",
                simulator_path=tmp_path / "sim.enc.json")
    m.run_cycle(NOW)
    assert any("DEGIRO" in t for t in tg.sent)
    buy_msg = next(t for t in tg.sent if "comprate 100" in t)
    assert "Tobin tax italiana 1,78 €" in buy_msg  # 0,2% di 890,45 €
    state = m.sim_state()
    assert state["deposited"] == 6000 and state["positions"]["ENEL.MI"]["qty"] == 100
    assert "ENEL" not in (tmp_path / "sim.enc.json").read_text()
    tg.updates = [upd(5, "/sim"), upd(6, "/simbroker")]
    m.process_commands()
    assert any("Simulatore" in t and "Valore del conto" in t for t in tg.sent)
    assert any("Broker disponibili" in t for t in tg.sent)
