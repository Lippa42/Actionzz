"""Testi dei messaggi Telegram, in italiano (HTML di Telegram)."""

from __future__ import annotations

import html
from datetime import datetime

from .config import Config
from .detector import Quote, Signal
from .markets import FLAGS

DISCLAIMER = "<i>Solo a scopo informativo, non è un consiglio d'investimento.</i>"
RATINGS = {
    "strong_buy": "acquisto forte", "buy": "acquisto", "hold": "mantenere",
    "underperform": "sottopesare", "sell": "vendita", "strong_sell": "vendita forte", "none": "n.d.",
}
GIORNI = ["lun", "mar", "mer", "gio", "ven", "sab", "dom"]


def esc(value) -> str:
    return html.escape(str(value), quote=False)


def fmt_num(x: float | None, decimals: int = 2) -> str:
    if x is None:
        return "n.d."
    s = f"{x:,.{decimals}f}"
    return s.replace(",", "§").replace(".", ",").replace("§", ".")


def fmt_pct(x: float | None, decimals: int = 1, sign: bool = True) -> str:
    if x is None:
        return "n.d."
    s = fmt_num(abs(x), decimals) + "%"
    if not sign:
        return s
    return ("−" if x < 0 else "+") + s


def fmt_pts(x: float | None) -> str:
    """Differenza in punti percentuali."""
    if x is None:
        return "n.d."
    return ("−" if x < 0 else "+") + fmt_num(abs(x), 1) + " pt"


def fmt_big(x: float | None) -> str:
    if x is None:
        return "n.d."
    for size, unit in ((1e12, "bln"), (1e9, "mld"), (1e6, "mln")):
        if abs(x) >= size:
            return f"{fmt_num(x / size, 1)} {unit}"
    return fmt_num(x, 0)


def fmt_day(dt: datetime) -> str:
    return f"{GIORNI[dt.weekday()]} {dt:%d/%m/%Y}"


def yahoo_url(ticker: str) -> str:
    return f"https://finance.yahoo.com/quote/{ticker}"


def _flag(meta: dict) -> str:
    return FLAGS.get(meta.get("country", ""), "🏳️")


