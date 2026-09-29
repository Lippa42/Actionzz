"""Simulatore di compravendita con soldi finti ma costi veri.

Due file, entrambi cifrati con la password della dashboard:
- config/simulator.enc.json: quello che decidi tu (versamenti, ordini, costi).
  Lo scrivono la dashboard e i comandi Telegram.
- simulator_state.enc.json (branch `data`): il "conto titoli" gestito dallo
  scanner: liquidità, posizioni, movimenti, zainetto fiscale, storico del valore.

Gli ordini vengono eseguiti dallo scanner a mercato aperto, al prezzo del momento,
con le regole di un investitore italiano in regime amministrato.
"""

from __future__ import annotations

import json
import logging
import math
import os
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd

from .config import ROOT, Config
from .crypto import WrongPassword, decrypt_json, encrypt_json
from .markets import exchange_info, is_trading_window

log = logging.getLogger(__name__)

SIM_PATH = Path(os.environ.get("ACTIONZZ_SIMULATOR", ROOT / "config" / "simulator.enc.json"))
BROKERS_PATH = ROOT / "site" / "brokers.json"  # catalogo condiviso con la dashboard
STATE_FILE = "simulator_state.enc.json"
DEFAULT_BROKER = "fineco_trading"

BASE_SETTINGS = {
    "broker": DEFAULT_BROKER,
    # commissioni per mercato: quota fissa + percentuale, con minimo e massimo (0 = nessuno)
    "fees": {m: {"fixed": 0.0, "pct": 0.19, "min": 2.95, "max": 19.0} for m in ("it", "eu", "us")},
    "fx_spread_pct": 0.10,  # costo del cambio per i titoli non in euro
    "slippage_pct": 0.05,  # scostamento dal prezzo visualizzato
    "connectivity_fee": 0.0,  # costo annuo per ogni borsa estera usata (es. DEGIRO)
    "monthly_fee": 0.0,  # canone mensile dell'abbonamento (es. Scalable PRIME+)
    "regime": "amministrato",  # oppure "dichiarativo": tasse pagate l'anno dopo
    "transaction_taxes": True,  # Tobin tax, stamp duty & co.
    "capital_gains_tax_pct": 26.0,
    "dividend_tax_pct": 26.0,
    "stamp_duty_pct": 0.20,  # imposta di bollo (o IVAFE) annua sul dossier titoli
}


def load_brokers(path: Path = BROKERS_PATH) -> list[dict]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))["brokers"]
    except (OSError, ValueError, KeyError):
        return []


def broker_settings(broker_id: str, base: dict | None = None) -> dict:
    """Impostazioni con le tariffe di un broker del catalogo."""
    s = json.loads(json.dumps(base or BASE_SETTINGS))
    b = next((b for b in load_brokers() if b["id"] == broker_id), None)
    if b is None:
        raise KeyError(broker_id)
    s.update(broker=b["id"], fees=b["fees"], fx_spread_pct=b["fx_spread_pct"], slippage_pct=b["slippage_pct"],
             connectivity_fee=b.get("connectivity_fee", 0), monthly_fee=b.get("monthly_fee", 0), regime=b["regime"])
    return s


def default_settings() -> dict:
    try:
        return broker_settings(DEFAULT_BROKER)
    except KeyError:
        return json.loads(json.dumps(BASE_SETTINGS))


DEFAULT_SETTINGS = BASE_SETTINGS  # compatibilità

# tasse sulle transazioni, pagate all'acquisto (per semplicità in base alla borsa).
# Italia: 0,2% dal 1/1/2026 (legge di bilancio 2026, prima 0,1%); Francia: 0,4% dal 1/4/2025.
TRANSACTION_TAXES = {
    ".MI": ("Tobin tax italiana", 0.20),
    ".PA": ("tassa francese sulle transazioni", 0.40),
    ".MC": ("tassa spagnola sulle transazioni", 0.20),
    ".L": ("stamp duty britannica", 0.50),
    ".IR": ("stamp duty irlandese", 1.00),
}

