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


def _amount(text: str) -> float | None:
    """Numero scritto all'italiana o all'inglese: 6,50 · 6.50 · 1.250,5."""
    t = text.strip().replace("€", "")
    if "," in t and "." in t:
        t = t.replace(".", "").replace(",", ".")
    else:
        t = t.replace(",", ".")
    try:
        v = float(t)
    except ValueError:
        return None
    return v if v >= 0 else None


def _trade_args(args: list[str]):
    if len(args) < 3:
        return None
    qty, price = _amount(args[1]), _amount(args[2])
    fees = _amount(args[3]) if len(args) > 3 else 0.0
    if not qty or not price or fees is None:
        return None
    return args[0].upper(), qty, price, fees


def _plan_for(m, pf: dict, ticker: str, history=None):
    from .portfolio import aggregate, sell_plan

    h = aggregate(pf["positions"]).get(ticker)
    if h is None:
        return None
    if history is None:
        history = m.download([ticker], period="2y").get(ticker)
    if history is None or history.empty:
        return None
    return sell_plan(h, history, m.fundamentals(ticker), pf["settings"], m.cfg)


def cmd_buy(m, args):
    from .messages import sell_plan_text
    from .portfolio import add_purchase

    parsed = _trade_args(args)
    if not parsed:
        m.tg.send("Uso: /compra TICKER QUANTITÀ PREZZO [commissioni]\nes. <code>/compra ENEL.MI 100 6,50 5</code>\n"
                  "Il prezzo è nella valuta di quotazione su Yahoo (Londra in pence).")
        return
    ticker, qty, price, fees = parsed
    try:
        pf = m.portfolio_for_edit()
    except ValueError as exc:
        m.tg.send(f"⚠️ Non posso registrare l'acquisto: {esc(exc)}.")
        return
    history = m.download([ticker], period="2y").get(ticker)
    if history is None or history.empty:
        m.tg.send(f"Non trovo dati per <code>{esc(ticker)}</code>: controlla il ticker con /cerca.")
        return
    name = (m.metas().get(ticker) or {}).get("name") or ticker
    add_purchase(pf, ticker, qty, price, fees, now_local(m.cfg).date().isoformat(), name)
    m.save_portfolio(pf)
    current = float(history["Close"].dropna().iloc[-1])
    lines = [f"✅ Acquisto registrato: {fmt_num(qty, 0 if qty.is_integer() else 3)} <code>{esc(ticker)}</code> a {fmt_num(price)}."]
    if abs(price / current - 1) > 0.3:
        lines.append(f"⚠️ Il prezzo indicato è molto diverso da quello attuale ({fmt_num(current)}): controlla la valuta "
                     "(per Londra i prezzi sono in pence). Puoi correggerlo dalla dashboard.")
    m.tg.send("\n".join(lines))
    plan = _plan_for(m, pf, ticker, history)
    if plan:
        m.tg.send(sell_plan_text(plan))
        m.just_planned.add(ticker)


def cmd_sell(m, args):
    from .portfolio import currency_of, fx_to_eur, record_sale

    parsed = _trade_args(args)
    if not parsed:
        m.tg.send("Uso: /vendi TICKER QUANTITÀ PREZZO [commissioni]\nes. <code>/vendi ENEL.MI 50 7,20</code>")
        return
    ticker, qty, price, fees = parsed
    try:
        pf = m.portfolio_for_edit()
    except ValueError as exc:
        m.tg.send(f"⚠️ Non posso registrare la vendita: {esc(exc)}.")
        return
    cur = currency_of(ticker, m.fundamentals(ticker))
    fx = fx_to_eur({cur}, m.download).get(cur)
    try:
        sale = record_sale(pf, ticker, qty, price, fees, now_local(m.cfg).date().isoformat(), cur, fx)
    except ValueError as exc:
        m.tg.send(f"⚠️ {esc(exc)} di <code>{esc(ticker)}</code>.")
        return
    m.save_portfolio(pf)
    gain = sale["realized"]
    left = sum(float(p["quantity"]) for p in pf["positions"] if p["ticker"] == ticker)
    m.tg.send(
        f"✅ Vendita registrata: {fmt_num(qty, 0 if qty.is_integer() else 3)} <code>{esc(ticker)}</code> a {fmt_num(price)} {esc(cur)}.\n"
        f"{'Plusvalenza' if gain >= 0 else 'Minusvalenza'}: <b>{fmt_num(gain)} {esc(cur)}</b>"
        + (f" (≈ {fmt_num(sale['realized_eur'], 0)} €)" if sale.get("realized_eur") is not None and cur != "EUR" else "")
        + (f"\nTe ne restano {fmt_num(left, 0 if float(left).is_integer() else 3)}: /piano {esc(ticker)}" if left else "\nPosizione chiusa.")
    )


