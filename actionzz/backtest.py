"""Backtest: quanti avvisi avrebbe mandato il bot negli ultimi anni, e com'è andata dopo.

Approssimazioni (dichiarate anche nella dashboard):
- si usano barre giornaliere: un titolo "scatta" se il minimo del giorno scende
  sotto la soglia rispetto alla chiusura precedente; il prezzo d'ingresso è la
  chiusura di quel giorno (prudente: non si compra al minimo);
- prezzi rettificati per dividendi e split;
- il mercato è la mediana dell'universo, come nel monitor;
- l'universo è quello di oggi: i titoli falliti o usciti dagli indici mancano
  (distorsione di sopravvivenza, rende i risultati più ottimisti).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from . import data
from .config import Config
from .state import Store

log = logging.getLogger(__name__)

HORIZONS = (5, 20, 60)  # giorni di borsa dopo l'avviso
SWEEP = (3, 4, 5, 6, 7, 8, 10, 12)
COOLDOWN_DAYS = 5  # un solo segnale per titolo ogni 5 sedute
BREAK_JUMP = np.log(1.4)  # salti oltre ±40% in un giorno: scorpori o errori di Yahoo


def data_breaks(close: pd.DataFrame) -> pd.DataFrame:
    """Numero progressivo di "rotture" della serie (scorpori, errori di prezzo) per ogni cella.

    Due giorni con lo stesso numero sono confrontabili; un segnale o un
    rendimento che attraversa una rottura viene scartato.
    """
    jumps = np.log(close).diff().abs() > BREAK_JUMP
    return jumps.cumsum()


def signal_mask(close: pd.DataFrame, low: pd.DataFrame, threshold: float, cfg: Config) -> pd.DataFrame:
    prev = close.shift(1)
    pct_low = (low / prev - 1) * 100
    pct_close = (close / prev - 1) * 100
    market = pct_close.median(axis=1)
    mask = pct_low <= -threshold
    if cfg.market_filter:
        mask &= pct_low.sub(market, axis=0) <= -cfg.relative_threshold_pct
    brk = data_breaks(close)
    mask &= brk == brk.shift(1)  # il "calo" di oggi non è uno scorporo o un errore di dato
    return _cooldown(mask.fillna(False))


def forward_returns(close: pd.DataFrame, h: int) -> pd.DataFrame:
    brk = data_breaks(close)
    fwd = (close.shift(-h) / close - 1) * 100
    return fwd.where(brk.shift(-h) == brk)


def _cooldown(mask: pd.DataFrame) -> pd.DataFrame:
    arr = mask.to_numpy(copy=True)
    for j in range(arr.shape[1]):
        last = -COOLDOWN_DAYS - 1
        for i in np.flatnonzero(arr[:, j]):
            if i - last <= COOLDOWN_DAYS:
                arr[i, j] = False
            else:
                last = i
    return pd.DataFrame(arr, index=mask.index, columns=mask.columns)


def _stats(values: pd.Series) -> dict:
    values = values.dropna()
    if values.empty:
        return {"n": 0}
    return {
        "n": int(len(values)),
        "mean": round(float(values.mean()), 2),
        "median": round(float(values.median()), 2),
        "hit_rate": round(float((values > 0).mean()) * 100, 1),
    }


def evaluate(close: pd.DataFrame, low: pd.DataFrame, cfg: Config, threshold: float) -> dict:
    mask = signal_mask(close, low, threshold, cfg)
    pct_close = (close / close.shift(1) - 1) * 100
    market_day = pct_close.median(axis=1)
    result = {"threshold": threshold, "signals": int(mask.to_numpy().sum()), "horizons": {}}
    years = max((close.index[-1] - close.index[0]).days / 365.25, 1e-9)
    result["per_year"] = round(result["signals"] / years, 1)
    for h in HORIZONS:
        fwd = forward_returns(close, h)
        market_fwd = fwd.median(axis=1)
        excess = fwd.sub(market_fwd, axis=0)
        result["horizons"][str(h)] = {
            "return": _stats(fwd[mask].stack()),
            "excess": _stats(excess[mask].stack()),
        }
    result["_mask"] = mask
    result["_market_day"] = market_day
    return result


def run_frames(close: pd.DataFrame, low: pd.DataFrame, cfg: Config, names: dict[str, str] | None = None) -> dict:
    names = names or {}
    main = evaluate(close, low, cfg, cfg.drop_threshold_pct)
    mask = main.pop("_mask")
    market_day = main.pop("_market_day")
    sweep = []
    for th in SWEEP:
        r = evaluate(close, low, cfg, th)
        r.pop("_mask"), r.pop("_market_day")
        sweep.append({
            "threshold": th,
            "signals": r["signals"],
            "per_year": r["per_year"],
            "ret20": r["horizons"]["20"]["return"].get("mean"),
            "hit20": r["horizons"]["20"]["return"].get("hit_rate"),
            "excess20": r["horizons"]["20"]["excess"].get("mean"),
            "ret60": r["horizons"]["60"]["return"].get("mean"),
        })

    prev = close.shift(1)
    fwds = {h: forward_returns(close, h) for h in HORIZONS}
    events = []
    for day, ticker in mask.stack().loc[lambda s: s].index:
        i = close.index.get_loc(day)
        ev = {
            "day": day.date().isoformat(),
            "ticker": ticker,
            "name": names.get(ticker, ticker),
            "low_pct": round(float((low.at[day, ticker] / prev.at[day, ticker] - 1) * 100), 2),
            "close_pct": round(float((close.at[day, ticker] / prev.at[day, ticker] - 1) * 100), 2),
            "market_pct": round(float(market_day.iloc[i]), 2),
        }
        for h in HORIZONS:
            v = fwds[h].at[day, ticker]
            ev[f"ret{h}"] = round(float(v), 2) if pd.notna(v) else None
        events.append(ev)
    events.sort(key=lambda e: e["day"], reverse=True)

    by_year: dict[str, int] = {}
    for e in events:
        by_year[e["day"][:4]] = by_year.get(e["day"][:4], 0) + 1

    return {
        "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "period": {"start": close.index[0].date().isoformat(), "end": close.index[-1].date().isoformat()},
        "tickers": int(close.shape[1]),
        "params": {
            "drop_threshold_pct": cfg.drop_threshold_pct,
            "market_filter": cfg.market_filter,
            "relative_threshold_pct": cfg.relative_threshold_pct,
            "cooldown_days": COOLDOWN_DAYS,
        },
        "main": main,
        "sweep": sweep,
        "by_year": dict(sorted(by_year.items())),
        "events": events[:300],
    }


def run_backtest(cfg: Config, store: Store) -> dict:
    universe = store.read("universe.json")
    if not universe:
        raise RuntimeError("Universo non calcolato: esegui prima `python -m actionzz universe`")
    names = {i["ticker"]: i["name"] for i in universe["items"]}
    frames = data.download_daily(list(names), period=f"{cfg.lookback_years}y", auto_adjust=True)
    close = pd.DataFrame({t: df["Close"] for t, df in frames.items()}).sort_index()
    low = pd.DataFrame({t: df["Low"] for t, df in frames.items()}).sort_index()
    # le borse hanno calendari diversi: le celle mancanti restano NaN e non generano segnali
    result = run_frames(close, low, cfg, names)
    store.write("backtest.json", result)
    log.info("Backtest: %d segnali in %s anni", result["main"]["signals"], cfg.lookback_years)
    return result