# ritenuta alla fonte estera sui dividendi (aliquote indicative per un residente italiano)
DIVIDEND_WITHHOLDING = {
    ".MI": 0.0, ".PA": 12.8, ".DE": 26.375, ".SW": 35.0, ".AS": 15.0, ".MC": 19.0, ".L": 0.0, ".IR": 25.0,
    ".BR": 30.0, ".LS": 25.0, ".HE": 35.0, ".VI": 27.5, ".ST": 30.0, ".CO": 27.0, ".OL": 25.0, ".WA": 19.0,
}
US_WITHHOLDING = 15.0  # con modulo W-8BEN
LOSS_CARRY_YEARS = 4  # le minusvalenze valgono fino al 31/12 del quarto anno successivo


def suffix(ticker: str) -> str:
    dot = ticker.rfind(".")
    return ticker[dot:].upper() if dot > 0 else ""


def currency_for(ticker: str) -> str:
    cur = exchange_info(ticker)[1]
    return cur or ("USD" if not suffix(ticker) else "EUR")


def is_european(ticker: str) -> bool:
    return bool(exchange_info(ticker)[1])


def market_of(ticker: str) -> str:
    """Scaglione di commissioni: Borsa Italiana, altre borse europee, resto del mondo (USA)."""
    if suffix(ticker) == ".MI":
        return "it"
    return "eu" if is_european(ticker) else "us"


# ------------------------------------------------------------------- file


def load_sim(password: str | None, path: Path = SIM_PATH) -> dict | None:
    if not path.exists() or not password:
        return None
    try:
        sim = decrypt_json(json.loads(path.read_text(encoding="utf-8")), password)
    except WrongPassword:
        log.error("PORTFOLIO_PASSWORD non apre il simulatore")
        return None
    return normalize(sim)


def normalize(sim: dict) -> dict:
    sim.setdefault("version", 1)
    sim.setdefault("epoch", "1")
    sim.setdefault("deposits", [])
    sim.setdefault("orders", [])
    raw = sim.get("settings") or {}
    if "fees" not in raw and "commission_pct" in raw:  # vecchio formato: una sola tariffa
        fee = {"fixed": raw.get("commission_fixed", 0.0), "pct": raw["commission_pct"],
               "min": raw.get("commission_min", 0.0), "max": raw.get("commission_max", 0.0)}
        raw = {**raw, "fees": {m: dict(fee) for m in ("it", "eu", "us")}, "broker": "custom"}
    base = default_settings() if not raw else json.loads(json.dumps(BASE_SETTINGS))
    sim["settings"] = {**base, **{k: v for k, v in raw.items() if not k.startswith("commission_")}}
    return sim


def new_sim(budget: float, today: str) -> dict:
    return normalize({"epoch": os.urandom(4).hex(), "deposits": [
        {"id": os.urandom(6).hex(), "amount": budget, "date": today, "note": "budget iniziale"}]})


def save_sim(sim: dict, password: str, path: Path = SIM_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(encrypt_json(sim, password)) + "\n", encoding="utf-8")


def load_state(store, password: str | None) -> dict | None:
    env = store.read(STATE_FILE)
    if not env or not password:
        return None
    try:
        return decrypt_json(env, password)
    except WrongPassword:
        return None


def save_state(store, state: dict, password: str) -> None:
    store.write(STATE_FILE, encrypt_json(state, password))


def empty_state(epoch: str) -> dict:
    return {
        "epoch": epoch,
        "cash": 0.0,
        "deposited": 0.0,
        "positions": {},
        "processed_deposits": [],
        "orders": {},  # id -> esito
        "transactions": [],
        "losses": [],  # zainetto fiscale: [{"year", "amount"}]
        "dividends_seen": [],
        "bollo_day": None,
        "connectivity": [],  # "anno:borsa" già pagati
        "tax_due": [],  # regime dichiarativo: [{"year", "amount"}] da pagare il 30 giugno dell'anno dopo
        "costs": {"commissions": 0.0, "transaction_taxes": 0.0, "fx": 0.0, "slippage": 0.0, "stamp_duty": 0.0,
                  "capital_gains_tax": 0.0, "dividend_tax": 0.0},
        "realized": 0.0,
        "dividends": 0.0,
        "prices": {},
        "history": [],
    }


# ------------------------------------------------------------------- costi


def commission(amount_eur: float, s: dict, market: str = "it") -> float:
    f = s["fees"].get(market) or s["fees"]["it"]
    if f.get("free_from") and amount_eur >= f["free_from"]:
        return 0.0  # ordini gratuiti sopra una soglia (es. Scalable PRIME+ da 250 €)
    fee = f["fixed"] + amount_eur * f["pct"] / 100
    if f["min"] > 0:
        fee = max(fee, f["min"])
    if f["max"] > 0:
        fee = min(fee, f["max"])
    return round(fee, 2)


