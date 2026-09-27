"""Comandi Telegram (/stato, /soglia, /titolo...)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .config import normalize_tickers
from .markets import is_trading_window, now_local
from .messages import HELP, esc, fmt_num, fmt_pct, quote_line

if TYPE_CHECKING:
    from .monitor import Monitor


def parse(text: str) -> tuple[str, list[str]]:
    parts = text.strip().split()
    cmd = parts[0].lstrip("/").split("@")[0].lower()
    return cmd, parts[1:]


def _number(args: list[str], low: float, high: float) -> float | None:
    if not args:
        return None
    try:
        value = float(args[0].replace(",", ".").rstrip("%"))
    except ValueError:
        return None
    return value if low <= value <= high else None


def handle_command(m: "Monitor", text: str) -> None:
    cmd, args = parse(text)
    handler = COMMANDS.get(cmd)
    if handler is None:
        m.tg.send(f"Comando sconosciuto: /{esc(cmd)}\n\n{HELP}")
        return
    handler(m, args)


def cmd_help(m, args):
    m.tg.send(HELP)


def cmd_status(m, args):
    cfg, st = m.cfg, m.state
    now = now_local(cfg)
    universe = m.store.read("universe.json") or {}
    open_ = is_trading_window(cfg, now)
    lines = [
        "🤖 <b>Stato di Actionzz</b>",
        f"Borsa: {'🟢 aperta' if open_ else '🔴 chiusa'} ({now:%H:%M})",
        f"Avvisi: {'⏸ in pausa' if cfg.paused else '▶️ attivi'}",
        f"Ultima scansione: {esc(st.last_scan or 'mai')} · oggi {st.scans_today}",
        f"Titoli monitorati: {len(m.metas())} (universo del {esc((universe.get('generated') or 'n.d.')[:10])})",
        f"Avvisi inviati oggi: {len(st.alerts)}",
        "",
        "⚙️ <b>Impostazioni</b>",
        f"Soglia di calo: {fmt_pct(-cfg.drop_threshold_pct)} rispetto a ieri",
        f"Filtro mercato: {'attivo' if cfg.market_filter else 'spento'}"
        + (f" (almeno {fmt_num(cfg.relative_threshold_pct, 1)} pt peggio del mercato)" if cfg.market_filter else ""),
        f"Nuovo avviso se scende di altri {fmt_num(cfg.realert_step_pct, 1)} pt",
        f"Avviso mercato: calo mediano oltre {fmt_pct(-cfg.market_crash_pct)}",
        f"Orari: {cfg.market_open}–{cfg.market_close} ({esc(cfg.timezone)}), riepilogo alle {cfg.summary_time}",
    ]
    if cfg.include:
        lines.append("Sempre inclusi: " + esc(", ".join(cfg.include)))
    if cfg.exclude:
        lines.append("Esclusi: " + esc(", ".join(cfg.exclude)))
    m.tg.send("\n".join(lines))


def cmd_today(m, args):
    n = int(_number(args, 1, 50) or 10)
    snap = m.store.read("snapshot.json")
    if not snap:
        m.tg.send("Nessuna scansione disponibile.")
        return
    metas = m.metas()
    lines = [
        f"🔻 <b>I {n} peggiori</b> · {esc(snap['time'][:16].replace('T', ' '))}",
        f"Mercato: {fmt_pct(snap['market_pct'])}",
        "",
    ] + [quote_line(q, metas) for q in snap["quotes"][:n]]
    m.tg.send("\n".join(lines))


def cmd_alerts(m, args):
    today = m.state.day
    alerts = [a for a in m.store.read("alerts.json", []) if a["day"] == today]
    if not alerts:
        m.tg.send("Nessun avviso oggi.")
        return
    lines = [f"🚨 <b>Avvisi di oggi ({len(alerts)})</b>"]
    for a in alerts:
        lines.append(f"{a['time'][11:16]} <code>{esc(a['ticker'])}</code> {esc(a['name'])}: {fmt_pct(a['pct'])}")
    m.tg.send("\n".join(lines))


def cmd_ticker(m, args):
    if not args:
        m.tg.send("Uso: /titolo TICKER (es. /titolo ENEL.MI). Usa /cerca per trovarlo.")
        return
    ticker = args[0].upper()
    m.tg.send(f"⏳ Recupero i dati di {esc(ticker)}...")
    text, png = m.ticker_card(ticker)
    if text is None:
        m.tg.send(f"Nessun dato per <code>{esc(ticker)}</code>. Controlla il ticker con /cerca.")
        return
    m.tg.send(text)
    if png:
        m.tg.send_photo(png, caption=ticker)


def cmd_search(m, args):
    query = " ".join(args).lower()
    if len(query) < 2:
        m.tg.send("Uso: /cerca nome (es. /cerca nestle)")
        return
    from .universe import load_candidates

    pool = {**{t: c.get("name", "") for t, c in load_candidates().items()},
            **{t: i.get("name", "") for t, i in m.metas().items()}}
    hits = [(t, n) for t, n in pool.items() if query in n.lower() or query in t.lower()][:15]
    if not hits:
        m.tg.send("Nessun risultato.")
        return
    metas = m.metas()
    m.tg.send("\n".join(
        f"<code>{esc(t)}</code> {esc(n)}" + (" ✅" if t in metas else "") for t, n in hits
    ) + "\n\n✅ = monitorato")


def cmd_portfolio(m, args):
    from .messages import holding_card, portfolio_overview

    if not m.portfolio_password:
        m.tg.send("Portafoglio non configurato: imposta il secret PORTFOLIO_PASSWORD (la stessa password della dashboard).")
        return
    report = m.portfolio_report()
    if not report or not report.get("holdings"):
        m.tg.send("Il portafoglio è vuoto o non ancora calcolato. Aggiungi i tuoi acquisti dalla dashboard.")
        return
    if args:
        row = next((r for r in report["holdings"] if r["ticker"] == args[0].upper()), None)
        if row is None:
            m.tg.send(f"<code>{esc(args[0].upper())}</code> non è nel tuo portafoglio.")
            return
        m.tg.send(holding_card(row, report["settings"]["tax_rate_pct"], title="💼 <b>Portafoglio</b>"))
        return
    m.tg.send(portfolio_overview(report))


def cmd_summary(m, args):
    m.send_summary(now_local(m.cfg))


def cmd_universe(m, args):
    u = m.store.read("universe.json")
    if not u:
        m.tg.send("Universo non ancora calcolato.")
        return
    s = u["stats"]
    items = u["items"]
    countries: dict[str, int] = {}
    for i in items:
        countries[i["country"]] = countries.get(i["country"], 0) + 1
    top = sorted(countries.items(), key=lambda kv: -kv[1])
    lines = [
        "🌍 <b>Universo monitorato</b>",
        f"Calcolato il {'/'.join(reversed(u['generated'][:10].split('-')))} su {s['candidates']} candidati ({s['with_data']} con dati)",
        f"Titoli scelti: {s['selected']} · volatilità mediana {fmt_num(s['vol_median'], 1)}% · massima {fmt_num(s['vol_max'], 1)}%",
        "",
        "Per paese: " + ", ".join(f"{esc(c)} {n}" for c, n in top),
        "",
        "I 10 più stabili: " + ", ".join(esc(i["ticker"]) for i in items[:10]),
    ]
    m.tg.send("\n".join(lines))


def _setting(field: str, label: str, low: float, high: float):
    def run(m, args):
        value = _number(args, low, high)
        if value is None:
            m.tg.send(f"Uso: /{field_cmd[field]} numero tra {fmt_num(low, 1)} e {fmt_num(high, 1)}. "
                      f"Valore attuale: {fmt_num(getattr(m.cfg, field), 1)}")
            return
        m.update_config(**{field: value})
        m.tg.send(f"✅ {label}: <b>{fmt_num(value, 1)}</b>")
    return run


field_cmd = {"drop_threshold_pct": "soglia", "relative_threshold_pct": "relativa", "realert_step_pct": "passo"}


def cmd_filter(m, args):
    if not args or args[0].lower() not in ("on", "off", "si", "sì", "no"):
        m.tg.send(f"Uso: /filtro on|off. Ora è {'attivo' if m.cfg.market_filter else 'spento'}.")
        return
    on = args[0].lower() in ("on", "si", "sì")
    m.update_config(market_filter=on)
    m.tg.send(f"✅ Filtro mercato {'attivato' if on else 'disattivato'}.")


def cmd_add(m, args):
    tickers = normalize_tickers(args)
    if not tickers:
        m.tg.send("Uso: /aggiungi TICKER [TICKER...]")
        return
    m.update_config(
        include=normalize_tickers(m.cfg.include + tickers),
        exclude=[t for t in m.cfg.exclude if t not in tickers],
    )
    m.tg.send("✅ Monitorati sempre: " + esc(", ".join(tickers)))


def cmd_remove(m, args):
    tickers = normalize_tickers(args)
    if not tickers:
        m.tg.send("Uso: /rimuovi TICKER [TICKER...]")
        return
    m.update_config(
        exclude=normalize_tickers(m.cfg.exclude + tickers),
        include=[t for t in m.cfg.include if t not in tickers],
    )
    m.tg.send("✅ Non più monitorati: " + esc(", ".join(tickers)))


def cmd_pause(m, args):
    m.update_config(paused=True)
    m.tg.send("⏸ Avvisi in pausa. Usa /riprendi per riattivarli.")


def cmd_resume(m, args):
    m.update_config(paused=False)
    m.tg.send("▶️ Avvisi riattivati.")


COMMANDS = {
    "start": cmd_help,
    "aiuto": cmd_help,
    "help": cmd_help,
    "stato": cmd_status,
    "oggi": cmd_today,
    "avvisi": cmd_alerts,
    "titolo": cmd_ticker,
    "cerca": cmd_search,
    "riepilogo": cmd_summary,
    "universo": cmd_universe,
    "portafoglio": cmd_portfolio,
    "soglia": _setting("drop_threshold_pct", "Soglia di calo (%)", 0.5, 50),
    "relativa": _setting("relative_threshold_pct", "Punti peggio del mercato", 0, 50),
    "passo": _setting("realert_step_pct", "Ulteriore calo per un nuovo avviso (pt)", 0.1, 50),
    "filtro": cmd_filter,
    "aggiungi": cmd_add,
    "rimuovi": cmd_remove,
    "pausa": cmd_pause,
    "riprendi": cmd_resume,
}
