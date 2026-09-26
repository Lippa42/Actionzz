from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import pytest

from actionzz.config import Config
from actionzz.state import Store
from actionzz.telegram import Telegram

TODAY = date(2026, 9, 25)  # un venerdì
ROME = ZoneInfo("Europe/Rome")


def bars(closes, end=TODAY, dividends=None, lows=None, volumes=None):
    """DataFrame giornaliero stile yfinance che termina in `end`."""
    idx = pd.bdate_range(end=end, periods=len(closes))
    df = pd.DataFrame(
        {
            "Open": closes,
            "High": closes,
            "Low": lows if lows is not None else closes,
            "Close": closes,
            "Volume": volumes if volumes is not None else [1000.0] * len(closes),
            "Dividends": dividends if dividends is not None else [0.0] * len(closes),
        },
        index=idx,
    )
    return df


class FakeTelegram(Telegram):
    def __init__(self, chat_id="42", updates=None):
        super().__init__(token="TEST", chat_id=chat_id)
        self.sent: list[str] = []
        self.photos: list[bytes] = []
        self.updates = updates or []

    def send(self, text, chat_id=None):
        self.sent.append(text)
        return True

    def send_photo(self, png, caption="", chat_id=None):
        self.photos.append(png)
        return True

    def get_updates(self, offset=0, timeout=0):
        pending = [u for u in self.updates if u["update_id"] >= offset]
        self.updates = []
        return pending


@pytest.fixture
def cfg():
    return Config(send_chart=False, send_news=False)


@pytest.fixture
def store(tmp_path):
    return Store(tmp_path / "stato")


@pytest.fixture
def now():
    return datetime(2026, 9, 25, 11, 0, tzinfo=ROME)


def make_universe(tickers):
    return {
        "generated": "2026-09-01T00:00:00+00:00",
        "stats": {"candidates": len(tickers), "with_data": len(tickers), "selected": len(tickers),
                  "vol_median": 15.0, "vol_max": 20.0, "rejected": {}},
        "items": [
            {"ticker": t, "name": f"Società {t}", "sector": "Utilities", "country": "Italia", "currency": "EUR",
             "exchange": "Borsa Italiana", "rank": i + 1, "vol": 15.0, "daily_sigma": 1.0, "max_drawdown": -20.0}
            for i, t in enumerate(tickers)
        ],
    }


def market_frames(n=30, drops=None, market_pct=0.0, seed=0):
    """n titoli che oggi si muovono intorno a market_pct, più cali specifici {ticker: pct}."""
    rng = np.random.default_rng(seed)
    drops = drops or {}
    frames = {}
    for i in range(n):
        t = f"T{i:02d}.MI"
        base = list(100 + rng.normal(0, 0.5, 21).cumsum())
        pct = drops.get(t, market_pct + rng.normal(0, 0.3))
        today = base[-1] * (1 + pct / 100)
        frames[t] = bars(base + [today])
    return frames