def transaction_tax(ticker: str, amount_eur: float, s: dict) -> tuple[str, float]:
    if not s["transaction_taxes"]:
        return "", 0.0
    name, rate = TRANSACTION_TAXES.get(suffix(ticker), ("", 0.0))
    return name, round(amount_eur * rate / 100, 2)


def usable_losses(state: dict, year: int) -> list[dict]:
    return [x for x in state["losses"] if x["year"] + LOSS_CARRY_YEARS >= year and x["amount"] > 0.005]


def buy_quote(ticker: str, qty: int, price: float, fx: float, s: dict) -> dict:
    """Quanto costa comprare qty azioni al prezzo (valuta locale) e cambio dati."""
    fill = price * (1 + s["slippage_pct"] / 100)
    gross = qty * fill * fx
    fx_cost = round(gross * s["fx_spread_pct"] / 100, 2) if currency_for(ticker) != "EUR" else 0.0
    comm = commission(gross, s, market_of(ticker))
    tax_name, tax = transaction_tax(ticker, gross, s)
    return {"fill": fill, "gross": gross, "fx_cost": fx_cost, "commission": comm, "tax_name": tax_name,
            "transaction_tax": tax, "slippage": qty * (fill - price) * fx, "total": gross + fx_cost + comm + tax}


def max_affordable(ticker: str, budget: float, price: float, fx: float, s: dict) -> int:
    qty = int(budget / (price * fx * (1 + s["slippage_pct"] / 100)))
    while qty > 0 and buy_quote(ticker, qty, price, fx, s)["total"] > budget + 1e-9:
        qty -= 1
    return max(qty, 0)


# ------------------------------------------------------------------- motore


def _tx(state: dict, **kw) -> dict:
    kw = {k: (round(v, 4) if isinstance(v, float) else v) for k, v in kw.items()}
    state["transactions"].append(kw)
    return kw


def charge_connectivity(state: dict, ticker: str, s: dict, now: datetime) -> float:
    """Costo annuo di connessione a una borsa estera, alla prima operazione dell'anno (es. DEGIRO)."""
    fee = s.get("connectivity_fee") or 0.0
    key = f"{now.year}:{suffix(ticker) or 'US'}"
    if fee <= 0 or market_of(ticker) == "it" or key in state["connectivity"]:
        return 0.0
    state["connectivity"].append(key)
    state["cash"] -= fee
    state["costs"]["commissions"] += fee
    _tx(state, type="fee", time=now.isoformat(timespec="seconds"), ticker=ticker,
        note=f"costo annuo di connessione alla borsa {suffix(ticker) or 'USA'}", total=-fee, cash_after=state["cash"])
    return fee


def charge_subscription(state: dict, s: dict, now: datetime) -> float:
    """Canone mensile del piano, addebitato una volta al mese (es. Scalable PRIME+ 4,99 €)."""
    fee = s.get("monthly_fee") or 0.0
    month = now.strftime("%Y-%m")
    paid = state.setdefault("subscription", [])
    if fee <= 0 or month in paid or not state["deposited"]:
        return 0.0
    paid.append(month)
    state["cash"] -= fee
    state["costs"]["commissions"] += fee
    _tx(state, type="fee", time=now.isoformat(timespec="seconds"), note=f"canone mensile {month}", total=-fee,
        cash_after=state["cash"])
    return fee


def charge_tax(state: dict, amount: float, s: dict, now: datetime, kind: str) -> bool:
    """Regime amministrato: tassa trattenuta subito. Dichiarativo: da pagare il 30 giugno dell'anno dopo."""
    if amount <= 0:
        return True
    state["costs"][kind] += amount
    if s.get("regime") == "dichiarativo":
        state["tax_due"].append({"year": now.year, "amount": amount})
        return False
    state["cash"] -= amount
    return True


def pay_due_taxes(state: dict, now: datetime) -> float:
    """In regime dichiarativo le imposte dell'anno X si pagano con il saldo di fine giugno dell'anno X+1."""
    paid = 0.0
    keep = []
    for t in state["tax_due"]:
        if (now.date() >= date(t["year"] + 1, 6, 30)):
            paid += t["amount"]
        else:
            keep.append(t)
    if paid:
        state["tax_due"] = keep
        state["cash"] -= paid
        _tx(state, type="tax_payment", time=now.isoformat(timespec="seconds"), total=-paid, cash_after=state["cash"],
            note="saldo imposte in dichiarazione dei redditi (regime dichiarativo)")
    return paid


