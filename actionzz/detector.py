"""Logica di rilevamento dei cali: pura, senza rete, facile da testare."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
from statistics import median

import pandas as pd

from .config import Config


@dataclass
class Quote:
    ticker: str
    price: float
    prev_close: float  # chiusura di ieri, corretta per l'eventuale stacco del dividendo
    pct: float  # variazione % rispetto a prev_close
    low: float
    low_pct: float
    open: float | None
    volume: float | None
    avg_volume_20d: float | None
    dividend: float  # dividendo staccato oggi (0 se nessuno)
    day: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Signal:
    quote: Quote
    relative: float | None  # pct del titolo meno pct del mercato
    previous_pct: float | None  # pct dell'ultimo avviso di oggi (None = primo avviso)

    @property
    def is_repeat(self) -> bool:
        return self.previous_pct is not None


def compute_quote(ticker: str, df: pd.DataFrame, today: date) -> Quote | None:
    """Confronta la barra di oggi con la chiusura precedente.

    Restituisce None se oggi il titolo non ha scambi (festività, sospensione)
    o se manca la chiusura precedente.
    """
    if df is None or len(df) < 2:
        return None
    df = df.dropna(subset=["Close"])
    if len(df) < 2 or df.index[-1].date() != today:
        return None
    last, prev = df.iloc[-1], df.iloc[-2]
    price, prev_close = float(last["Close"]), float(prev["Close"])
    dividend = float(last.get("Dividends", 0.0) or 0.0)
    if dividend > 0 and dividend < prev_close:
        # nel giorno di stacco il prezzo scende "meccanicamente" del dividendo
        prev_close -= dividend
    if prev_close <= 0 or price <= 0:
        return None
    low = float(last["Low"]) if pd.notna(last.get("Low")) else price
    low = min(low, price)
    volume = float(last["Volume"]) if pd.notna(last.get("Volume")) else None
    past_vol = df["Volume"].iloc[:-1].tail(20).dropna() if "Volume" in df else pd.Series(dtype=float)
    avg_vol = float(past_vol.mean()) if len(past_vol) else None
    return Quote(
        ticker=ticker,
        price=price,
        prev_close=prev_close,
        pct=(price / prev_close - 1) * 100,
        low=low,
        low_pct=(low / prev_close - 1) * 100,
        open=float(last["Open"]) if pd.notna(last.get("Open")) else None,
        volume=volume,
        avg_volume_20d=avg_vol,
        dividend=dividend,
        day=today.isoformat(),
    )


def market_move(quotes: list[Quote]) -> float | None:
    """Andamento del mercato = mediana delle variazioni dell'universo (robusta agli outlier)."""
    if not quotes:
        return None
    return float(median(q.pct for q in quotes))


def find_signals(
    quotes: list[Quote],
    market: float | None,
    cfg: Config,
    alerted: dict[str, dict],
) -> list[Signal]:
    """Titoli da segnalare ora, dal calo più forte.

    `alerted` contiene gli avvisi già inviati oggi: {ticker: {"pct": ...}}.
    Un titolo già segnalato torna a esserlo solo se scende di almeno
    `realert_step_pct` punti oltre l'ultimo avviso.
    """
    signals: list[Signal] = []
    for q in quotes:
        if q.pct > -cfg.drop_threshold_pct:
            continue
        relative = None if market is None else q.pct - market
        if cfg.market_filter and relative is not None and relative > -cfg.relative_threshold_pct:
            continue  # scende, ma in linea con il mercato
        previous = alerted.get(q.ticker)
        if previous is not None and q.pct > previous["pct"] - cfg.realert_step_pct:
            continue  # già segnalato e non è sceso abbastanza da allora
        signals.append(Signal(q, relative, previous["pct"] if previous else None))
    signals.sort(key=lambda s: s.quote.pct)
    return signals


def market_crash_due(market: float | None, cfg: Config, last_notified: float | None) -> bool:
    """True se il mercato nel suo complesso è in forte calo (e non l'abbiamo già detto)."""
    if market is None or market > -cfg.market_crash_pct:
        return False
    return last_notified is None or market <= last_notified - cfg.realert_step_pct
