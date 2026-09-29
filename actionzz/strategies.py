"""Laboratorio delle strategie: backtest su 5 anni dei titoli dell'universo.

Produce strategies.json per la dashboard, con tre blocchi:
- "dip": griglia "compro dopo un calo del X%, rivendo al +Y%" (con stop e durata massima), calcolata
  operazione per operazione sui prezzi reali; la dashboard ci applica costi e tasse del broker scelto
  e simula n operazioni pescando dagli esiti storici;
- "strategies": strategie di portafoglio dalla letteratura (momentum, bassa volatilità, trend, ...), con
  i rendimenti lordi anno per anno e i volumi scambiati, così la dashboard calcola costi e tasse;
- "lab": dati per i consigli interattivi (indice equiponderato giornaliero, diversificazione).

Limiti dichiarati nella dashboard: universo di oggi (distorsione di sopravvivenza), prezzi rettificati,
nessun dividendo nelle strategie "a posizioni" oltre a quelli già nel prezzo rettificato.
"""

from __future__ import annotations

import logging
import math
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from .backtest import BREAK_JUMP
from .simulator import TRANSACTION_TAXES, currency_for, suffix

log = logging.getLogger(__name__)

DIPS = [3, 4, 5, 6, 7, 8, 10]
TARGETS = [3, 5, 7, 10, 15, 20]
STOPS = [0, 5, 10, 15, 20]  # 0 = nessuno stop
HOLDS = [20, 60, 120]  # sedute massime prima di vendere comunque
QUANTILES = np.linspace(0, 100, 21)
COOLDOWN = 5
TRADING_DAYS = 252
WARMUP = 252  # tutte le strategie partono dopo un anno di storico, così il confronto è alla pari
KEEP = object()  # "non ribilanciare": tieni i pesi attuali


# ---------------------------------------------------------------- dati


