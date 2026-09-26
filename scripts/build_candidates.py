"""Costruisce data/candidates.csv: l'elenco dei titoli europei candidati.

Legge da Wikipedia la composizione dei principali indici europei e converte i
ticker nel formato di Yahoo Finance. Il file risultante viene poi filtrato da
`python -m actionzz universe`, che tiene i titoli più stabili sui 5 anni.

Uso:  python scripts/build_candidates.py
"""

from __future__ import annotations

import csv
import io
import re
import sys
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "candidates.csv"
HEADERS = {"User-Agent": "Mozilla/5.0 (actionzz candidate builder)"}

# pagina Wikipedia, indice della tabella, colonna nome, colonna ticker,
# colonna settore (o None), suffisso Yahoo (None se il ticker lo contiene già)
SOURCES = [
    ("FTSE_100_Index", 6, "Company", "Ticker", 2, ".L"),
    ("FTSE_250_Index", 3, "Company", "Ticker", 2, ".L"),
    ("DAX", 4, "Company", "Ticker", "Prime Standard Sector", None),
    ("CAC_40", 4, "Company", "Ticker", "Sector", None),
    ("FTSE_MIB", 1, "Company", "Ticker", "ICB Sector", None),
    ("IBEX_35", 2, "Company", "Ticker", "Sector", None),
    ("AEX_index", 3, "Company", "Ticker", "ICB Sector", None),
    ("AMX_index", 0, "Company", "Ticker symbol", "ICB Sector", ".AS"),
    ("BEL_20", 2, "Company", "Ticker symbol", "ICB Sector", ".BR"),
    ("Swiss_Market_Index", 2, "Name", "Ticker", "Sector", ".SW"),
    ("SMI_MID", 1, "Company", "Ticker symbol", "Sector", ".SW"),
    ("OMX_Stockholm_30", 1, "Company", "Ticker", "GICS sector", None),
    ("OMX_Copenhagen_25", 0, "Company", "Ticker symbol", "ICB Sector", ".CO"),
    ("OMX_Helsinki_25", 1, "Company", "Ticker", "GICS sector", None),
    ("OBX_Index", 0, "Company", "Ticker symbol", "ICB subsector", ".OL"),
    ("PSI-20", 2, "Company", "Ticker", "Industry", ".LS"),
    ("ISEQ_20", 0, "Company", "MNEM code", None, ".IR"),
    ("EURO_STOXX_50", 3, "Name", "Ticker", "Sector", None),
    ("CAC_Next_20", 0, "Company", "Ticker symbol", "ICB Sector", ".PA"),
    ("AScX_index", 0, "Company", "Ticker symbol", "ICB Sector", ".AS"),
    # STOXX Europe 600: i ticker non hanno il suffisso di borsa, lo ricaviamo dal paese
    ("STOXX_Europe_600", 3, "Company", "Ticker", "ICB Sector", "country"),
]

COUNTRY_SUFFIX = {
    "United Kingdom": ".L", "Germany": ".DE", "France": ".PA", "Switzerland": ".SW",
    "Sweden": ".ST", "Netherlands": ".AS", "Spain": ".MC", "Italy": ".MI",
    "Belgium": ".BR", "Finland": ".HE", "Norway": ".OL", "Denmark": ".CO",
    "Austria": ".VI", "Ireland": ".IR", "Portugal": ".LS", "Poland": ".WA",
}

# Fondi, investment trust e veicoli di private equity quotati non sono "azioni
# singole" (e sembrano stabili solo perché diversificati): li escludiamo.
EXCLUDED_SECTORS = re.compile(
    r"investment trust|closed end|investment compan|collective investment|equity investments|hedge fund", re.I
)
EXCLUDED_NAMES = re.compile(
    r"investment trust|\btrust$|\bfund\b(?! management)|private equity|infrastructure investments|"
    r"public partnerships|3i infrastructure|greencoat|renewables infrastructure|\bhicl\b|\bbbgi\b|"
    r"\bmacro\b|vietnam enterprise",
    re.I,
)


def to_yahoo(raw: str, suffix: str | None) -> str | None:
    t = str(raw).strip()
    t = re.sub(r"\[.*?\]", "", t)  # note a piè di pagina
    t = t.split(":")[-1].strip()  # "Euronext Brussels: ABI" -> "ABI"
    if not t or t.lower() == "nan":
        return None
    if suffix is None:
        return t.replace(" ", "-")
    if suffix == ".L":
        t = t.rstrip(".").replace(".", "-")  # "BP." -> "BP", "BT.A" -> "BT-A"
    t = t.replace(" ", "-")  # "NOVO B" -> "NOVO-B"
    return t + suffix


def fetch(page: str) -> list[pd.DataFrame]:
    r = requests.get(f"https://en.wikipedia.org/wiki/{page}", headers=HEADERS, timeout=30)
    r.raise_for_status()
    return pd.read_html(io.StringIO(r.text))


def main() -> int:
    rows: dict[str, dict] = {}
    for page, idx, name_col, ticker_col, sector_col, suffix in SOURCES:
        try:
            table = fetch(page)[idx]
        except Exception as exc:  # una pagina rotta non deve bloccare le altre
            print(f"!! {page}: {exc}", file=sys.stderr)
            continue
        if isinstance(sector_col, int):
            sector_col = table.columns[sector_col]
        added = 0
        for _, rec in table.iterrows():
            sector = "" if sector_col is None else str(rec.get(sector_col, "") or "")
            if sector.lower() == "nan":
                sector = ""
            if EXCLUDED_SECTORS.search(sector):
                continue
            row_suffix = suffix
            if suffix == "country":
                row_suffix = COUNTRY_SUFFIX.get(str(rec.get("Country", "")))
                if row_suffix is None:
                    continue
            ticker = to_yahoo(rec[ticker_col], row_suffix)
            if not ticker or ticker in rows:
                continue
            name = re.sub(r"\s*\[.*?\]", "", str(rec[name_col])).strip()
            if EXCLUDED_NAMES.search(name):
                continue
            rows[ticker] = {"ticker": ticker, "name": name, "sector": sector.strip(), "index": page.replace("_", " ")}
            added += 1
        print(f"{page:22s} {added:4d} titoli")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=["ticker", "name", "sector", "index"])
        writer.writeheader()
        writer.writerows(sorted(rows.values(), key=lambda r: r["ticker"]))
    print(f"Totale: {len(rows)} candidati -> {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