def cmd_plan(m, args):
    from .messages import sell_plan_text

    if not args:
        m.tg.send("Uso: /piano TICKER (es. /piano ENEL.MI)")
        return
    try:
        pf = m.portfolio_for_edit()
    except ValueError as exc:
        m.tg.send(f"⚠️ {esc(exc)}.")
        return
    plan = _plan_for(m, pf, args[0].upper())
    if plan is None:
        m.tg.send(f"<code>{esc(args[0].upper())}</code> non è nel tuo portafoglio (o non ci sono dati). Registralo con /compra.")
        return
    m.tg.send(sell_plan_text(plan))


def _pf_setting(key: str, label: str):
    def run(m, args):
        value = _amount(args[0]) if args else None
        if value is None or not 1 <= value <= 500:
            m.tg.send(f"Uso: /{'obiettivo' if key == 'take_profit_pct' else 'stop'} numero (es. 20)")
            return
        try:
            pf = m.portfolio_for_edit()
        except ValueError as exc:
            m.tg.send(f"⚠️ {esc(exc)}.")
            return
        pf["settings"][key] = value
        m.save_portfolio(pf)
        m.tg.send(f"✅ {label}: <b>{fmt_num(value, 0 if value.is_integer() else 1)}%</b> per tutti i titoli del portafoglio.")
    return run


def _new_order(m, ticker: str, side: str) -> dict:
    """Ordine valido per la seduta di oggi, o per la prossima se la borsa ha già chiuso."""
    import os
    from datetime import timedelta

    from .markets import is_trading_window

    now = now_local(m.cfg)
    day = now.date()
    if not is_trading_window(m.cfg, now) and now.hour >= 12:
        day += timedelta(days=1)
    while day.weekday() >= 5:
        day += timedelta(days=1)
    return {"id": os.urandom(6).hex(), "created": now.isoformat(timespec="seconds"), "ticker": ticker.upper(),
            "side": side, "validity": "day", "valid_until": day.isoformat()}


def _sim_or_help(m):
    try:
        sim = m.sim_for_edit()
    except ValueError as exc:
        m.tg.send(f"⚠️ {esc(exc)}.")
        return None
    if sim is None:
        m.tg.send("Il simulatore non è ancora attivo: crealo con /simnuovo 10000 (budget in euro) o dalla dashboard.")
    return sim


def cmd_sim(m, args):
    from .messages import sim_overview

    sim = _sim_or_help(m)
    if sim is None:
        return
    state = m.sim_state()
    if not state or state.get("epoch") != sim["epoch"] or "totals" not in state:
        m.tg.send("🧪 Simulatore creato: il conto si aggiorna al prossimo giro dello scanner.")
        return
    pending = sum(1 for o in sim["orders"] if o["id"] not in state["orders"] and not o.get("cancelled"))
    m.tg.send(sim_overview(state, pending))


def cmd_sim_new(m, args):
    from .simulator import new_sim

    budget = _amount(args[0]) if args else None
    if not budget or budget < 100:
        m.tg.send("Uso: /simnuovo BUDGET (almeno 100 €), es. /simnuovo 10000. Attenzione: azzera la simulazione attuale.")
        return
    try:
        old = m.sim_for_edit()
    except ValueError as exc:
        m.tg.send(f"⚠️ {esc(exc)}.")
        return
    sim = new_sim(budget, now_local(m.cfg).date().isoformat())
    if old:
        sim["settings"] = old["settings"]  # tengo i costi che avevi impostato
    m.save_sim(sim)
    m.tg.send(f"🧪 Nuova simulazione con {fmt_num(budget, 0)} € di budget. Compra con /simcompra TICKER QUANTITÀ.")


def cmd_sim_deposit(m, args):
    import os

    amount = _amount(args[0]) if args else None
    if not amount:
        m.tg.send("Uso: /simversa IMPORTO (es. /simversa 1000)")
        return
    sim = _sim_or_help(m)
    if sim is None:
        return
    sim["deposits"].append({"id": os.urandom(6).hex(), "amount": amount, "date": now_local(m.cfg).date().isoformat(),
                            "note": "versamento da Telegram"})
    m.save_sim(sim)
    m.tg.send(f"🧪 Versati {fmt_num(amount, 2)} € nel conto simulato.")


