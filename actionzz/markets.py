"""Borse europee: paese e valuta dal suffisso Yahoo, e orari di contrattazione."""

from __future__ import annotations

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from .config import Config

# suffisso Yahoo -> (paese, valuta, borsa)
EXCHANGES = {
    ".L": ("Regno Unito", "GBp", "Londra"),
    ".DE": ("Germania", "EUR", "Xetra"),
    ".PA": ("Francia", "EUR", "Euronext Parigi"),
    ".MI": ("Italia", "EUR", "Borsa Italiana"),
    ".MC": ("Spagna", "EUR", "Madrid"),
    ".AS": ("Paesi Bassi", "EUR", "Euronext Amsterdam"),
    ".BR": ("Belgio", "EUR", "Euronext Bruxelles"),
    ".LS": ("Portogallo", "EUR", "Euronext Lisbona"),
    ".IR": ("Irlanda", "EUR", "Euronext Dublino"),
    ".HE": ("Finlandia", "EUR", "Nasdaq Helsinki"),
    ".VI": ("Austria", "EUR", "Vienna"),
    ".SW": ("Svizzera", "CHF", "SIX"),
    ".ST": ("Svezia", "SEK", "Nasdaq Stoccolma"),
    ".CO": ("Danimarca", "DKK", "Nasdaq Copenaghen"),
    ".OL": ("Norvegia", "NOK", "Oslo Børs"),
    ".WA": ("Polonia", "PLN", "Varsavia"),
}

FLAGS = {
    "Regno Unito": "🇬🇧", "Germania": "🇩🇪", "Francia": "🇫🇷", "Italia": "🇮🇹", "Spagna": "🇪🇸",
    "Paesi Bassi": "🇳🇱", "Belgio": "🇧🇪", "Portogallo": "🇵🇹", "Irlanda": "🇮🇪", "Finlandia": "🇫🇮",
    "Austria": "🇦🇹", "Svizzera": "🇨🇭", "Svezia": "🇸🇪", "Danimarca": "🇩🇰", "Norvegia": "🇳🇴",
    "Polonia": "🇵🇱",
}


def exchange_info(ticker: str) -> tuple[str, str, str]:
    """(paese, valuta, borsa) di un ticker Yahoo."""
    dot = ticker.rfind(".")
    if dot > 0:
        info = EXCHANGES.get(ticker[dot:].upper())
        if info:
            return info
    return ("?", "", "?")


def _hm(value: str) -> time:
    h, m = value.split(":")
    return time(int(h), int(m))


def now_local(cfg: Config) -> datetime:
    return datetime.now(ZoneInfo(cfg.timezone))


def is_trading_window(cfg: Config, now: datetime) -> bool:
    """True nei giorni feriali dall'apertura alla chiusura più il ritardo dei dati.

    Le festività non sono in calendario: nei giorni di chiusura Yahoo non
    produce una barra con la data di oggi e il titolo viene semplicemente saltato.
    """
    if now.weekday() >= 5:
        return False
    start = now.replace(hour=_hm(cfg.market_open).hour, minute=_hm(cfg.market_open).minute, second=0, microsecond=0)
    close = _hm(cfg.market_close)
    end = now.replace(hour=close.hour, minute=close.minute, second=0, microsecond=0)
    end += timedelta(minutes=cfg.data_delay_minutes)
    return start <= now <= end


def is_summary_due(cfg: Config, now: datetime) -> bool:
    t = _hm(cfg.summary_time)
    return now.weekday() < 5 and (now.hour, now.minute) >= (t.hour, t.minute)