def alert_card(
    signal: Signal,
    meta: dict,
    market: float | None,
    fundamentals: dict | None = None,
    news: list[dict] | None = None,
    extra: dict | None = None,
) -> str:
    """Scheda completa di un titolo in calo."""
    q, f, x = signal.quote, fundamentals or {}, extra or {}
    cur = meta.get("currency", "")
    name = f.get("name") or meta.get("name") or q.ticker
    title = "🔻 <b>Nuovo calo</b>" if signal.is_repeat else "🚨 <b>Calo improvviso</b>"
    lines = [
        f"{title} · {_flag(meta)} <b>{esc(name)}</b> (<code>{esc(q.ticker)}</code>)",
        f"{esc(meta.get('exchange', ''))} · {esc(f.get('sector') or meta.get('sector') or 'settore n.d.')}",
        "",
        f"💶 Prezzo: <b>{fmt_num(q.price)} {esc(cur)}</b>  (<b>{fmt_pct(q.pct)}</b>)",
        f"Chiusura di ieri: {fmt_num(q.prev_close)} {esc(cur)}"
        + (f" (rettificata per dividendo di {fmt_num(q.dividend)})" if q.dividend else ""),
        f"Minimo di oggi: {fmt_num(q.low)} ({fmt_pct(q.low_pct)})",
    ]
    if signal.is_repeat:
        lines.append(f"Ulteriore calo dall'ultimo avviso ({fmt_pct(signal.previous_pct)})")
    lines += ["", f"📊 Mercato oggi (mediana universo): {fmt_pct(market)}"]
    if signal.relative is not None:
        lines.append(f"Rispetto al mercato: <b>{fmt_pts(signal.relative)}</b>")
    sigma = meta.get("daily_sigma")
    if sigma:
        lines.append(
            f"Oscillazione tipica giornaliera: ±{fmt_num(sigma, 1)}% → oggi <b>{fmt_num(abs(q.pct) / sigma, 1)}×</b> il normale"
        )
    if q.volume and q.avg_volume_20d:
        lines.append(f"Volume: {fmt_num(q.volume / q.avg_volume_20d, 1)}× la media a 20 giorni")

    lines += ["", "🧭 <b>Contesto</b>"]
    high = f.get("high_52w") or x.get("high_52w")
    if high:
        lines.append(f"Dal massimo a 52 settimane ({fmt_num(high)}): {fmt_pct((q.price / high - 1) * 100)}")
    low52 = f.get("low_52w") or x.get("low_52w")
    if low52:
        lines.append(f"Dal minimo a 52 settimane ({fmt_num(low52)}): {fmt_pct((q.price / low52 - 1) * 100)}")
    if x.get("return_1y") is not None:
        lines.append(f"Rendimento 1 anno: {fmt_pct(x['return_1y'])}")
    if meta.get("vol") is not None:
        lines.append(
            f"Volatilità 5 anni: {fmt_num(meta['vol'], 1)}% annua"
            + (f" · Max drawdown: {fmt_pct(meta.get('max_drawdown'))}" if meta.get("max_drawdown") is not None else "")
            + (f" · Stabilità: #{meta['rank']}" if meta.get("rank") else "")
        )

    fund = []
    if f.get("pe"):
        fund.append(f"P/E {fmt_num(f['pe'], 1)}")
    if f.get("forward_pe"):
        fund.append(f"P/E atteso {fmt_num(f['forward_pe'], 1)}")
    if f.get("dividend_yield"):
        dy = f["dividend_yield"]
        fund.append(f"Dividendo {fmt_num(dy if dy > 1 else dy * 100, 1)}%")  # yfinance ha cambiato unità
    if f.get("pb"):
        fund.append(f"P/BV {fmt_num(f['pb'], 1)}")
    if f.get("market_cap"):
        fund.append(f"Capitalizzazione {fmt_big(f['market_cap'])} {esc(f.get('currency') or cur)}")
    if f.get("beta"):
        fund.append(f"Beta {fmt_num(f['beta'], 2)}")
    if fund:
        lines += ["", "🏦 " + " · ".join(fund)]
    if f.get("target_price"):
        lines.append(
            f"Prezzo obiettivo medio analisti: {fmt_num(f['target_price'])} "
            f"({fmt_pct((f['target_price'] / q.price - 1) * 100)})"
            + (f" · giudizio: {esc(RATINGS.get(f['recommendation'], f['recommendation']))}" if f.get("recommendation") not in (None, "none") else "")
        )

    if news:
        lines += ["", "📰 <b>Notizie recenti</b>"]
        for n in news:
            label = esc(n["title"])
            link = f'<a href="{esc(n["url"])}">{label}</a>' if n.get("url") else label
            lines.append(f"• {link}" + (f" <i>({esc(n['publisher'])})</i>" if n.get("publisher") else ""))

    lines += ["", f'🔗 <a href="{yahoo_url(q.ticker)}">Yahoo Finance</a>', DISCLAIMER]
    return "\n".join(lines)


def overflow_list(signals: list[Signal], metas: dict[str, dict]) -> str:
    lines = [f"➕ <b>Altri {len(signals)} titoli sotto soglia</b>"]
    for s in signals:
        m = metas.get(s.quote.ticker, {})
        lines.append(
            f"• <code>{esc(s.quote.ticker)}</code> {esc(m.get('name', ''))}: <b>{fmt_pct(s.quote.pct)}</b>"
            + (f" (vs mercato {fmt_pts(s.relative)})" if s.relative is not None else "")
        )
    lines.append("Usa /titolo TICKER per la scheda completa.")
    return "\n".join(lines)


def market_crash(market: float, quotes: list[Quote], cfg: Config) -> str:
    down = sum(1 for q in quotes if q.pct < 0)
    worst = sorted(quotes, key=lambda q: q.pct)[:5]
    lines = [
        "📉 <b>Calo generalizzato del mercato</b>",
        f"Variazione mediana dell'universo: <b>{fmt_pct(market)}</b>",
        f"Titoli in calo: {down} su {len(quotes)}",
    ]
    if cfg.market_filter:
        lines.append(
            f"Il filtro di mercato è attivo: ti avviso solo per i titoli che fanno almeno "
            f"{fmt_num(cfg.relative_threshold_pct, 1)} punti peggio del mercato."
        )
    lines.append("Peggiori: " + ", ".join(f"{esc(q.ticker)} {fmt_pct(q.pct)}" for q in worst))
    return "\n".join(lines)


