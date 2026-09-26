from datetime import datetime, timedelta

from actionzz.config import load_config
from actionzz.monitor import Monitor

from .conftest import ROME, FakeTelegram, make_universe, market_frames


def build(cfg, store, tmp_path, frames, tg=None):
    store.write("universe.json", make_universe(sorted(frames)))
    tg = tg or FakeTelegram()

    def downloader(tickers, period="1mo", **kw):
        return {t: frames[t] for t in tickers if t in frames}

    m = Monitor(cfg, store, tg, downloader=downloader, fundamentals=lambda t: {"pe": 12.5, "dividend_yield": 4.1},
                news=lambda t: [], config_path=tmp_path / "config.json")
    return m, tg


def test_scan_sends_alert_once(cfg, store, tmp_path, now):
    frames = market_frames(drops={"T03.MI": -7.0})
    m, tg = build(cfg, store, tmp_path, frames)
    m.run_cycle(now)
    alerts = [t for t in tg.sent if "Calo improvviso" in t]
    assert len(alerts) == 1 and "T03.MI" in alerts[0] and "P/E 12,5" in alerts[0]
    assert store.read("alerts.json")[0]["ticker"] == "T03.MI"
    assert store.read("snapshot.json")["quotes"][0]["ticker"] == "T03.MI"

    # stato ricaricato come in una nuova esecuzione di GitHub Actions: niente doppioni
    m2, tg2 = build(cfg, store, tmp_path, frames)
    m2.run_cycle(now + timedelta(minutes=5))
    assert not [t for t in tg2.sent if "Calo" in t]


def test_realert_when_falls_further(cfg, store, tmp_path, now):
    m, tg = build(cfg, store, tmp_path, market_frames(drops={"T03.MI": -6.0}))
    m.run_cycle(now)
    m2, tg2 = build(cfg, store, tmp_path, market_frames(drops={"T03.MI": -9.0}))
    m2.run_cycle(now + timedelta(minutes=5))
    assert any("Nuovo calo" in t for t in tg2.sent)


def test_market_wide_drop_is_filtered(cfg, store, tmp_path, now):
    # tutto il mercato a -4%, un titolo a -6%: solo l'avviso di mercato
    m, tg = build(cfg, store, tmp_path, market_frames(market_pct=-4.0, drops={"T03.MI": -6.0}))
    m.run_cycle(now)
    assert any("Calo generalizzato" in t for t in tg.sent)
    assert not any("Calo improvviso" in t for t in tg.sent)


def test_closed_market_no_scan(cfg, store, tmp_path):
    m, tg = build(cfg, store, tmp_path, market_frames(drops={"T03.MI": -7.0}))
    m.run_cycle(datetime(2026, 9, 26, 11, 0, tzinfo=ROME))  # sabato
    assert tg.sent == [] and store.read("snapshot.json") is None


def test_paused_scans_but_does_not_alert(cfg, store, tmp_path, now):
    cfg.paused = True
    m, tg = build(cfg, store, tmp_path, market_frames(drops={"T03.MI": -7.0}))
    m.run_cycle(now)
    assert tg.sent == [] and store.read("snapshot.json") is not None


def test_daily_summary_sent_once(cfg, store, tmp_path, now):
    m, tg = build(cfg, store, tmp_path, market_frames(drops={"T03.MI": -7.0}))
    m.run_cycle(now)
    evening = now.replace(hour=18, minute=5)
    m.run_cycle(evening)
    m.run_cycle(evening + timedelta(minutes=5))
    summaries = [t for t in tg.sent if "Riepilogo" in t]
    assert len(summaries) == 1 and "T03.MI" in summaries[0]


def update(uid, text, chat=42):
    return {"update_id": uid, "message": {"text": text, "chat": {"id": chat}}}


def test_commands_change_config(cfg, store, tmp_path, now):
    tg = FakeTelegram(updates=[update(1, "/soglia 4,5"), update(2, "/filtro off"), update(3, "/aggiungi enel.mi")])
    m, tg = build(cfg, store, tmp_path, market_frames(), tg)
    m.run_cycle(now)
    saved = load_config(tmp_path / "config.json")
    assert saved.drop_threshold_pct == 4.5 and saved.market_filter is False and saved.include == ["ENEL.MI"]
    assert m.config_changed and m.state.telegram_offset == 4


def test_commands_from_strangers_ignored(cfg, store, tmp_path, now):
    tg = FakeTelegram(updates=[update(1, "/pausa", chat=999)])
    m, tg = build(cfg, store, tmp_path, market_frames(), tg)
    m.process_commands()
    assert m.cfg.paused is False and tg.sent == []


def test_status_and_today_commands(cfg, store, tmp_path, now):
    m, tg = build(cfg, store, tmp_path, market_frames(drops={"T03.MI": -7.0}))
    m.run_cycle(now)
    tg.updates = [update(1, "/stato"), update(2, "/oggi 3"), update(3, "/boh")]
    m.process_commands()
    assert "Stato di Actionzz" in tg.sent[-3]
    assert "T03.MI" in tg.sent[-2]
    assert "Comando sconosciuto" in tg.sent[-1]
