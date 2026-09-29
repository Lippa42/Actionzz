"""Manutenzione periodica eseguita dalla sessione continua a borsa chiusa.

Il ricalcolo mensile vive qui e non in un workflow separato: la sessione possiede il branch `data`
(lo ripubblica a ogni giro), quindi un altro job che lo scrivesse verrebbe sovrascritto.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from .config import Config
from .markets import is_trading_window, now_local
from .state import Store

log = logging.getLogger(__name__)
MAX_AGE = timedelta(days=30)


def _age(doc: dict | None) -> timedelta:
    if not doc or not doc.get("generated"):
        return timedelta.max
    return datetime.now(timezone.utc) - datetime.fromisoformat(doc["generated"])


def run_maintenance(cfg: Config, store: Store, now: datetime | None = None) -> list[str]:
    now = now or now_local(cfg)
    if is_trading_window(cfg, now):
        return []  # durante la borsa conta il controllo ogni 5 minuti
    done = []
    if _age(store.read("universe.json")) > MAX_AGE:
        from .universe import build_universe

        build_universe(cfg, store)
        done.append("universo")
    if "universo" in done or _age(store.read("backtest.json")) > MAX_AGE:
        from .backtest import run_backtest

        run_backtest(cfg, store)
        done.append("backtest")
    if "universo" in done or _age(store.read("strategies.json")) > MAX_AGE:
        from .strategies import run_strategies

        run_strategies(cfg, store)
        done.append("strategie")
    if done:
        log.info("Manutenzione eseguita: %s", ", ".join(done))
    return done
