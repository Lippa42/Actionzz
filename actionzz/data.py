"""Accesso ai dati di mercato tramite yfinance (Yahoo Finance, gratuito)."""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone

import pandas as pd

log = logging.getLogger(__name__)

COLUMNS = ["Open", "High", "Low", "Close", "Volume", "Dividends"]


def _yf():
    import yfinance as yf  # import ritardato: i test non ne hanno bisogno

    return yf


def download_daily(
    tickers: list[str],
    period: str = "5d",
    auto_adjust: bool = False,
    chunk_size: int = 100,
    retries: int = 2,
) -> dict[str, pd.DataFrame]:
    """Barre giornaliere per molti ticker. Restituisce {ticker: DataFrame}.

    I ticker senza dati vengono omessi. La barra di oggi, se la borsa è
    aperta, contiene l'ultimo prezzo disponibile (con il ritardo di Yahoo).
    """
    out: dict[str, pd.DataFrame] = {}
    for start in range(0, len(tickers), chunk_size):
        chunk = tickers[start : start + chunk_size]
        raw = None
        for attempt in range(retries + 1):
            try:
                raw = _yf().download(
                    chunk,
                    period=period,
                    interval="1d",
                    group_by="ticker",
                    auto_adjust=auto_adjust,
                    actions=True,
                    threads=True,
                    progress=False,
                )
                break
            except Exception as exc:  # errori di rete o rate limit di Yahoo
                log.warning("download fallito (%s), tentativo %d", exc, attempt + 1)
                time.sleep(5 * (attempt + 1))
        if raw is None or raw.empty:
            continue
        out.update(split_download(raw, chunk))
    return out


def split_download(raw: pd.DataFrame, tickers: list[str]) -> dict[str, pd.DataFrame]:
    out: dict[str, pd.DataFrame] = {}
    multi = isinstance(raw.columns, pd.MultiIndex)
    for t in tickers:
        if multi:
            if t not in raw.columns.get_level_values(0):
                continue
            df = raw[t].copy()
        elif len(tickers) == 1:
            df = raw.copy()
        else:
            continue
        df = df[[c for c in COLUMNS if c in df.columns]].dropna(subset=["Close"])
        if "Dividends" not in df.columns:
            df["Dividends"] = 0.0
        if not df.empty:
            df.index = pd.DatetimeIndex(df.index)
            out[t] = df.sort_index()
    return out


def fetch_fundamentals(ticker: str) -> dict:
    """Dati fondamentali (P/E, dividendo, capitalizzazione...). Vuoto se non disponibili."""
    try:
        info = _yf().Ticker(ticker).info or {}
    except Exception as exc:
        log.info("info non disponibili per %s: %s", ticker, exc)
        return {}
    keys = {
        "longName": "name",
        "shortName": "short_name",
        "sector": "sector",
        "industry": "industry",
        "trailingPE": "pe",
        "forwardPE": "forward_pe",
        "dividendYield": "dividend_yield",
        "marketCap": "market_cap",
        "fiftyTwoWeekHigh": "high_52w",
        "fiftyTwoWeekLow": "low_52w",
        "averageVolume": "avg_volume",
        "beta": "beta",
        "priceToBook": "pb",
        "recommendationKey": "recommendation",
        "targetMeanPrice": "target_price",
        "currency": "currency",
    }
    return {new: info[old] for old, new in keys.items() if info.get(old) is not None}


def fetch_news(ticker: str, limit: int = 3) -> list[dict]:
    """Ultime notizie del titolo: [{title, publisher, url, time}]."""
    try:
        items = _yf().Ticker(ticker).news or []
    except Exception as exc:
        log.info("notizie non disponibili per %s: %s", ticker, exc)
        return []
    return [n for n in (parse_news_item(i) for i in items) if n][:limit]


def parse_news_item(item: dict) -> dict | None:
    # yfinance ha cambiato formato: le versioni recenti annidano tutto in "content"
    content = item.get("content") or item
    title = content.get("title")
    if not title:
        return None
    provider = content.get("provider") or {}
    url = (content.get("canonicalUrl") or {}).get("url") or (content.get("clickThroughUrl") or {}).get("url")
    url = url or content.get("link")
    when = content.get("pubDate") or content.get("providerPublishTime")
    if isinstance(when, (int, float)):
        when = datetime.fromtimestamp(when, tz=timezone.utc).isoformat()
    return {
        "title": title,
        "publisher": provider.get("displayName") or content.get("publisher") or "",
        "url": url or "",
        "time": when or "",
    }
