"""Riga di comando: python -m actionzz <comando>."""

from __future__ import annotations

import argparse
import logging
import sys

from .config import DATA_DIR, load_config
from .state import Store
from .telegram import Telegram


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="actionzz", description="Monitor di azioni europee stabili con avvisi Telegram")
    parser.add_argument("--data-dir", default=str(DATA_DIR), help="cartella dei file di stato (predefinita: ./stato)")
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("scan", help="un ciclo: comandi Telegram, scansione se la borsa è aperta, riepilogo se è l'ora")
    sub.add_parser("loop", help="esecuzione continua (PC/server): scansione ogni N minuti")
    sub.add_parser("universe", help="ricalcola l'universo dei titoli più stabili")
    sub.add_parser("backtest", help="simula gli avvisi sugli ultimi anni")
    sub.add_parser("summary", help="invia subito il riepilogo della giornata")
    sub.add_parser("test-telegram", help="invia un messaggio di prova e registra i comandi del bot")
    sub.add_parser("chat-id", help="mostra il chat id di chi ha scritto al bot")
    sub.add_parser("session-status", help="stampa before/open/closed per la sessione di borsa")
    sub.add_parser("strategies", help="calcola il laboratorio delle strategie (strategies.json)")
    sub.add_parser("maintenance", help="a borsa chiusa: ricalcola universo, backtest e strategie se sono vecchi")
    listen = sub.add_parser("listen", help="risponde ai comandi Telegram fino al prossimo multiplo di N minuti")
    listen.add_argument("--minutes", type=int, default=5)
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    logging.getLogger("yfinance").setLevel(logging.CRITICAL)  # i ticker senza dati sono normali

    cfg = load_config()
    store = Store(args.data_dir)
    tg = Telegram()

    if args.command == "session-status":
        from .markets import now_local, session_status

        print(session_status(cfg, now_local(cfg)))
        return 0
    if args.command == "listen":
        import time as _time

        from .monitor import Monitor

        period = max(1, args.minutes) * 60
        wait = period - (_time.time() % period)
        monitor = Monitor(cfg, store, tg)
        monitor.listen(wait)
        if monitor.config_changed or monitor.portfolio_changed:
            print("::notice::Modifiche da Telegram")
        return 0
    if args.command == "strategies":
        from .strategies import run_strategies

        r = run_strategies(cfg, store)
        print(f"Strategie calcolate: {len(r['strategies'])} strategie, {len(r['dip']['combos'])} combinazioni")
        return 0
    if args.command == "maintenance":
        from .maintenance import run_maintenance

        run_maintenance(cfg, store)
        return 0
    if args.command == "universe":
        from .universe import build_universe

        u = build_universe(cfg, store)
        print(f"Universo: {u['stats']['selected']} titoli, volatilità mediana {u['stats']['vol_median']}%")
    elif args.command == "backtest":
        from .backtest import run_backtest

        r = run_backtest(cfg, store)
        print(f"{r['main']['signals']} segnali ({r['main']['per_year']}/anno) con soglia {cfg.drop_threshold_pct}%")
        for row in r["sweep"]:
            print(f"  soglia {row['threshold']:>4}%: {row['signals']:>5} segnali, rendimento medio a 20 gg {row['ret20']}%, "
                  f"positivi {row['hit20']}%, vs mercato {row['excess20']} pt")
    elif args.command == "test-telegram":
        from .messages import BOT_COMMANDS

        if not tg.enabled:
            print("Imposta le variabili TELEGRAM_TOKEN e TELEGRAM_CHAT_ID.")
            return 1
        tg.set_commands(BOT_COMMANDS)
        ok = tg.send("✅ <b>Actionzz</b> è collegato! Scrivi /aiuto per i comandi.")
        print("Messaggio inviato." if ok else "Invio fallito: controlla token e chat id.")
        return 0 if ok else 1
    elif args.command == "chat-id":
        if not tg.token:
            print("Imposta la variabile TELEGRAM_TOKEN.")
            return 1
        chats = {}
        for upd in tg.get_updates():
            chat = (upd.get("message") or {}).get("chat") or {}
            if chat:
                chats[chat["id"]] = chat.get("username") or chat.get("first_name") or ""
        if not chats:
            print("Nessun messaggio: scrivi /start al tuo bot su Telegram e riprova.")
            return 1
        for cid, who in chats.items():
            print(f"chat id {cid}  ({who})")
    else:
        from .monitor import Monitor

        monitor = Monitor(cfg, store, tg)
        if args.command == "scan":
            monitor.run_cycle()
            if monitor.config_changed:
                print("::notice::Impostazioni modificate da Telegram")
            if monitor.portfolio_changed:
                print("::notice::Portafoglio modificato da Telegram")
        elif args.command == "loop":
            monitor.loop()
        elif args.command == "summary":
            from .markets import now_local

            monitor.send_summary(now_local(cfg))
    return 0


if __name__ == "__main__":
    sys.exit(main())
