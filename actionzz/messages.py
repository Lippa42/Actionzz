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
/portafoglio [TICKER] — il tuo portafoglio e i segnali di vendita

💼 <b>Portafoglio</b>
/compra TICKER QUANTITÀ PREZZO [commissioni] — registra un acquisto e ricevi il piano di vendita (es. /compra ENEL.MI 100 6,50)
/vendi TICKER QUANTITÀ PREZZO [commissioni] — registra una vendita
/piano TICKER — quando vendere un titolo che possiedi
/obiettivo 20 · /stop 10 — cambia obiettivo di guadagno e stop di perdita (%)

🧪 <b>Simulatore</b> (soldi finti, costi e tasse veri)
/sim — stato del conto simulato
/simcompra TICKER QUANTITÀ [limite] — es. /simcompra ENEL.MI 100 oppure /simcompra ENEL.MI 1000€
/simvendi TICKER QUANTITÀ|tutto [limite]
/simversa 1000 — aggiungi denaro al budget
/simnuovo 10000 — ricomincia da zero con un nuovo budget
/simbroker [ID] — confronta i broker e scegli le tariffe da simulare

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
    ("portafoglio", "Il tuo portafoglio e i segnali di vendita"),
    ("compra", "Registra un acquisto: TICKER QUANTITÀ PREZZO"),
    ("vendi", "Registra una vendita: TICKER QUANTITÀ PREZZO"),
    ("piano", "Quando vendere un titolo che possiedi"),
    ("sim", "Simulatore: stato del conto"),
    ("simcompra", "Simulatore: compra TICKER QUANTITÀ"),
    ("simvendi", "Simulatore: vendi TICKER QUANTITÀ|tutto"),
    ("simversa", "Simulatore: aggiungi budget"),
    ("simbroker", "Simulatore: scegli il broker"),
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


# ------------------------------------------------------------------ portafoglio

LEVEL_ICON = {"strong": "🔴", "warn": "🟠", "info": "🔵", "hold": "🟢"}


def fmt_eur(x: float | None, decimals: int = 0) -> str:
    if x is None:
        return "n.d."
    return ("−" if x < 0 else "") + fmt_num(abs(x), decimals) + " €"


def fmt_eur_signed(x: float | None, decimals: int = 0) -> str:
    if x is None:
        return "n.d."
    return ("−" if x < 0 else "+") + fmt_num(abs(x), decimals) + " €"


def holding_card(r: dict, tax_rate_pct: float, title: str = "💼 <b>Portafoglio · segnali di vendita</b>") -> str:
    cur = r.get("currency", "")
    net = r["pnl_eur"] - max(r["pnl_eur"], 0) * tax_rate_pct / 100 if r.get("pnl_eur") is not None else None
    lines = [
        title,
        f"<b>{esc(r['name'])}</b> (<code>{esc(r['ticker'])}</code>)",
        f"Valutazione: <b>{r['verdict']['label']}</b>",
        "",
        f"Prezzo {fmt_num(r['price'])} {esc(cur)}"
        + (f" ({fmt_pct(r['day_pct'])} oggi)" if r.get("day_pct") is not None else ""),
        f"Tuo prezzo medio {fmt_num(r['avg_price'])} · {fmt_num(r['quantity'], 0 if float(r['quantity']).is_integer() else 3)} azioni",
        f"Risultato: <b>{fmt_pct(r['pnl_pct'])}</b> ({fmt_eur_signed(r.get('pnl_eur'))}"
        + (f", netto tasse ≈ {fmt_eur_signed(net)}" if net is not None else "") + ")",
    ]
    if r.get("signals"):
        lines += ["", "<b>Segnali</b>"] + [f"{LEVEL_ICON[s['level']]} {esc(s['text'])}" for s in r["signals"]]
    if r.get("holds"):
        lines += ["", "<b>Motivi per aspettare</b>"] + [f"{LEVEL_ICON['hold']} {esc(h['text'])}" for h in r["holds"]]
    lines += ["", f'🔗 <a href="{yahoo_url(r["ticker"])}">Yahoo Finance</a>',
              "<i>Segnali tecnici automatici, non un consiglio d'investimento: la decisione è tua.</i>"]
    return "\n".join(lines)