def matrices(frames: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    """Matrici date × titoli di apertura, massimo, minimo e chiusura (prezzi rettificati)."""
    out = {k: pd.DataFrame({t: df[k] for t, df in frames.items()}).sort_index() for k in ("Open", "High", "Low", "Close")}
    close = out["Close"]
    # le rotture della serie (scorpori, errori di Yahoo) spezzano il titolo: i giorni dopo diventano NaN
    jumps = (np.log(close).diff().abs() > BREAK_JUMP).cumsum()
    valid = jumps == 0
    for k in out:
        out[k] = out[k].where(valid)
    return out


def ticker_costs(tickers) -> dict[str, np.ndarray]:
    t = list(tickers)
    return {
        "ftt": np.array([TRANSACTION_TAXES.get(suffix(x), ("", 0.0))[1] for x in t]),
        "noneur": np.array([currency_for(x) != "EUR" for x in t], dtype=float),
        "it": np.array([suffix(x) == ".MI" for x in t], dtype=float),
    }


# ------------------------------------------------ compro al −X%, rivendo al +Y%


def dip_signals(m: dict[str, pd.DataFrame], dip: float):
    """Segnali: il titolo chiude almeno dip% sotto la chiusura di ieri; si compra in chiusura.

    Si usano solo le chiusure: i minimi e massimi di giornata di Yahoo contengono errori e comprare
    esattamente sul minimo presuppone ordini limite già piazzati su tutti i titoli (troppo ottimista).
    """
    c = m["Close"].to_numpy()
    prev = np.roll(c, 1, axis=0)
    prev[0] = np.nan
    hit = (c <= prev * (1 - dip / 100)) & np.isfinite(prev)
    entry = c
    rows, cols = [], []
    for j in range(hit.shape[1]):
        last = -COOLDOWN - 1
        for i in np.flatnonzero(hit[:, j]):
            if i - last > COOLDOWN:
                rows.append(i)
                cols.append(j)
                last = i
    rows, cols = np.array(rows, dtype=int), np.array(cols, dtype=int)
    return rows, cols, entry[rows, cols]


def forward_paths(m, rows, cols, entry, horizon):
    """Prezzi dei giorni successivi all'acquisto, relativi al prezzo d'ingresso: (segnali × orizzonte)."""
    n_days = m["Close"].shape[0]
    idx = rows[:, None] + np.arange(1, horizon + 1)[None, :]
    ok = idx < n_days
    idx = np.minimum(idx, n_days - 1)
    paths = {}
    for k in ("Close",):
        arr = m[k].to_numpy()[idx, cols[:, None]] / entry[:, None]
        arr[~ok] = np.nan
        paths[k] = arr
    return paths


def first_true(mask: np.ndarray) -> np.ndarray:
    """Indice del primo True per riga, o -1."""
    any_ = mask.any(axis=1)
    return np.where(any_, mask.argmax(axis=1), -1)


def simulate_exits(paths, market_fwd, target, stop, hold):
    """Esito di ogni operazione: rendimento lordo, sedute di possesso, rendimento del mercato nello stesso periodo.

    Si vende in chiusura il primo giorno che la chiusura raggiunge l'obiettivo o scende sotto lo stop,
    altrimenti alla chiusura dell'ultima seduta consentita.
    """
    c = paths["Close"][:, :hold]
    n = c.shape[0]
    t_lvl = 1 + target / 100
    k_t = first_true(c >= t_lvl)
    if stop:
        s_lvl = 1 - stop / 100
        k_s = first_true(c <= s_lvl)
    else:
        k_s = np.full(n, -1)
    # ultima seduta disponibile entro l'orizzonte (i titoli possono uscire dai dati)
    valid = np.isfinite(c)
    last = np.where(valid.any(axis=1), hold - 1 - np.argmax(valid[:, ::-1], axis=1), -1)
    big = hold + 1
    kt = np.where(k_t >= 0, k_t, big)
    ks = np.where(k_s >= 0, k_s, big)
    # stesso giorno: prudenzialmente prima lo stop
    exit_stop = (ks <= kt) & (ks < big)
    exit_target = (kt < ks) & (kt < big)
    k = np.where(exit_stop, ks, np.where(exit_target, kt, last))
    rows = np.arange(n)
    kk = np.clip(k, 0, hold - 1)
    ret = c[rows, kk] - 1
    ok = k >= 0
    market = market_fwd[rows, kk]
    outcome = np.where(exit_target, 1, np.where(exit_stop, -1, 0))
    return ret[ok] * 100, (k[ok] + 1), market[ok], outcome[ok]


def dip_grid(m, market_idx: np.ndarray) -> dict:
    """Tutte le combinazioni calo/obiettivo/stop/durata, con statistiche e distribuzione degli esiti."""
    close = m["Close"]
    costs = ticker_costs(close.columns)
    years = (close.index[-1] - close.index[0]).days / 365.25
    horizon = max(HOLDS)
    combos = []
    per_dip = {}
    for dip in DIPS:
        rows, cols, entry = dip_signals(m, dip)
        if len(rows) == 0:
            continue
        paths = forward_paths(m, rows, cols, entry, horizon)
        # rendimento del mercato (indice equiponderato) dalla chiusura del giorno d'ingresso a quella d'uscita
        idx = rows[:, None] + np.arange(1, horizon + 1)[None, :]
        idx = np.minimum(idx, len(market_idx) - 1)
        market_fwd = (market_idx[idx] / market_idx[rows][:, None] - 1) * 100
        per_dip[dip] = {
            "signals": int(len(rows)),
            "per_year": round(len(rows) / years, 1),
            "ftt_pct": round(float(costs["ftt"][cols].mean()), 4),
            "noneur": round(float(costs["noneur"][cols].mean()), 3),
            "it_share": round(float(costs["it"][cols].mean()), 3),
        }
        for target in TARGETS:
            for stop in STOPS:
                for hold in HOLDS:
                    r, days, mkt, outcome = simulate_exits(paths, market_fwd, target, stop, hold)
                    if len(r) < 20:
                        continue
                    combos.append({
                        "dip": dip, "target": target, "stop": stop, "hold": hold,
                        "n": int(len(r)),
                        "win": round(float((outcome == 1).mean() * 100), 1),
                        "stopped": round(float((outcome == -1).mean() * 100), 1),
                        "timeout": round(float((outcome == 0).mean() * 100), 1),
                        "positive": round(float((r > 0).mean() * 100), 1),
                        "mean": round(float(r.mean()), 3),
                        "median": round(float(np.median(r)), 3),
                        "days": round(float(days.mean()), 1),
                        "market": round(float(np.nanmean(mkt)), 3),
                        "q": [round(float(x), 2) for x in np.percentile(r, QUANTILES)],
                    })
    return {"dips": DIPS, "targets": TARGETS, "stops": STOPS, "holds": HOLDS, "per_dip": per_dip,
            "years": round(years, 2), "combos": combos}


# ------------------------------------------------------ strategie di portafoglio


def _rebalance_days(index: pd.DatetimeIndex, every: str) -> set:
    s = pd.Series(np.arange(len(index)), index=index)
    if every == "W":
        return set(s.groupby([index.isocalendar().year, index.isocalendar().week]).min())
    period = {"M": index.to_period("M"), "Q": index.to_period("Q")}[every]
    return set(s.groupby(period).min())


class Book:
    """Registro di un portafoglio simulato: valore lordo, ordini e volumi scambiati, anno per anno."""

    def __init__(self, index, tickers, start=WARMUP):
        self.index = index
        self.start = start
        self.equity = np.ones(len(index))
        self.invested = np.zeros(len(index))  # quota investita (il resto è liquidità): serve per il bollo
        self.year_stats: dict[int, dict] = {}
        self.costs = ticker_costs(tickers)

    def trade(self, i: int, delta_w: np.ndarray, equity: float):
        y = self.index[i].year
        st = self.year_stats.setdefault(y, {"orders": 0, "buy": 0.0, "sell": 0.0, "ftt": 0.0, "noneur": 0.0, "it_orders": 0})
        moved = np.abs(delta_w) > 1e-9
        buys = np.clip(delta_w, 0, None) * equity
        sells = np.clip(-delta_w, 0, None) * equity
        st["orders"] += int(moved.sum())
        st["it_orders"] += int((moved & (self.costs["it"] > 0)).sum())
        st["buy"] += float(buys.sum())
        st["sell"] += float(sells.sum())
        st["ftt"] += float((buys * self.costs["ftt"] / 100).sum())
        st["noneur"] += float(((buys + sells) * self.costs["noneur"]).sum())


def weights_strategy(m, select, every: str, name: str) -> dict:
    """Strategia a pesi uguali sui titoli scelti da `select(i)` ai giorni di ribilanciamento."""
    close = m["Close"]
    rets = close.pct_change().fillna(0.0).to_numpy()
    rets = np.nan_to_num(rets)
    tickers = close.columns
    book = Book(close.index, tickers)
    reb = _rebalance_days(close.index, every)
    w = np.zeros(len(tickers))
    eq = 1.0
    for i in range(book.start, len(close.index)):
        if i > book.start:
            growth = w * (1 + rets[i])
            port = growth.sum() + (1 - w.sum())  # la parte non investita resta liquida
            eq *= port
            w = growth / port if port > 0 else w
        if i in reb or i == book.start:
            chosen = select(i)
            if chosen is KEEP:
                book.equity[i] = eq
                book.invested[i] = w.sum()
                continue
            target = np.zeros(len(tickers))
            if chosen is not None and len(chosen):
                target[chosen] = 1.0 / len(chosen)
            if np.abs(target - w).sum() > 1e-9:
                book.trade(i, target - w, eq)
            w = target
        book.equity[i] = eq
        book.invested[i] = w.sum()
    return finalize(book, name)


def slot_strategy(m, entries, exit_rule, slots: int, name: str, max_hold: int = 60) -> dict:
    """Strategia "a posizioni": al massimo `slots` titoli, ognuno con 1/slots del capitale.

    entries(i) -> [(colonna, prezzo d'ingresso)] in ordine di priorità;
    exit_rule(i, col, entry_price, days) -> prezzo di uscita o None per restare.
    """
    close = m["Close"].to_numpy()
    tickers = m["Close"].columns
    book = Book(m["Close"].index, tickers)
    cash = 1.0
    pos = {}  # col -> [quote, prezzo d'ingresso, sedute]
    for i in range(book.start, close.shape[0]):
        # uscite
        for col in list(pos):
            q, ep, d = pos[col]
            pos[col][2] = d + 1
            px = exit_rule(i, col, ep, d + 1)
            if px is None and (d + 1 >= max_hold or not np.isfinite(close[i, col])):
                px = close[i, col] if np.isfinite(close[i, col]) else ep
            if px is not None:
                value = q * px
                eq_now = cash + sum(qq * _px(close, i, c, e) for c, (qq, e, _) in pos.items())
                delta = np.zeros(len(tickers))
                delta[col] = -value / eq_now
                book.trade(i, delta, eq_now)
                cash += value
                del pos[col]
        # ingressi
        free = slots - len(pos)
        if free > 0:
            eq_now = cash + sum(q * _px(close, i, c, e) for c, (q, e, _) in pos.items())
            for col, ep in entries(i):
                if free <= 0:
                    break
                if col in pos or not np.isfinite(ep) or ep <= 0:
                    continue
                amount = min(eq_now / slots, cash)
                if amount <= 1e-6:
                    break
                delta = np.zeros(len(tickers))
                delta[col] = amount / eq_now
                book.trade(i, delta, eq_now)
                pos[col] = [amount / ep, ep, 0]
                cash -= amount
                free -= 1
        book.equity[i] = cash + sum(q * _px(close, i, c, e) for c, (q, e, _) in pos.items())
        book.invested[i] = 1 - cash / book.equity[i] if book.equity[i] > 0 else 0
    return finalize(book, name)


def _px(close, i, col, fallback):
    v = close[i, col]
    return v if np.isfinite(v) else fallback


def index_strategy(m, invested, name: str) -> dict:
    """Strategia su un ETF equiponderato dell'universo: dentro o fuori dal mercato (1 ordine a cambio)."""
    close = m["Close"]
    idx_ret = close.pct_change().mean(axis=1).fillna(0.0).to_numpy()
    book = Book(close.index, ["ETF"])
    book.costs = {"ftt": np.array([0.0]), "noneur": np.array([0.0]), "it": np.array([0.0])}  # ETF: niente Tobin tax
    eq, inside = 1.0, False
    for i in range(book.start, len(close.index)):
        if i > book.start and inside:
            eq *= 1 + idx_ret[i]
        want = bool(invested(i))
        if want != inside:
            book.trade(i, np.array([1.0 if want else -1.0]), eq)
            inside = want
        book.equity[i] = eq
        book.invested[i] = 1.0 if inside else 0.0
    return finalize(book, name)


def finalize(book: Book, name: str) -> dict:
    eq = pd.Series(book.equity[book.start:], index=book.index[book.start:])
    inv = pd.Series(book.invested[book.start:], index=book.index[book.start:])
    yearly = []
    for y, grp in eq.groupby(eq.index.year):
        start = eq[eq.index.year < y].iloc[-1] if (eq.index.year < y).any() else 1.0
        st = book.year_stats.get(y, {"orders": 0, "buy": 0.0, "sell": 0.0, "ftt": 0.0, "noneur": 0.0, "it_orders": 0})
        avg_eq = float(grp.mean())
        yearly.append({
            "year": int(y),
            "days": int(len(grp)),
            "ret": round(float(grp.iloc[-1] / start - 1) * 100, 3),
            "orders": st["orders"],
            "it_share": round(st["it_orders"] / st["orders"], 3) if st["orders"] else 0.0,
            "buy": round(st["buy"] / avg_eq, 4),  # volumi in multipli del capitale medio dell'anno
            "sell": round(st["sell"] / avg_eq, 4),
            "ftt": round(st["ftt"] / avg_eq, 6),
            "noneur": round(st["noneur"] / avg_eq, 4),
            "invested": round(float(inv[inv.index.year == y].mean()), 3),
        })
    rets = eq.pct_change().dropna()
    years = (eq.index[-1] - eq.index[0]).days / 365.25
    weekly = eq.resample("W-FRI").last().dropna()
    dd = (eq / eq.cummax() - 1).min()
    return {
        "name": name,
        "cagr": round(float(eq.iloc[-1] ** (1 / years) - 1) * 100, 2),
        "vol": round(float(rets.std() * math.sqrt(TRADING_DAYS)) * 100, 2),
        "max_dd": round(float(dd) * 100, 2),
        "orders_per_year": round(sum(y["orders"] for y in yearly) / years, 1),
        "yearly": yearly,
        "curve": {"d": [d.strftime("%Y-%m-%d") for d in weekly.index], "v": [round(float(v), 4) for v in weekly]},
    }


def rsi(close: np.ndarray, n: int) -> np.ndarray:
    delta = np.diff(close, axis=0, prepend=np.nan)
    up = pd.DataFrame(np.clip(delta, 0, None)).ewm(alpha=1 / n, adjust=False).mean().to_numpy()
    dn = pd.DataFrame(np.clip(-delta, 0, None)).ewm(alpha=1 / n, adjust=False).mean().to_numpy()
    with np.errstate(divide="ignore", invalid="ignore"):
        return 100 - 100 / (1 + up / dn)


def portfolio_strategies(m) -> list[dict]:
    close_df = m["Close"]
    close = close_df.to_numpy()
    n_days, n_tk = close.shape
    ret = close_df.pct_change()
    logp = np.log(close_df)
    mom = (logp.shift(21) - logp.shift(252)).to_numpy()  # 12 mesi saltando l'ultimo
    rev5 = (logp - logp.shift(5)).to_numpy()
    vol252 = ret.rolling(252, min_periods=200).std().to_numpy()
    hi52 = (close_df / close_df.rolling(252, min_periods=200).max()).to_numpy()
    sma200 = close_df.rolling(200, min_periods=200).mean().to_numpy()
    sma5 = close_df.rolling(5).mean().to_numpy()
    rsi2 = rsi(close, 2)
    idx_level = (1 + ret.mean(axis=1).fillna(0)).cumprod().to_numpy()
    idx_sma200 = pd.Series(idx_level).rolling(200, min_periods=200).mean().to_numpy()
    top = max(10, n_tk // 10)

    def best(values, i, k, largest=True):
        v = values[i]
        ok = np.isfinite(v) & np.isfinite(close[i])
        if ok.sum() < k:
            return None
        cand = np.flatnonzero(ok)
        order = np.argsort(v[cand])
        pick = order[-k:] if largest else order[:k]
        return cand[pick]

    all_ok = lambda i: np.flatnonzero(np.isfinite(close[i]))  # noqa: E731
    start = WARMUP

    out = []
    out.append(("buy_hold", weights_strategy(m, lambda i: all_ok(i) if i == start else KEEP, "M", "Compra e tieni")))
    out.append(("rebalance", weights_strategy(m, all_ok, "Q", "Pesi uguali, ribilanciato")))
    out.append(("momentum", weights_strategy(m, lambda i: best(mom, i, top), "M", "Momentum 12-1")))
    out.append(("low_vol", weights_strategy(m, lambda i: best(-vol252, i, n_tk // 5), "Q", "Bassa volatilità")))
    out.append(("high52", weights_strategy(m, lambda i: best(hi52, i, top), "M", "Vicini al massimo a 52 settimane")))
    out.append(("reversal", weights_strategy(m, lambda i: best(-rev5, i, top), "W", "Inversione settimanale")))
    out.append(("trend", weights_strategy(
        m, lambda i: np.flatnonzero(np.isfinite(sma200[i]) & (close[i] > sma200[i])), "M", "Trend: sopra la media a 200 giorni")))

    # strategie "a posizioni" (10 posizioni da 1/10 del capitale)
    def dip_entries(dip):
        prev = np.roll(close, 1, axis=0)

        def f(i):
            if i == 0:
                return []
            chg = close[i] / prev[i] - 1
            hit = np.flatnonzero(np.isfinite(chg) & (chg <= -dip / 100))
            order = np.argsort(chg[hit])  # prima i cali più forti
            return [(int(hit[k]), float(close[i, hit[k]])) for k in order]
        return f

    def target_exit(target, stop):
        def f(i, col, ep, d):
            px = close[i, col]
            if d <= 0 or not np.isfinite(px):
                return None
            if stop and px <= ep * (1 - stop / 100):
                return px
            if px >= ep * (1 + target / 100):
                return px
            return None
        return f

    out.append(("dip_5_10", slot_strategy(m, dip_entries(5), target_exit(10, 0), 10, "Compro a −5%, rivendo a +10%", max_hold=120)))
    out.append(("dip_7_5_s10", slot_strategy(m, dip_entries(7), target_exit(5, 10), 10, "Compro a −7%, rivendo a +5% (stop −10%)", max_hold=60)))

    def rsi_entries(i):
        ok = np.flatnonzero(np.isfinite(rsi2[i]) & (rsi2[i] < 10) & np.isfinite(sma200[i]) & (close[i] > sma200[i]))
        order = np.argsort(rsi2[i, ok])
        return [(int(ok[k]), float(close[i, ok[k]])) for k in order]

    def rsi_exit(i, col, ep, d):
        if d > 0 and np.isfinite(sma5[i, col]) and close[i, col] > sma5[i, col]:
            return close[i, col]
        return None

    out.append(("rsi2", slot_strategy(m, rsi_entries, rsi_exit, 10, "RSI(2) di Connors", max_hold=20)))

    # strategie su un ETF dell'intero universo
    month = close_df.index.month
    out.append(("etf_hold", index_strategy(m, lambda i: True, "ETF equiponderato (compra e tieni)")))
    out.append(("halloween", index_strategy(m, lambda i: month[i] in (11, 12, 1, 2, 3, 4), "Halloween: investito solo nov–apr")))
    out.append(("etf_trend", index_strategy(
        m, lambda i: bool(np.isfinite(idx_sma200[i]) and idx_level[i] > idx_sma200[i]), "ETF solo sopra la media a 200 giorni")))
    s = pd.Series(np.arange(n_days), index=close_df.index)
    per = close_df.index.to_period("M")
    first_days = s.groupby(per).min().to_numpy()
    last_days = s.groupby(per).max().to_numpy()
    tom = np.zeros(n_days, dtype=bool)
    for fd in first_days:
        tom[fd:fd + 3] = True
    for ld in last_days:
        tom[ld] = True
    out.append(("turn_of_month", index_strategy(m, lambda i: tom[i], "Fine/inizio mese")))
    return out


def lab_data(m) -> dict:
    """Dati per i consigli interattivi."""
    close = m["Close"]
    ret = close.pct_change()
    idx_ret = ret.mean(axis=1).fillna(0.0)
    rng = np.random.default_rng(42)
    valid_cols = np.flatnonzero(ret.notna().mean().to_numpy() > 0.95)
    r = ret.iloc[:, valid_cols].fillna(0.0).to_numpy()
    diversification = []
    for k in (1, 2, 3, 5, 8, 10, 15, 20, 30, 50, 100):
        vols = []
        for _ in range(300):
            pick = rng.choice(r.shape[1], size=min(k, r.shape[1]), replace=False)
            vols.append(r[:, pick].mean(axis=1).std() * math.sqrt(TRADING_DAYS) * 100)
        diversification.append({"k": k, "vol": round(float(np.mean(vols)), 2),
                                "p10": round(float(np.percentile(vols, 10)), 2), "p90": round(float(np.percentile(vols, 90)), 2)})
    # quanti titoli, da soli, hanno battuto l'indice equiponderato (Bessembinder)
    total = (close.iloc[-1] / close.apply(lambda s: s.dropna().iloc[0]) - 1).dropna()
    idx_total = float((1 + idx_ret).prod() - 1)
    return {
        "index": {"d": [d.strftime("%Y-%m-%d") for d in idx_ret.index], "r": [round(float(x), 5) for x in idx_ret]},
        "diversification": diversification,
        "stocks": {"n": int(len(total)), "beat_index": int((total > idx_total).sum()), "negative": int((total < 0).sum()),
                   "median": round(float(total.median() * 100), 1), "index": round(idx_total * 100, 1)},
    }


def run_strategies(cfg, store) -> dict:
    """Scarica lo storico dell'universo, calcola tutto e salva strategies.json nella cartella dati."""
    from . import data

    universe = store.read("universe.json")
    if not universe:
        raise RuntimeError("Universo non calcolato")
    tickers = [i["ticker"] for i in universe["items"]]
    frames = data.download_daily(tickers, period=f"{cfg.lookback_years}y", auto_adjust=True)
    result = build(frames)
    store.write("strategies.json", result)
    return result


def build(frames: dict[str, pd.DataFrame]) -> dict:
    m = matrices(frames)
    close = m["Close"]
    market_idx = (1 + close.pct_change().mean(axis=1).fillna(0)).cumprod().to_numpy()
    log.info("Griglia compro/rivendo...")
    grid = dip_grid(m, market_idx)
    log.info("Strategie di portafoglio...")
    strategies = {k: v for k, v in portfolio_strategies(m)}
    log.info("Dati per i consigli...")
    return {
        "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "period": {"start": close.index[0].date().isoformat(), "end": close.index[-1].date().isoformat()},
        "tickers": int(close.shape[1]),
        "dip": grid,
        "strategies": strategies,
        "lab": lab_data(m),
    }