def execute_buy(state: dict, order: dict, qty: int, price: float, fx: float, s: dict, now: datetime, name: str) -> dict:
    t = order["ticker"]
    charge_connectivity(state, t, s, now)
    q = buy_quote(t, qty, price, fx, s)
    pos = state["positions"].setdefault(t, {"qty": 0, "cost_eur": 0.0, "name": name, "currency": currency_for(t),
                                           "first_date": now.date().isoformat()})
    pos["qty"] += qty
    # le tasse sulle transazioni non sono deducibili: non entrano nel costo fiscale
    pos["cost_eur"] += q["gross"] + q["fx_cost"] + q["commission"]
    state["cash"] -= q["total"]
    c = state["costs"]
    c["commissions"] += q["commission"]
    c["transaction_taxes"] += q["transaction_tax"]
    c["fx"] += q["fx_cost"]
    c["slippage"] += q["slippage"]
    return _tx(state, type="buy", time=now.isoformat(timespec="seconds"), order=order["id"], ticker=t, name=name,
               qty=qty, price=q["fill"], currency=pos["currency"], fx=fx, gross=q["gross"], commission=q["commission"],
               transaction_tax=q["transaction_tax"], tax_name=q["tax_name"], fx_cost=q["fx_cost"],
               total=-q["total"], cash_after=state["cash"])


def execute_sell(state: dict, order: dict, qty: int, price: float, fx: float, s: dict, now: datetime) -> dict:
    t = order["ticker"]
    charge_connectivity(state, t, s, now)
    pos = state["positions"][t]
    fill = price * (1 - s["slippage_pct"] / 100)
    gross = qty * fill * fx
    fx_cost = round(gross * s["fx_spread_pct"] / 100, 2) if pos["currency"] != "EUR" else 0.0
    comm = commission(gross, s, market_of(t))
    proceeds = gross - fx_cost - comm
    basis = pos["cost_eur"] * qty / pos["qty"]  # costo medio ponderato
    gain = proceeds - basis
    tax, used = 0.0, 0.0
    if gain > 0:
        remaining = gain
        for loss in sorted(usable_losses(state, now.year), key=lambda x: x["year"]):
            take = min(loss["amount"], remaining)
            loss["amount"] -= take
            remaining -= take
            used += take
        tax = round(remaining * s["capital_gains_tax_pct"] / 100, 2)
    elif gain < 0:
        state["losses"].append({"year": now.year, "amount": -gain})
    pos["qty"] -= qty
    pos["cost_eur"] -= basis
    if pos["qty"] == 0:
        del state["positions"][t]
    state["cash"] += proceeds
    withheld = charge_tax(state, tax, s, now, "capital_gains_tax")
    state["realized"] += gain - tax
    c = state["costs"]
    c["commissions"] += comm
    c["fx"] += fx_cost
    c["slippage"] += qty * (price - fill) * fx
    return _tx(state, type="sell", time=now.isoformat(timespec="seconds"), order=order["id"], ticker=t, name=pos["name"],
               qty=qty, price=fill, currency=pos["currency"], fx=fx, gross=gross, commission=comm, fx_cost=fx_cost,
               cost_basis=basis, gain=gain, losses_used=used, capital_gains_tax=tax, tax_withheld=withheld,
               total=proceeds - tax if withheld else proceeds, cash_after=state["cash"])


def order_valid_until(order: dict) -> str:
    if order.get("valid_until"):
        return order["valid_until"]
    created = datetime.fromisoformat(order["created"]).date()
    days = 1 if order.get("validity", "day") == "day" else 90
    return (created + timedelta(days=days)).isoformat()


