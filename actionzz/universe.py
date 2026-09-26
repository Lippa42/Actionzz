"""Selezione dell'universo: i titoli europei più stabili sugli ultimi anni.

Parte da data/candidates.csv (indici europei principali), scarica lo storico,
calcola la volatilità annua e tiene gli N titoli meno volatili.
"""

from __future__ import annotations

import csv
import logging
import math
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from . import data
from .config import CANDIDATES_PATH, Config
from .markets import exchange_info
from .state import Store

log = logging.getLogger(__name__)

TRADING_DAYS = 252
STALE_DAYS = 14  # un titolo senza prezzi da due settimane è delistato o sospeso
MAX_FLAT_DAYS = 0.2  # oltre il 20% di sedute senza variazioni i dati non sono affidabili


def load_candidates(path: Path = CANDIDATES_PATH) -> dict[str, dict]:
    with path.open(encoding="utf-8") as fh:
        return {row["ticker"]: row for row in csv.DictReader(fh)}


def compute_metrics(close: pd.Series) -> dict | None:
    """Metriche di stabilità da una serie di chiusure (rettificate)."""
    close = close.dropna()
    close = close[close > 0]
    if len(close) < 60:
        return None
    rets = np.log(close).diff().dropna()
    # i ritorni assurdi sono quasi sempre errori di dato (es. pence/sterline)
    rets = rets[rets.abs() < 0.5]
    daily_sigma = float(rets.std())
    # prezzo quasi sempre fermo: titolo illiquido o serie di Yahoo rotta
    stale_share = float((rets.tail(250) == 0).mean()) if len(rets) else 1.0
    years = (close.index[-1] - close.index[0]).days / 365.25
    drawdown = close / close.cummax() - 1
    return {
        "vol": round(daily_sigma * math.sqrt(TRADING_DAYS) * 100, 2),
        "daily_sigma": round(daily_sigma * 100, 3),
        "max_drawdown": round(float(drawdown.min()) * 100, 1),
        "return_total": round(float(close.iloc[-1] / close.iloc[0] - 1) * 100, 1),
        "return_1y": _period_return(close, 365),
        "years": round(years, 2),
        "last_price": round(float(close.iloc[-1]), 4),
        "last_date": close.index[-1].date().isoformat(),
        "flat_days": round(stale_share, 3),
    }


def _period_return(close: pd.Series, days: int) -> float | None:
    past = close[close.index <= close.index[-1] - pd.Timedelta(days=days)]
    if past.empty:
        return None
    return round(float(close.iloc[-1] / past.iloc[-1] - 1) * 100, 1)


def select(metrics: dict[str, dict], candidates: dict[str, dict], cfg: Config, today=None) -> tuple[list[dict], dict]:
    """Applica i filtri e restituisce (titoli scelti, conteggi degli scarti)."""
    today = pd.Timestamp(today or datetime.now(timezone.utc).date())
    rejected = {"storico_breve": 0, "senza_prezzi_recenti": 0, "dati_anomali": 0, "esclusi": 0}
    eligible = []
    for ticker, m in metrics.items():
        if ticker in cfg.exclude:
            rejected["esclusi"] += 1
            continue
        if (today - pd.Timestamp(m["last_date"])).days > STALE_DAYS:
            rejected["senza_prezzi_recenti"] += 1
            continue
        if m.get("flat_days", 0) > MAX_FLAT_DAYS and ticker not in cfg.include:
            rejected["dati_anomali"] += 1
            continue
        if m["years"] < cfg.min_history_years and ticker not in cfg.include:
            rejected["storico_breve"] += 1
            continue
        eligible.append(ticker)

    eligible.sort(key=lambda t: metrics[t]["vol"])
    chosen = [t for t in eligible if t in cfg.include]
    for t in eligible:
        if len(chosen) >= cfg.universe_size:
            break
        if t not in chosen:
            chosen.append(t)

    items = []
    for rank, t in enumerate(sorted(chosen, key=lambda t: metrics[t]["vol"]), start=1):
        country, currency, exchange = exchange_info(t)
        cand = candidates.get(t, {})
        items.append(
            {
                "ticker": t,
                "name": cand.get("name") or t,
                "sector": cand.get("sector", ""),
                "index": cand.get("index", ""),
                "country": country,
                "currency": currency,
                "exchange": exchange,
                "rank": rank,
                "forced": t in cfg.include,
                **metrics[t],
            }
        )
    return items, rejected


def build_universe(cfg: Config, store: Store, candidates_path: Path = CANDIDATES_PATH) -> dict:
    candidates = load_candidates(candidates_path)
    tickers = sorted(set(candidates) | set(cfg.include))
    log.info("Scarico %d anni di storico per %d candidati...", cfg.lookback_years, len(tickers))
    history = data.download_daily(tickers, period=f"{cfg.lookback_years}y", auto_adjust=True)
    metrics = {t: m for t, df in history.items() if (m := compute_metrics(df["Close"])) is not None}
    items, rejected = select(metrics, candidates, cfg)
    universe = {
        "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "params": {
            "size": cfg.universe_size,
            "lookback_years": cfg.lookback_years,
            "min_history_years": cfg.min_history_years,
        },
        "stats": {
            "candidates": len(tickers),
            "with_data": len(metrics),
            "selected": len(items),
            "rejected": rejected,
            "vol_median": round(float(np.median([i["vol"] for i in items])), 2) if items else None,
            "vol_max": max((i["vol"] for i in items), default=None),
        },
        "items": items,
    }
    store.write("universe.json", universe)
    log.info("Universo: %d titoli (su %d con dati)", len(items), len(metrics))
    return universe


def load_universe(store: Store) -> dict | None:
    return store.read("universe.json")


def active_items(universe: dict | None, cfg: Config) -> list[dict]:
    """Titoli da monitorare: universo meno esclusi, più eventuali inclusi a mano."""
    items = [i for i in (universe or {}).get("items", []) if i["ticker"] not in cfg.exclude]
    known = {i["ticker"] for i in items}
    for t in cfg.include:
        if t not in known and t not in cfg.exclude:
            country, currency, exchange = exchange_info(t)
            items.append({"ticker": t, "name": t, "sector": "", "country": country, "currency": currency,
                          "exchange": exchange, "forced": True})
    return items
