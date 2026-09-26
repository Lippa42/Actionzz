"""Stato tra un'esecuzione e l'altra.

Su GitHub Actions ogni esecuzione parte da zero, quindi il poco stato
necessario (avvisi già inviati oggi, ultimo messaggio Telegram letto...) vive
in file JSON nella cartella dati, pubblicata sul branch `data`. Gli stessi
file alimentano la dashboard.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

MAX_ALERT_HISTORY = 1000


class Store:
    """Lettura/scrittura dei file JSON nella cartella dati."""

    def __init__(self, directory: Path):
        self.dir = Path(directory)
        self.dir.mkdir(parents=True, exist_ok=True)

    def read(self, name: str, default=None):
        path = self.dir / name
        if not path.exists():
            return default
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return default

    def write(self, name: str, data) -> None:
        tmp = self.dir / (name + ".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
        tmp.replace(self.dir / name)

    def append_alerts(self, records: list[dict]) -> None:
        if not records:
            return
        history = self.read("alerts.json", [])
        history.extend(records)
        self.write("alerts.json", history[-MAX_ALERT_HISTORY:])


class State:
    """Stato giornaliero; si azzera da solo quando cambia la data."""

    FILE = "state.json"

    def __init__(self, store: Store):
        self.store = store
        data = store.read(self.FILE, {}) or {}
        self.day: str = data.get("day", "")
        self.alerts: dict[str, dict] = data.get("alerts", {})
        self.market_alert_pct: float | None = data.get("market_alert_pct")
        self.summary_sent: bool = data.get("summary_sent", False)
        self.scans_today: int = data.get("scans_today", 0)
        self.last_scan: str | None = data.get("last_scan")
        self.telegram_offset: int = data.get("telegram_offset", 0)

    def roll_day(self, today: date) -> None:
        if self.day != today.isoformat():
            self.day = today.isoformat()
            self.alerts = {}
            self.market_alert_pct = None
            self.summary_sent = False
            self.scans_today = 0

    def to_dict(self) -> dict:
        return {
            "day": self.day,
            "alerts": self.alerts,
            "market_alert_pct": self.market_alert_pct,
            "summary_sent": self.summary_sent,
            "scans_today": self.scans_today,
            "last_scan": self.last_scan,
            "telegram_offset": self.telegram_offset,
        }

    def save(self) -> None:
        self.store.write(self.FILE, self.to_dict())