def portfolio_overview(report: dict) -> str:
    t = report["totals"]
    lines = [
        "💼 <b>Il tuo portafoglio</b>",
        f"Valore: <b>{fmt_eur(t['value_eur'])}</b> · investito {fmt_eur(t['cost_eur'])}",
        f"Risultato: <b>{fmt_eur_signed(t['pnl_eur'])}</b> ({fmt_pct(t['pnl_pct'])}) · netto tasse ≈ {fmt_eur_signed(t['net_pnl_eur'])}",
    ]
    if t.get("day_pnl_eur") is not None:
        lines.append(f"Oggi: {fmt_eur_signed(t['day_pnl_eur'])}")
    lines.append("")
    order = {"vendi": 0, "valuta": 1, "mantieni": 2}
    for r in sorted(report["holdings"], key=lambda r: (order[r["verdict"]["code"]], -(r["value_eur"] or 0))):
        icon = r["verdict"]["label"].split()[0]
        lines.append(
            f"{icon} <code>{esc(r['ticker'])}</code> {esc(r['name'])[:24]}: {fmt_pct(r['pnl_pct'])}"
            + (f" · {fmt_eur(r['value_eur'])}" if r.get("value_eur") is not None else "")
        )
    if report.get("missing"):
        lines += ["", "Senza dati: " + esc(", ".join(report["missing"]))]
    lines += ["", "🔴 vendere almeno in parte · 🟠 da tenere d'occhio · 🟢 nessun segnale",
              "Dettagli: /portafoglio TICKER"]
    return "\n".join(lines)


def sell_plan_text(plan: dict, title: str = "📌 <b>Piano di vendita</b>") -> str:
    """Quando vendere: livelli di prezzo concreti per una posizione."""
    cur = esc(plan["currency"])
    s = plan["settings"]
    q = plan["quantity"]
    lines = [
        f"{title} · <b>{esc(plan['name'])}</b> (<code>{esc(plan['ticker'])}</code>)",
        f"Hai {fmt_num(q, 0 if float(q).is_integer() else 3)} azioni a {fmt_num(plan['avg_price'])} {cur} di media"
        " (commissioni incluse).",
        f"Prezzo attuale {fmt_num(plan['price'])} {cur} → {fmt_pct(plan['pnl_pct'])}",
        "",
        "<b>Quando vendere</b>",
        f"🎯 <b>Sopra {fmt_num(plan['take_profit_price'])} {cur}</b> (+{fmt_num(s['take_profit_pct'], 0)}%): obiettivo di guadagno,"
        " vendi almeno una parte e lascia correre il resto.",
        f"🛑 <b>Sotto {fmt_num(plan['stop_loss_price'])} {cur}</b> (−{fmt_num(s['stop_loss_pct'], 0)}%): stop di perdita,"
        " valuta di uscire invece di sperare nel recupero.",
    ]
    if plan["trailing_active"]:
        lines.append(
            f"📉 <b>Sotto {fmt_num(plan['trailing_price'])} {cur}</b>: −{fmt_num(s['trailing_stop_pct'], 0)}% dal massimo"
            f" ({fmt_num(plan['peak'])}) toccato da quando lo possiedi, proteggi il guadagno."
        )
    else:
        lines.append(
            f"📉 Quando sarai in guadagno: se scende del {fmt_num(s['trailing_stop_pct'], 0)}% dal massimo raggiunto"
            " ti avviso per proteggere il guadagno."
        )
    extra = ["RSI oltre 70 (ipercomprato)"]
    if plan.get("sma200"):
        extra.append(f"prezzo oltre {fmt_num(plan['sma200'] * 1.25)} (25% sopra la media a 200 giorni)")
    if plan.get("target_price"):
        extra.append(f"prezzo obiettivo degli analisti {fmt_num(plan['target_price'])} {cur}")
    lines.append("➕ Ti segnalo anche: " + ", ".join(extra) + ".")

    move = plan.get("year_move_pct")
    if move:
        tp = s["take_profit_pct"]
        judgement = (
            "raggiungibile in un anno normale" if tp <= move
            else "ambizioso ma possibile" if tp <= 2 * move
            else "molto ambizioso per questo titolo: valuta un obiettivo più basso con /obiettivo"
        )
        lines += ["", f"📏 Questo titolo in un anno oscilla tipicamente di ±{fmt_num(move, 0)}%: l'obiettivo del +{fmt_num(tp, 0)}% è {judgement}."]

    v = plan["verdict"]
    lines += ["", f"<b>Oggi</b>: {v['label']}"]
    lines += [f"{LEVEL_ICON[x['level']]} {esc(x['text'])}" for x in plan["signals"] + plan["holds"]]
    lines += [
        "",
        "🔔 Ti scrivo io quando scatta uno di questi livelli: controllo ogni 5 minuti in orario di borsa.",
        "<i>Regole automatiche, non un consiglio d'investimento: la decisione è tua.</i>",
    ]
    return "\n".join(lines)


# ------------------------------------------------------------------ simulatore