def process(sim: dict, state: dict | None, quotes: dict[str, pd.DataFrame], rates: dict[str, float],
            names: dict[str, str], cfg: Config, now: datetime) -> tuple[dict, list[dict]]:
    """Applica versamenti, dividendi, ordini e bollo. Restituisce (stato, eventi da notificare)."""
    s = sim["settings"]
    if state is None or state.get("epoch") != sim["epoch"]:
        state = empty_state(sim["epoch"])
    events: list[dict] = []
    today = now.date()

    pay_due_taxes(state, now)

    for d in sim["deposits"]:
        if d["id"] in state["processed_deposits"]:
            continue
        state["processed_deposits"].append(d["id"])
        state["cash"] += float(d["amount"])
        state["deposited"] += float(d["amount"])
        _tx(state, type="deposit", time=now.isoformat(timespec="seconds"), total=float(d["amount"]),
            note=d.get("note", ""), cash_after=state["cash"])

    charge_subscription(state, s, now)

    def bar_today(t):
        df = quotes.get(t)
        if df is None or df.empty:
            return None
        close = df["Close"].dropna()
        return float(close.iloc[-1]) if not close.empty and close.index[-1].date() == today else None

    def fx_of(t):
        return rates.get(currency_for(t))

    # dividendi staccati mentre possedevi il titolo
    for t, pos in list(state["positions"].items()):
        df = quotes.get(t)
        if df is None or "Dividends" not in df:
            continue
        for day, amount in df["Dividends"].items():
            key = f"{t}@{day.date().isoformat()}"
            if amount <= 0 or key in state["dividends_seen"] or day.date().isoformat() <= pos["first_date"] or day.date() > today:
                continue
            fx = fx_of(t)
            if not fx:
                continue
            state["dividends_seen"].append(key)
            gross = pos["qty"] * float(amount) * fx
            fx_cost = gross * s["fx_spread_pct"] / 100 if pos["currency"] != "EUR" else 0.0
            wh_rate = DIVIDEND_WITHHOLDING.get(suffix(t), US_WITHHOLDING if not suffix(t) else 0.0)
            withholding = (gross - fx_cost) * wh_rate / 100
            it_tax = (gross - fx_cost - withholding) * s["dividend_tax_pct"] / 100
            net = gross - fx_cost - withholding - it_tax
            state["cash"] += gross - fx_cost - withholding
            charge_tax(state, it_tax, s, now, "dividend_tax")
            state["dividends"] += net
            state["costs"]["dividend_tax"] += withholding
            state["costs"]["fx"] += fx_cost
            events.append(_tx(state, type="dividend", time=now.isoformat(timespec="seconds"), ticker=t, name=pos["name"],
                              per_share=float(amount), qty=pos["qty"], gross=gross, withholding=withholding,
                              withholding_pct=wh_rate, italian_tax=it_tax, fx_cost=fx_cost, total=net,
                              cash_after=state["cash"]))

    # ordini, nell'ordine in cui li hai inseriti
    for order in sorted(sim["orders"], key=lambda o: o["created"]):
        oid = order["id"]
        if oid in state["orders"]:
            continue
        if order.get("cancelled"):
            state["orders"][oid] = {"status": "cancelled", "time": now.isoformat(timespec="seconds")}
            continue
        if today.isoformat() > order_valid_until(order):
            state["orders"][oid] = {"status": "expired", "time": now.isoformat(timespec="seconds"),
                                    "reason": "scaduto senza essere eseguito"}
            events.append({"type": "expired", **order})
            continue
        t = order["ticker"]
        price = bar_today(t)
        if price is None or (is_european(t) and not is_trading_window(cfg, now)):
            continue  # mercato chiuso: l'ordine resta in attesa
        fx = fx_of(t)
        if not fx:
            continue
        side = order["side"]
        fill = price * (1 + s["slippage_pct"] / 100) if side == "buy" else price * (1 - s["slippage_pct"] / 100)
        limit = order.get("limit")
        if limit and ((side == "buy" and fill > limit) or (side == "sell" and fill < limit)):
            continue  # prezzo limite non raggiunto
        result = {"time": now.isoformat(timespec="seconds")}
        if side == "buy":
            qty = int(order.get("quantity") or 0)
            if not qty and order.get("amount"):
                qty = max_affordable(t, min(float(order["amount"]), state["cash"]), price, fx, s)
            if qty <= 0:
                result.update(status="rejected", reason="importo troppo basso per comprare anche una sola azione")
            elif buy_quote(t, qty, price, fx, s)["total"] > state["cash"] + 1e-6:
                result.update(status="rejected", reason="liquidità insufficiente: versa altro denaro o riduci la quantità")
            else:
                tx = execute_buy(state, order, qty, price, fx, s, now, names.get(t, t))
                result.update(status="filled", tx=len(state["transactions"]) - 1)
                events.append(tx)
        else:
            owned = state["positions"].get(t, {}).get("qty", 0)
            qty = owned if order.get("all") else int(order.get("quantity") or 0)
            if owned <= 0 or qty <= 0 or qty > owned:
                result.update(status="rejected", reason=f"non possiedi abbastanza azioni (ne hai {owned})")
            else:
                tx = execute_sell(state, order, qty, price, fx, s, now)
                result.update(status="filled", tx=len(state["transactions"]) - 1)
                events.append(tx)
        if result["status"] == "rejected":
            events.append({"type": "rejected", "reason": result["reason"], **order})
        state["orders"][oid] = result

    # prezzi e valore attuale delle posizioni
    positions_value = 0.0
    for t, pos in state["positions"].items():
        df = quotes.get(t)
        fx = fx_of(t)
        if df is None or df.empty or not fx:
            continue
        close = df["Close"].dropna()
        price = float(close.iloc[-1])
        prev = float(close.iloc[-2]) if len(close) > 1 else price
        state["prices"][t] = {"price": price, "date": close.index[-1].date().isoformat(), "fx": fx,
                              "day_pct": (price / prev - 1) * 100 if close.index[-1].date() == today else None}
        positions_value += pos["qty"] * price * fx

    # imposta di bollo, giorno per giorno sul valore dei titoli
    last = date.fromisoformat(state["bollo_day"]) if state["bollo_day"] else today
    days = (today - last).days
    if days > 0 and positions_value > 0:
        bollo = positions_value * s["stamp_duty_pct"] / 100 * days / 365
        state["cash"] -= bollo
        state["costs"]["stamp_duty"] += bollo
    state["bollo_day"] = today.isoformat()

    state["totals"] = totals(state, positions_value, s, now.year)
    point = {"day": today.isoformat(), "equity": round(state["totals"]["equity"], 2),
             "deposited": round(state["deposited"], 2), "cash": round(state["cash"], 2)}
    state["history"] = [h for h in state["history"] if h["day"] != point["day"]] + [point]
    state["history"] = state["history"][-1500:]
    state["transactions"] = state["transactions"][-2000:]
    state["generated"] = now.isoformat(timespec="seconds")
    return state, events


