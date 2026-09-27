"""Portafoglio personale: posizioni, guadagni e segnali di vendita.

Il portafoglio vive cifrato in config/portfolio.enc.json (lo scrive la
dashboard); il resoconto calcolato qui finisce cifrato nel branch `data`.
I "consigli" sono regole tecniche trasparenti, non previsioni: ogni segnale
dice esattamente quale condizione è scattata.
"""

from __future__ import annotations

import logging
import math
import os
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

import pandas as pd

from .config import ROOT, Config
from .crypto import WrongPassword, decrypt_json, encrypt_json
from .markets import exchange_info

log = logging.getLogger(__name__)

PORTFOLIO_PATH = Path(os.environ.get("ACTIONZZ_PORTFOLIO", ROOT / "config" / "portfolio.enc.json"))
REPORT_FILE = "portfolio_report.enc.json"

DEFAULT_SETTINGS = {
    "take_profit_pct": 25.0,  # guadagno oltre il quale conviene valutare di incassare
    "stop_loss_pct": 15.0,  # perdita oltre la quale conviene valutare di uscire
    "trailing_stop_pct": 12.0,  # calo dal massimo toccato da quando possiedi il titolo
    "tax_rate_pct": 26.0,  # tassazione italiana sulle plusvalenze
    "sell_alerts": True,  # avvisi Telegram sui segnali di vendita
}

# Yahoo quota Londra in pence: 1 GBp = 0,01 GBP
FX_TICKERS = {"GBP": "GBPEUR=X", "CHF": "CHFEUR=X", "SEK": "SEKEUR=X", "DKK": "DKKEUR=X", "NOK": "NOKEUR=X",
              "PLN": "PLNEUR=X", "USD": "USDEUR=X", "CAD": "CADEUR=X", "JPY": "JPYEUR=X", "HKD": "HKDEUR=X"}

VERDICTS = {
    "vendi": "🔴 Momento favorevole per vendere, almeno in parte",
    "valuta": "🟠 Da tenere d'occhio",
    "mantieni": "🟢 Nessun segnale di vendita",
}


# ------------------------------------------------------------------ caricamento


def load_portfolio(password: str | None, path: Path = PORTFOLIO_PATH) -> dict | None:
    """Portafoglio decifrato, o None se manca il file o la password."""
    if not path.exists():
        return None
    if not password:
        log.warning("Portafoglio presente ma PORTFOLIO_PASSWORD non impostata: lo salto")
        return None
    import json

    try:
        data = decrypt_json(json.loads(path.read_text(encoding="utf-8")), password)
    except WrongPassword:
        log.error("PORTFOLIO_PASSWORD non corrisponde alla password della dashboard")
        return None
    data.setdefault("positions", [])
    data["settings"] = {**DEFAULT_SETTINGS, **(data.get("settings") or {})}
    return data


def load_report(store, password: str | None) -> dict | None:
    envelope = store.read(REPORT_FILE)
    if not envelope or not password:
        return None
    try:
        return decrypt_json(envelope, password)
    except WrongPassword:
        return None


def save_report(store, report: dict, password: str) -> None:
    store.write(REPORT_FILE, encrypt_json(report, password))


# ------------------------------------------------------------------ posizioni


@dataclass
class Holding:
    ticker: str
    name: str
    quantity: float = 0.0
    cost: float = 0.0  # costo totale in valuta del titolo, commissioni incluse
    first_date: str | None = None
    lots: list[dict] = field(default_factory=list)

    @property
    def avg_price(self) -> float:
        return self.cost / self.quantity if self.quantity else 0.0


def aggregate(positions: list[dict]) -> dict[str, Holding]:
    """Somma i lotti di acquisto per ticker (le vendite li hanno già ridotti)."""
    out: dict[str, Holding] = {}
    for p in positions:
        qty = float(p.get("quantity") or 0)
        if qty <= 0:
            continue
        t = str(p["ticker"]).strip().upper()
        h = out.setdefault(t, Holding(ticker=t, name=p.get("name") or t))
        h.quantity += qty
        h.cost += qty * float(p.get("price") or 0) + float(p.get("fees") or 0)
        d = p.get("date")
        if d and (h.first_date is None or d < h.first_date):
            h.first_date = d
        h.lots.append(p)
    return out


