"""Impostazioni del monitor, lette da config/config.json.

Il file viene modificato dalla dashboard (via API GitHub) e dai comandi
Telegram; ogni chiave mancante prende il valore predefinito qui sotto.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = Path(os.environ.get("ACTIONZZ_CONFIG", ROOT / "config" / "config.json"))
DATA_DIR = Path(os.environ.get("ACTIONZZ_DATA_DIR", ROOT / "stato"))
CANDIDATES_PATH = ROOT / "data" / "candidates.csv"


@dataclass
class Config:
    # --- rilevamento dei cali ---
    drop_threshold_pct: float = 5.0  # calo minimo rispetto alla chiusura di ieri
    market_filter: bool = True  # ignora i cali che seguono solo il mercato
    relative_threshold_pct: float = 3.0  # quanto il titolo deve fare peggio del mercato
    market_crash_pct: float = 2.5  # calo mediano che fa scattare l'avviso "mercato"
    realert_step_pct: float = 2.0  # nuovo avviso se il titolo scende ancora di tanto
    max_alerts_per_scan: int = 8  # oltre, gli altri finiscono in un messaggio riassuntivo

    # --- universo dei titoli ---
    universe_size: int = 500
    lookback_years: int = 5
    min_history_years: float = 4.5
    include: list[str] = field(default_factory=list)  # ticker sempre monitorati
    exclude: list[str] = field(default_factory=list)  # ticker mai monitorati

    # --- orari (ora locale) ---
    timezone: str = "Europe/Rome"
    market_open: str = "09:00"
    market_close: str = "17:30"
    data_delay_minutes: int = 30  # i dati Yahoo per l'Europa arrivano in ritardo
    summary_time: str = "18:00"

    # --- notifiche ---
    paused: bool = False
    daily_summary: bool = True
    send_news: bool = True
    send_chart: bool = True
    scan_interval_minutes: int = 5  # usato solo dalla modalità "loop"

    @classmethod
    def from_dict(cls, data: dict) -> "Config":
        known = {f.name for f in fields(cls)}
        cfg = cls(**{k: v for k, v in data.items() if k in known})
        cfg.include = normalize_tickers(cfg.include)
        cfg.exclude = normalize_tickers(cfg.exclude)
        return cfg

    def to_dict(self) -> dict:
        return asdict(self)


def normalize_tickers(tickers) -> list[str]:
    seen: list[str] = []
    for t in tickers or []:
        t = str(t).strip().upper()
        if t and t not in seen:
            seen.append(t)
    return seen


def load_config(path: Path = CONFIG_PATH) -> Config:
    if path.exists():
        return Config.from_dict(json.loads(path.read_text(encoding="utf-8")))
    return Config()


def save_config(cfg: Config, path: Path = CONFIG_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cfg.to_dict(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