def quote_line(q: dict, metas: dict[str, dict]) -> str:
    m = metas.get(q["ticker"], {})
    return f"<code>{esc(q['ticker']):<9}</code> {fmt_pct(q['pct']):>7}  {esc(m.get('name', ''))[:28]}"


def daily_summary(snapshot: dict, alerts_today: list[dict], metas: dict[str, dict], now: datetime, cfg: Config) -> str:
    quotes = snapshot.get("quotes", [])
    market = snapshot.get("market_pct")
    ups = sum(1 for q in quotes if q["pct"] > 0)
    downs = sum(1 for q in quotes if q["pct"] < 0)
    lines = [
        f"📋 <b>Riepilogo di {fmt_day(now)}</b>",
        "",
        f"📊 Mercato (mediana di {len(quotes)} titoli): <b>{fmt_pct(market)}</b>",
        f"In rialzo: {ups} · In calo: {downs}",
        "",
        f"🚨 <b>Avvisi di oggi: {len(alerts_today)}</b>",
    ]
    current = {q["ticker"]: q for q in quotes}
    seen = set()
    for a in alerts_today:
        if a["ticker"] in seen:
            continue
        seen.add(a["ticker"])
        now_pct = current.get(a["ticker"], {}).get("pct")
        lines.append(
            f"• <code>{esc(a['ticker'])}</code> {esc(a.get('name', ''))}: avviso a {fmt_pct(a['pct'])}"
            + (f" → chiusura {fmt_pct(now_pct)}" if now_pct is not None else "")
        )
    if not alerts_today:
        lines.append("Nessun calo anomalo oggi. 😌")

    ranked = sorted(quotes, key=lambda q: q["pct"])
    if ranked:
        lines += ["", "🔻 <b>I 10 peggiori</b>"] + [quote_line(q, metas) for q in ranked[:10]]
        lines += ["", "🔺 <b>I 5 migliori</b>"] + [quote_line(q, metas) for q in ranked[::-1][:5]]
        near = [q for q in ranked if -cfg.drop_threshold_pct < q["pct"] <= -cfg.drop_threshold_pct * 0.6]
        if near:
            lines += ["", f"👀 <b>Vicini alla soglia</b> (tra {fmt_pct(-cfg.drop_threshold_pct * 0.6)} e {fmt_pct(-cfg.drop_threshold_pct)})"]
            lines += [quote_line(q, metas) for q in near[:8]]
    lines += ["", DISCLAIMER]
    return "\n".join(lines)


HELP = """🤖 <b>Actionzz — comandi</b>

/stato — stato del monitor e impostazioni
/oggi [n] — i titoli peggiori di oggi (predefinito 10)
/avvisi — gli avvisi inviati oggi
/titolo TICKER — scheda completa di un titolo (es. /titolo ENEL.MI)
/cerca testo — cerca un titolo per nome
/riepilogo — riepilogo della giornata adesso
/universo — informazioni sui titoli monitorati

⚙️ <b>Impostazioni</b>
/soglia 5 — calo minimo in % rispetto a ieri
/relativa 3 — quanti punti peggio del mercato
/filtro on|off — filtro sui cali di tutto il mercato
/passo 2 — ulteriore calo per un nuovo avviso
/aggiungi TICKER — monitora sempre un titolo
/rimuovi TICKER — non monitorare un titolo
/pausa · /riprendi — sospendi o riattiva gli avvisi

ℹ️ Su GitHub Actions i comandi vengono letti a ogni esecuzione: fino a 5 minuti durante la borsa, qualche ora fuori orario."""

BOT_COMMANDS = [
    ("stato", "Stato del monitor e impostazioni"),
    ("oggi", "I titoli peggiori di oggi"),
    ("avvisi", "Avvisi inviati oggi"),
    ("titolo", "Scheda completa di un titolo"),
    ("cerca", "Cerca un titolo per nome"),
    ("riepilogo", "Riepilogo della giornata"),
    ("universo", "Titoli monitorati"),
    ("soglia", "Imposta il calo minimo in %"),
    ("relativa", "Punti peggio del mercato"),
    ("filtro", "Filtro mercato on/off"),
    ("passo", "Ulteriore calo per un nuovo avviso"),
    ("aggiungi", "Monitora sempre un titolo"),
    ("rimuovi", "Non monitorare un titolo"),
    ("pausa", "Sospendi gli avvisi"),
    ("riprendi", "Riattiva gli avvisi"),
    ("aiuto", "Elenco dei comandi"),
]