# ------------------------------------------------------------------ indicatori


def rsi(close: pd.Series, n: int = 14) -> float | None:
    """RSI di Wilder: sopra 70 "ipercomprato", sotto 30 "ipervenduto"."""
    close = close.dropna()
    if len(close) <= n:
        return None
    delta = close.diff().dropna()
    gain = delta.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean().iloc[-1]
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean().iloc[-1]
    if loss == 0:
        return 100.0
    return float(100 - 100 / (1 + gain / loss))


def indicators(history: pd.DataFrame, since: str | None) -> dict:
    close = history["Close"].dropna()
    out = {
        "rsi": rsi(close),
        "sma50": float(close.tail(50).mean()) if len(close) >= 50 else None,
        "sma200": float(close.tail(200).mean()) if len(close) >= 200 else None,
        "high_52w": float(history["High"].tail(252).max()),
        "low_52w": float(history["Low"].tail(252).min()),
    }
    held = close[close.index >= pd.Timestamp(since)] if since else close
    if held.empty:
        held = close.tail(1)
    out["max_since_buy"] = float(held.max())
    return out


# ------------------------------------------------------------------ regole


def _sig(code: str, level: str, weight: int, text: str) -> dict:
    return {"code": code, "level": level, "weight": weight, "text": text}


def sell_signals(h: Holding, price: float, day_pct: float | None, ind: dict, fund: dict,
                 settings: dict, cfg: Config) -> tuple[list[dict], list[dict]]:
    """(segnali di vendita, motivi per tenere). Ogni voce ha un peso nel giudizio."""
    s = {**DEFAULT_SETTINGS, **settings}
    signals, holds = [], []
    pnl_pct = (price / h.avg_price - 1) * 100 if h.avg_price else 0.0

    if pnl_pct >= s["take_profit_pct"]:
        signals.append(_sig("take_profit", "strong", 2,
                            f"Guadagno del {_p(pnl_pct)}: obiettivo del +{_n(s['take_profit_pct'])}% raggiunto. "
                            "Valuta di incassare una parte e lasciar correre il resto."))
    if pnl_pct <= -s["stop_loss_pct"]:
        signals.append(_sig("stop_loss", "strong", 3,
                            f"Perdita del {_p(pnl_pct)}: oltre lo stop del −{_n(s['stop_loss_pct'])}%. "
                            "Chiediti se compreresti ancora questo titolo oggi."))

    peak = ind.get("max_since_buy")
    if peak and price < peak:
        from_max = (price / peak - 1) * 100
        if from_max <= -s["trailing_stop_pct"] and peak > h.avg_price:
            in_profit = price > h.avg_price
            signals.append(_sig("trailing_stop", "strong" if in_profit else "warn", 2 if in_profit else 1,
                                f"Sceso del {_p(from_max)} dal massimo ({_n(peak, 2)}) toccato da quando lo possiedi"
                                + (": proteggi il guadagno rimasto." if in_profit else ".")))

    r = ind.get("rsi")
    if r is not None and r >= 80:
        signals.append(_sig("rsi", "strong", 2, f"RSI {_n(r, 0)}: fortemente ipercomprato, spesso seguito da una pausa."))
    elif r is not None and r >= 70:
        signals.append(_sig("rsi", "warn", 1, f"RSI {_n(r, 0)}: ipercomprato."))
    elif r is not None and r <= 30:
        holds.append(_sig("oversold", "hold", -1, f"RSI {_n(r, 0)}: ipervenduto, vendere ora rischia di farlo vicino a un minimo."))

    sma50, sma200 = ind.get("sma50"), ind.get("sma200")
    if sma200:
        vs200 = (price / sma200 - 1) * 100
        if vs200 >= 25:
            signals.append(_sig("extended", "warn", 1, f"{_p(vs200)} sopra la media a 200 giorni: corsa molto estesa."))
        if sma50 and price < sma200 and sma50 < sma200:
            signals.append(_sig("downtrend", "warn", 1,
                                "Sotto la media a 200 giorni, con la media a 50 giorni più bassa: tendenza negativa."))

    target = fund.get("target_price")
    if target:
        if price >= target:
            signals.append(_sig("target", "warn", 1, f"Superato il prezzo obiettivo medio degli analisti ({_n(target, 2)})."))
        elif (target / price - 1) * 100 >= 15:
            holds.append(_sig("upside", "hold", -1,
                              f"Gli analisti vedono ancora {_p((target / price - 1) * 100)} di potenziale (obiettivo {_n(target, 2)})."))
    if fund.get("recommendation") in ("sell", "strong_sell", "underperform"):
        signals.append(_sig("analysts", "warn", 1, "Il giudizio medio degli analisti è negativo."))

    high = ind.get("high_52w")
    if high and price >= high * 0.98 and pnl_pct > 0:
        signals.append(_sig("near_high", "info", 0, "Vicino al massimo a 52 settimane."))

    if day_pct is not None and day_pct <= -cfg.drop_threshold_pct:
        holds.append(_sig("sudden_drop", "hold", -1,
                          f"Oggi {_p(day_pct)}: dopo un calo improvviso evita decisioni affrettate, aspetta di capirne il motivo."))
    return signals, holds