def totals(state: dict, positions_value: float, s: dict, year: int) -> dict:
    """Valore del conto, anche "al netto": quanto incasseresti vendendo tutto oggi."""
    liquidation = 0.0
    losses = sum(x["amount"] for x in usable_losses(state, year))
    for t, pos in state["positions"].items():
        p = state["prices"].get(t)
        if not p:
            continue
        gross = pos["qty"] * p["price"] * (1 - s["slippage_pct"] / 100) * p["fx"]
        net = gross - (gross * s["fx_spread_pct"] / 100 if pos["currency"] != "EUR" else 0) - commission(gross, s, market_of(t))
        gain = net - pos["cost_eur"]
        if gain > 0:
            offset = min(losses, gain)
            losses -= offset
            net -= (gain - offset) * s["capital_gains_tax_pct"] / 100
        liquidation += net
    due = sum(t["amount"] for t in state.get("tax_due", []))
    equity = state["cash"] + positions_value
    net_equity = state["cash"] + liquidation - due
    total_costs = sum(state["costs"].values())
    return {
        "equity": equity,
        "net_equity": net_equity,
        "cash": state["cash"],
        "positions_value": positions_value,
        "deposited": state["deposited"],
        "pnl": equity - state["deposited"],
        "pnl_pct": (equity / state["deposited"] - 1) * 100 if state["deposited"] else None,
        "net_pnl": net_equity - state["deposited"],
        "net_pnl_pct": (net_equity / state["deposited"] - 1) * 100 if state["deposited"] else None,
        "total_costs": total_costs,
        "losses_available": sum(x["amount"] for x in usable_losses(state, year)),
        "tax_due": due,
        "realized": state["realized"],
        "dividends": state["dividends"],
    }


def round_state(state: dict) -> dict:
    """Arrotonda per un JSON più compatto (i calcoli restano in virgola mobile)."""
    def r(v):
        if isinstance(v, float):
            return round(v, 6) if abs(v) < 1 else round(v, 4)
        if isinstance(v, dict):
            return {k: r(x) for k, x in v.items()}
        if isinstance(v, list):
            return [r(x) for x in v]
        return v
    return r(state)


def is_nan(x) -> bool:
    return isinstance(x, float) and math.isnan(x)