def sim_event(e: dict) -> str:
    t = e.get("type")
    head = "🧪 <b>Simulatore</b> · "
    if t == "buy":
        costs = [f"commissione {fmt_eur(e['commission'], 2)}"]
        if e.get("transaction_tax"):
            costs.append(f"{esc(e['tax_name'])} {fmt_eur(e['transaction_tax'], 2)}")
        if e.get("fx_cost"):
            costs.append(f"cambio {fmt_eur(e['fx_cost'], 2)}")
        return (f"{head}comprate {fmt_num(e['qty'], 0)} <code>{esc(e['ticker'])}</code> a {fmt_num(e['price'])} {esc(e['currency'])}\n"
                f"Controvalore {fmt_eur(e['gross'], 2)} · {' · '.join(costs)}\n"
                f"Totale addebitato <b>{fmt_eur(-e['total'], 2)}</b> · liquidità {fmt_eur(e['cash_after'], 2)}")
    if t == "sell":
        lines = [f"{head}vendute {fmt_num(e['qty'], 0)} <code>{esc(e['ticker'])}</code> a {fmt_num(e['price'])} {esc(e['currency'])}",
                 f"Controvalore {fmt_eur(e['gross'], 2)} · commissione {fmt_eur(e['commission'], 2)}"
                 + (f" · cambio {fmt_eur(e['fx_cost'], 2)}" if e.get("fx_cost") else ""),
                 f"{'Plusvalenza' if e['gain'] >= 0 else 'Minusvalenza'}: <b>{fmt_eur_signed(e['gain'], 2)}</b>"]
        if e.get("losses_used"):
            lines.append(f"Compensata con lo zainetto fiscale: {fmt_eur(e['losses_used'], 2)}")
        if e.get("capital_gains_tax"):
            lines.append(f"Tasse sulla plusvalenza (26%): {fmt_eur(e['capital_gains_tax'], 2)}"
                         + ("" if e.get("tax_withheld", True) else " · regime dichiarativo: da pagare con la dichiarazione dei redditi"))
        elif e["gain"] < 0:
            lines.append("La minusvalenza va nello zainetto fiscale: compenserà plusvalenze future (4 anni).")
        lines.append(f"Accreditati <b>{fmt_eur(e['total'], 2)}</b> · liquidità {fmt_eur(e['cash_after'], 2)}")
        return "\n".join(lines)
    if t == "dividend":
        return (f"{head}dividendo di <code>{esc(e['ticker'])}</code>: {fmt_num(e['per_share'], 4)} × {fmt_num(e['qty'], 0)} azioni\n"
                f"Lordo {fmt_eur(e['gross'], 2)} · ritenuta estera {fmt_eur(e['withholding'], 2)} · tasse italiane {fmt_eur(e['italian_tax'], 2)}\n"
                f"Netto accreditato <b>{fmt_eur(e['total'], 2)}</b>")
    if t == "rejected":
        return f"{head}⚠️ ordine su <code>{esc(e['ticker'])}</code> rifiutato: {esc(e['reason'])}."
    if t == "expired":
        return f"{head}⌛ ordine su <code>{esc(e['ticker'])}</code> scaduto senza essere eseguito (prezzo limite non raggiunto?)."
    return head + esc(t)


def sim_overview(state: dict, pending: int = 0) -> str:
    t = state["totals"]
    lines = [
        "🧪 <b>Simulatore</b>",
        f"Valore del conto: <b>{fmt_eur(t['equity'])}</b> · versati {fmt_eur(t['deposited'])}",
        f"Risultato: <b>{fmt_eur_signed(t['pnl'])}</b> ({fmt_pct(t['pnl_pct'])})",
        f"Se vendessi tutto oggi, al netto di costi e tasse: {fmt_eur(t['net_equity'])} ({fmt_pct(t['net_pnl_pct'])})",
        f"Liquidità: {fmt_eur(t['cash'], 2)} · costi e tasse pagati: {fmt_eur(t['total_costs'], 2)}",
    ]
    if t.get("losses_available"):
        lines.append(f"Zainetto fiscale: {fmt_eur(t['losses_available'], 2)} di minusvalenze da compensare")
    if state["positions"]:
        lines.append("")
        for tk, pos in sorted(state["positions"].items()):
            p = state["prices"].get(tk)
            if not p:
                continue
            value = pos["qty"] * p["price"] * p["fx"]
            lines.append(f"<code>{esc(tk)}</code> {fmt_num(pos['qty'], 0)} az. · {fmt_eur(value)} · "
                         f"{fmt_pct((value / pos['cost_eur'] - 1) * 100 if pos['cost_eur'] else None)}")
    if pending:
        lines += ["", f"⏳ Ordini in attesa: {pending}"]
    lines += ["", "Comandi: /simcompra, /simvendi, /simversa"]
    return "\n".join(lines)
