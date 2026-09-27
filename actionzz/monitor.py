"""Il ciclo principale: comandi Telegram, scansione, avvisi, riepilogo."""

from __future__ import annotations

import logging
import os
import time
from datetime import datetime
from typing import Callable

import pandas as pd

from . import charts, data, messages, portfolio
from .commands import handle_command
from .config import CONFIG_PATH, Config, save_config
from .detector import Quote, Signal, compute_quote, find_signals, market_crash_due, market_move
from .markets import is_summary_due, is_trading_window, now_local
from .state import State, Store
from .telegram import Telegram
from .universe import active_items, build_universe, load_universe

log = logging.getLogger(__name__)

MIN_QUOTES_FOR_MARKET = 20  # con meno titoli aperti la mediana non è significativa


class Monitor:
    def __init__(
        self,
        cfg: Config,
        store: Store,
        tg: Telegram,
        downloader: Callable[..., dict[str, pd.DataFrame]] = data.download_daily,
        fundamentals: Callable[[str], dict] = data.fetch_fundamentals,
        news: Callable[[str], list[dict]] = data.fetch_news,
        config_path=CONFIG_PATH,
        portfolio_path=portfolio.PORTFOLIO_PATH,
        portfolio_password: str | None = None,
    ):
        self.cfg = cfg
        self.store = store
        self.tg = tg
        self.download = downloader
        self.fundamentals = fundamentals
        self.news = news
        self.config_path = config_path
        self.state = State(store)
        self.config_changed = False
        self.portfolio_path = portfolio_path
        self.portfolio_password = (
            portfolio_password if portfolio_password is not None else os.environ.get("PORTFOLIO_PASSWORD", "")
        )

    # ------------------------------------------------------------------ utilità

    def metas(self) -> dict[str, dict]:
        return {i["ticker"]: i for i in active_items(load_universe(self.store), self.cfg)}

    def ensure_universe(self) -> None:
        if not load_universe(self.store):
            log.info("Universo assente: lo costruisco ora (qualche minuto)...")
            build_universe(self.cfg, self.store)

    def update_config(self, **changes) -> None:
        for key, value in changes.items():
            setattr(self.cfg, key, value)
        save_config(self.cfg, self.config_path)
        self.config_changed = True

    # ---------------------------------------------------------------- scansione

    def scan(self, now: datetime) -> dict | None:
        metas = self.metas()
        if not metas:
            log.warning("Nessun titolo da monitorare")
            return None
        frames = self.download(list(metas), period="1mo")
        quotes = [q for t, df in frames.items() if (q := compute_quote(t, df, now.date()))]
        log.info("Quotazioni di oggi: %d su %d titoli", len(quotes), len(metas))
        if len(quotes) < MIN_QUOTES_FOR_MARKET:
            log.info("Troppi pochi titoli aperti oggi (festività?): nessun avviso")
            return None

        market = market_move(quotes)
        self.state.scans_today += 1
        self.state.last_scan = now.isoformat(timespec="seconds")
        snapshot = self._write_snapshot(now, quotes, market, metas)

        if self.cfg.paused:
            log.info("Avvisi in pausa")
            return snapshot

        if market_crash_due(market, self.cfg, self.state.market_alert_pct):
            self.tg.send(messages.market_crash(market, quotes, self.cfg))
            self.state.market_alert_pct = market

        signals = find_signals(quotes, market, self.cfg, self.state.alerts)
        if signals:
            self.send_alerts(signals, market, metas, now)
        return snapshot

    def _write_snapshot(self, now: datetime, quotes: list[Quote], market: float, metas: dict) -> dict:
        snapshot = {
            "time": now.isoformat(timespec="seconds"),
            "day": now.date().isoformat(),
            "market_pct": round(market, 3),
            "monitored": len(metas),
            "quotes": [
                {
                    "ticker": q.ticker,
                    "price": round(q.price, 4),
                    "prev_close": round(q.prev_close, 4),
                    "pct": round(q.pct, 3),
                    "low_pct": round(q.low_pct, 3),
                    "rel": round(q.pct - market, 3),
                    "vol_ratio": round(q.volume / q.avg_volume_20d, 2) if q.volume and q.avg_volume_20d else None,
                    "dividend": q.dividend or None,
                }
                for q in sorted(quotes, key=lambda q: q.pct)
            ],
        }
        self.store.write("snapshot.json", snapshot)
        history = [h for h in self.store.read("market_history.json", []) if h["day"] != snapshot["day"]]
        history.append({
            "day": snapshot["day"],
            "market_pct": snapshot["market_pct"],
            "down": sum(1 for q in quotes if q.pct < 0),
            "up": sum(1 for q in quotes if q.pct > 0),
            "alerts": len(self.state.alerts),
        })
        self.store.write("market_history.json", history[-400:])
        return snapshot

    def send_alerts(self, signals: list[Signal], market: float, metas: dict, now: datetime) -> None:
        detailed = signals[: self.cfg.max_alerts_per_scan]
        rest = signals[self.cfg.max_alerts_per_scan :]
        histories = self.download([s.quote.ticker for s in detailed], period="1y")
        records = []
        for s in detailed:
            meta = metas.get(s.quote.ticker, {})
            text, png = self.detail_card(s, meta, market, histories.get(s.quote.ticker))
            self.tg.send(text)
            if png:
                self.tg.send_photo(png, caption=f"{s.quote.ticker} {messages.fmt_pct(s.quote.pct)}")
        for s in signals:
            meta = metas.get(s.quote.ticker, {})
            prev = self.state.alerts.get(s.quote.ticker, {})
            self.state.alerts[s.quote.ticker] = {
                "pct": s.quote.pct,
                "first_pct": prev.get("first_pct", s.quote.pct),
                "first_time": prev.get("first_time", now.isoformat(timespec="seconds")),
                "count": prev.get("count", 0) + 1,
            }
            records.append({
                "time": now.isoformat(timespec="seconds"),
                "day": now.date().isoformat(),
                "ticker": s.quote.ticker,
                "name": meta.get("name", s.quote.ticker),
                "country": meta.get("country", ""),
                "price": round(s.quote.price, 4),
                "prev_close": round(s.quote.prev_close, 4),
                "pct": round(s.quote.pct, 3),
                "relative": None if s.relative is None else round(s.relative, 3),
                "market_pct": round(market, 3),
                "repeat": s.is_repeat,
            })
        if rest:
            self.tg.send(messages.overflow_list(rest, metas))
        self.store.append_alerts(records)
        # salvo subito: se il job muore dopo, non rimandiamo gli stessi avvisi
        self.state.save()

    def detail_card(self, signal: Signal, meta: dict, market: float | None, history: pd.DataFrame | None):
        q = signal.quote
        fundamentals = self.fundamentals(q.ticker)
        news = self.news(q.ticker) if self.cfg.send_news else []
        extra, png = {}, None
        if history is not None and not history.empty:
            year = history["Close"].dropna()
            extra = {
                "high_52w": float(history["High"].max()),
                "low_52w": float(history["Low"].min()),
                "return_1y": round((q.price / float(year.iloc[0]) - 1) * 100, 1) if len(year) else None,
            }
            if self.cfg.send_chart:
                try:
                    png = charts.price_chart(q.ticker, year, q.prev_close, q.price, meta.get("currency", ""))
                except Exception as exc:  # il grafico è un di più: mai bloccare l'avviso
                    log.warning("grafico non generato per %s: %s", q.ticker, exc)
        text = messages.alert_card(signal, meta, market, fundamentals, news, extra)
        return text, png

    def ticker_card(self, ticker: str):
        """Scheda di un titolo a richiesta (/titolo), anche fuori dall'universo."""
        frames = self.download([ticker], period="1y")
        df = frames.get(ticker)
        if df is None or len(df) < 2:
            return None, None
        quote = compute_quote(ticker, df, df.index[-1].date())
        if quote is None:
            return None, None
        snapshot = self.store.read("snapshot.json", {}) or {}
        market = snapshot.get("market_pct") if snapshot.get("day") == quote.day else None
        relative = None if market is None else quote.pct - market
        meta = self.metas().get(ticker) or {"ticker": ticker, **_exchange_meta(ticker)}
        signal = Signal(quote, relative, None)
        text, png = self.detail_card(signal, meta, market, df)
        text = text.replace("🚨 <b>Calo improvviso</b>", "🔎 <b>Scheda</b>", 1)
        return text, png

    # -------------------------------------------------------------- portafoglio

    def update_portfolio(self, now: datetime) -> dict | None:
        """Ricalcola il resoconto cifrato del portafoglio e avvisa sui nuovi segnali di vendita."""
        pf = portfolio.load_portfolio(self.portfolio_password, self.portfolio_path)
        if pf is None:
            return None
        previous = portfolio.load_report(self.store, self.portfolio_password) or {}
        tickers = sorted(portfolio.aggregate(pf["positions"]))
        cached = previous.get("fundamentals", {})
        cache = cached.get("data", {}) if cached.get("day") == now.date().isoformat() else {}
        fundamentals = {t: cache[t] if t in cache else self.fundamentals(t) for t in tickers}
        histories = self.download(tickers, period="2y") if tickers else {}
        rates = portfolio.fx_to_eur({portfolio.currency_of(t, fundamentals[t]) for t in tickers}, self.download)
        report = portfolio.build_report(pf, histories, fundamentals, rates, self.cfg, now.date(), previous)
        # fuori orario i segnali restano in attesa: li mando alla prossima apertura
        if is_trading_window(self.cfg, now):
            fresh = portfolio.new_notifications(report)
            if fresh and report["settings"]["sell_alerts"] and not self.cfg.paused:
                for row in fresh:
                    self.tg.send(messages.holding_card(row, report["settings"]["tax_rate_pct"]))
        portfolio.save_report(self.store, report, self.portfolio_password)
        return report

    def portfolio_report(self) -> dict | None:
        return portfolio.load_report(self.store, self.portfolio_password)

    # ---------------------------------------------------------------- riepilogo

    def send_summary(self, now: datetime) -> bool:
        snapshot = self.store.read("snapshot.json")
        if not snapshot:
            self.tg.send("Nessun dato disponibile per il riepilogo: la borsa non è ancora stata scansionata.")
            return False
        alerts_today = [a for a in self.store.read("alerts.json", []) if a["day"] == snapshot["day"]]
        text = messages.daily_summary(snapshot, alerts_today, self.metas(), now, self.cfg)
        self.tg.send(text)
        self.store.write("summary.json", {"day": snapshot["day"], "time": now.isoformat(timespec="seconds"), "text": text})
        report = self.portfolio_report()
        if report and report.get("holdings"):
            # messaggio a parte: summary.json è pubblico, il portafoglio no
            self.tg.send(messages.portfolio_overview(report))
        return True

    # ----------------------------------------------------------------- comandi

    def process_commands(self, timeout: int = 0) -> int:
        if not self.tg.token:
            return 0
        updates = self.tg.get_updates(offset=self.state.telegram_offset, timeout=timeout)
        for upd in updates:
            self.state.telegram_offset = upd["update_id"] + 1
            msg = upd.get("message") or {}
            text = (msg.get("text") or "").strip()
            chat = str((msg.get("chat") or {}).get("id", ""))
            if not text.startswith("/"):
                continue
            if not self.tg.chat_id:
                self.tg.send(f"Il tuo chat id è <code>{chat}</code>: salvalo nel secret TELEGRAM_CHAT_ID.", chat_id=chat)
                continue
            if chat != self.tg.chat_id:
                log.warning("Comando ignorato da una chat non autorizzata: %s", chat)
                continue
            try:
                handle_command(self, text)
            except Exception as exc:
                log.exception("Errore nel comando %s", text)
                self.tg.send(f"⚠️ Errore nel comando: {messages.esc(exc)}")
        if updates:
            self.state.save()
        return len(updates)

    # ------------------------------------------------------------------- ciclo

    def run_cycle(self, now: datetime | None = None) -> None:
        now = now or now_local(self.cfg)
        self.state.roll_day(now.date())
        self.process_commands()
        if is_trading_window(self.cfg, now):
            self.ensure_universe()
            self.scan(now)
        else:
            log.info("Borsa chiusa (%s): nessuna scansione", now.strftime("%a %H:%M"))
        try:
            self.update_portfolio(now)
        except Exception:
            log.exception("Errore nel calcolo del portafoglio")
        if (
            self.cfg.daily_summary
            and not self.state.summary_sent
            and self.state.scans_today > 0
            and is_summary_due(self.cfg, now)
        ):
            self.state.summary_sent = self.send_summary(now)
        self.state.save()

    def loop(self) -> None:
        """Esecuzione continua (PC, Raspberry...): scansione ogni N minuti, comandi subito."""
        self.tg.set_commands(messages.BOT_COMMANDS)
        while True:
            started = time.monotonic()
            try:
                self.run_cycle()
            except Exception:
                log.exception("Errore nel ciclo di scansione")
            deadline = started + self.cfg.scan_interval_minutes * 60
            while (remaining := deadline - time.monotonic()) > 0:
                if self.tg.token:
                    self.process_commands(timeout=int(min(30, max(1, remaining))))
                else:
                    time.sleep(remaining)


def _exchange_meta(ticker: str) -> dict:
    from .markets import exchange_info

    country, currency, exchange = exchange_info(ticker)
    return {"name": ticker, "country": country, "currency": currency, "exchange": exchange}