def cmd_sim_broker(m, args):
    from .simulator import broker_settings, commission, load_brokers, market_of

    brokers = load_brokers()
    if not args:
        lines = ["🏦 <b>Broker disponibili</b> (costo di un ordine da 2.000 € su Borsa Italiana · Europa · USA)"]
        for b in brokers:
            st = broker_settings(b["id"])
            costs = " · ".join(fmt_num(commission(2000, st, mk), 2) for mk in ("it", "eu", "us"))
            lines.append(f"<code>{b['id']}</code> {esc(b['name'])}: {costs} € · {b['regime']}")
        lines.append("\nScegli con /simbroker ID (es. /simbroker degiro)")
        m.tg.send("\n".join(lines))
        return
    sim = _sim_or_help(m)
    if sim is None:
        return
    try:
        new = broker_settings(args[0].lower(), sim["settings"])
    except KeyError:
        m.tg.send("Broker sconosciuto: scrivi /simbroker per l'elenco.")
        return
    sim["settings"] = new
    m.save_sim(sim)
    b = next(b for b in brokers if b["id"] == new["broker"])
    m.tg.send(f"🏦 Il simulatore ora usa le tariffe di <b>{esc(b['name'])}</b> ({b['regime']}).\n{esc(b['summary'])}")


def _sim_trade(side: str):
    def run(m, args):
        usage = (f"Uso: /sim{'compra' if side == 'buy' else 'vendi'} TICKER QUANTITÀ [prezzo limite]\n"
                 + ("es. /simcompra ENEL.MI 100 · /simcompra ENEL.MI 1000€ (importo) · /simcompra ENEL.MI 100 8,50 (limite)"
                    if side == "buy" else "es. /simvendi ENEL.MI 50 · /simvendi ENEL.MI tutto · /simvendi ENEL.MI 50 9,20 (limite)"))
        if len(args) < 2:
            m.tg.send(usage)
            return
        sim = _sim_or_help(m)
        if sim is None:
            return
        order = _new_order(m, args[0], side)
        size = args[1].lower()
        if side == "sell" and size in ("tutto", "tutte", "all"):
            order["all"] = True
        elif side == "buy" and size.endswith(("€", "eur")):
            amount = _amount(size.rstrip("eur€"))
            if not amount:
                m.tg.send(usage)
                return
            order["amount"] = amount
        else:
            qty = _amount(size)
            if not qty or not float(qty).is_integer():
                m.tg.send("La quantità deve essere un numero intero di azioni.\n" + usage)
                return
            order["quantity"] = int(qty)
        if len(args) > 2:
            limit = _amount(args[2])
            if not limit:
                m.tg.send(usage)
                return
            order["limit"] = limit
        sim["orders"].append(order)
        m.save_sim(sim)
        what = ("tutte le azioni" if order.get("all") else f"{fmt_num(order['amount'], 0)} €" if order.get("amount")
                else f"{order['quantity']} azioni")
        m.tg.send(f"🧪 Ordine di {'acquisto' if side == 'buy' else 'vendita'} inserito: {what} di <code>{esc(order['ticker'])}</code>"
                  + (f" con limite {fmt_num(order['limit'])}" if order.get("limit") else " al mercato")
                  + f", valido per la seduta del {'/'.join(reversed(order['valid_until'].split('-')))}. "
                  "Lo eseguo al prossimo controllo a borsa aperta.")
    return run


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
    "compra": cmd_buy,
    "vendi": cmd_sell,
    "piano": cmd_plan,
    "obiettivo": _pf_setting("take_profit_pct", "Obiettivo di guadagno"),
    "sim": cmd_sim,
    "simnuovo": cmd_sim_new,
    "simversa": cmd_sim_deposit,
    "simcompra": _sim_trade("buy"),
    "simvendi": _sim_trade("sell"),
    "simbroker": cmd_sim_broker,
    "stop": _pf_setting("stop_loss_pct", "Stop di perdita"),
    "soglia": _setting("drop_threshold_pct", "Soglia di calo (%)", 0.5, 50),
    "relativa": _setting("relative_threshold_pct", "Punti peggio del mercato", 0, 50),
    "passo": _setting("realert_step_pct", "Ulteriore calo per un nuovo avviso (pt)", 0.1, 50),
    "filtro": cmd_filter,
    "aggiungi": cmd_add,
    "rimuovi": cmd_remove,
    "pausa": cmd_pause,
    "riprendi": cmd_resume,
}