def verdict(signals: list[dict], holds: list[dict]) -> dict:
    score = sum(s["weight"] for s in signals) + sum(h["weight"] for h in holds)
    code = "vendi" if score >= 3 else "valuta" if score >= 1 else "mantieni"
    return {"code": code, "label": VERDICTS[code], "score": score}


# ------------------------------------------------------------------ resoconto


def currency_of(ticker: str, fund: dict) -> str:
    return fund.get("currency") or exchange_info(ticker)[1] or "EUR"


def fx_to_eur(currencies: set[str], downloader) -> dict[str, float]:
    rates = {"EUR": 1.0}
    need = {("GBP" if c == "GBp" else c) for c in currencies} - {"EUR"}
    pairs = {c: FX_TICKERS[c] for c in need if c in FX_TICKERS}
    if pairs:
        frames = downloader(list(pairs.values()), period="5d")
        for c, t in pairs.items():
            df = frames.get(t)
            if df is not None and not df.empty:
                rates[c] = float(df["Close"].dropna().iloc[-1])
    if "GBP" in rates:
        rates["GBp"] = rates["GBP"] / 100
    return rates


def _num(x, d=4):
    return None if x is None or (isinstance(x, float) and math.isnan(x)) else round(float(x), d)


def build_report(portfolio: dict, histories: dict[str, pd.DataFrame], fundamentals: dict[str, dict],
                 rates: dict[str, float], cfg: Config, today: date, previous: dict | None = None) -> dict:
    settings = {**DEFAULT_SETTINGS, **(portfolio.get("settings") or {})}
    holdings = aggregate(portfolio.get("positions", []))
    rows, missing = [], []
    for t, h in sorted(holdings.items()):
        df = histories.get(t)
        fund = fundamentals.get(t, {})
        if df is None or len(df) < 2:
            missing.append(t)
            continue
        close = df["Close"].dropna()
        price = float(close.iloc[-1])
        prev = float(close.iloc[-2])
        last_day = close.index[-1].date()
        day_pct = (price / prev - 1) * 100 if last_day == today else None
        ind = indicators(df, h.first_date)
        signals, holds = sell_signals(h, price, day_pct, ind, fund, settings, cfg)
        cur = currency_of(t, fund)
        fx = rates.get(cur)
        value, pnl = h.quantity * price, h.quantity * price - h.cost
        rows.append({
            "ticker": t,
            "name": fund.get("name") or h.name,
            "currency": cur,
            "quantity": h.quantity,
            "avg_price": _num(h.avg_price),
            "cost": _num(h.cost, 2),
            "price": _num(price),
            "price_date": last_day.isoformat(),
            "day_pct": _num(day_pct, 3),
            "value": _num(value, 2),
            "pnl": _num(pnl, 2),
            "pnl_pct": _num((price / h.avg_price - 1) * 100 if h.avg_price else None, 2),
            "fx": fx,
            "value_eur": _num(value * fx, 2) if fx else None,
            "cost_eur": _num(h.cost * fx, 2) if fx else None,
            "pnl_eur": _num(pnl * fx, 2) if fx else None,
            "day_pnl_eur": _num(h.quantity * (price - prev) * fx, 2) if fx and day_pct is not None else None,
            "first_date": h.first_date,
            "days_held": (today - date.fromisoformat(h.first_date)).days if h.first_date else None,
            "lots": len(h.lots),
            "rsi": _num(ind["rsi"], 1),
            "sma50": _num(ind["sma50"]),
            "sma200": _num(ind["sma200"]),
            "vs_sma200_pct": _num((price / ind["sma200"] - 1) * 100, 2) if ind["sma200"] else None,
            "max_since_buy": _num(ind["max_since_buy"]),
            "from_max_pct": _num((price / ind["max_since_buy"] - 1) * 100, 2),
            "high_52w": _num(ind["high_52w"]),
            "low_52w": _num(ind["low_52w"]),
            "target_price": _num(fund.get("target_price")),
            "pe": _num(fund.get("pe"), 2),
            "dividend_yield": _num(fund.get("dividend_yield")),
            "recommendation": fund.get("recommendation"),
            "sector": fund.get("sector"),
            "signals": signals,
            "holds": holds,
            "verdict": verdict(signals, holds),
        })

    total_value = sum(r["value_eur"] or 0 for r in rows)
    for r in rows:
        r["weight_pct"] = _num((r["value_eur"] or 0) / total_value * 100, 2) if total_value else None
    cost = sum(r["cost_eur"] or 0 for r in rows)
    pnl = total_value - cost
    gains = sum(max(r["pnl_eur"] or 0, 0) for r in rows)
    tax = gains * settings["tax_rate_pct"] / 100
    day_pnl = [r["day_pnl_eur"] for r in rows if r["day_pnl_eur"] is not None]
    return {
        "generated": datetime.now().astimezone().isoformat(timespec="seconds"),
        "day": today.isoformat(),
        "base_currency": "EUR",
        "settings": settings,
        "totals": {
            "value_eur": round(total_value, 2),
            "cost_eur": round(cost, 2),
            "pnl_eur": round(pnl, 2),
            "pnl_pct": round(pnl / cost * 100, 2) if cost else None,
            "tax_if_sold_eur": round(tax, 2),
            "net_pnl_eur": round(pnl - tax, 2),
            "day_pnl_eur": round(sum(day_pnl), 2) if day_pnl else None,
            "positions": len(rows),
            "to_sell": sum(1 for r in rows if r["verdict"]["code"] == "vendi"),
            "to_watch": sum(1 for r in rows if r["verdict"]["code"] == "valuta"),
        },
        "holdings": rows,
        "missing": missing,
        "rates": rates,
        "notified": (previous or {}).get("notified", {}),
        "fundamentals": {"day": today.isoformat(), "data": fundamentals},
    }


def new_notifications(report: dict) -> list[dict]:
    """Titoli da segnalare su Telegram: nuovi segnali forti o d'attenzione su titoli da vendere/valutare.

    Aggiorna report["notified"] così lo stesso segnale non viene ripetuto finché
    resta attivo; se sparisce e poi ritorna, viene segnalato di nuovo.
    """
    notified = report.setdefault("notified", {})
    out = []
    for r in report["holdings"]:
        active = {s["code"] for s in r["signals"] if s["level"] in ("strong", "warn")}
        seen = set(notified.get(r["ticker"], []))
        fresh = active - seen
        if fresh and r["verdict"]["code"] != "mantieni":
            out.append({**r, "new_codes": sorted(fresh)})
        notified[r["ticker"]] = sorted(active)
    for t in list(notified):
        if t not in {r["ticker"] for r in report["holdings"]}:
            del notified[t]
    return out


def _n(x: float, d: int = 1) -> str:
    if d == 1 and float(x).is_integer():
        d = 0
    s = f"{x:,.{d}f}"
    return s.replace(",", "§").replace(".", ",").replace("§", ".")


def _p(x: float) -> str:
    return ("−" if x < 0 else "+") + _n(abs(x)) + "%"
