from datetime import date

import pytest

from actionzz.config import Config
from actionzz.detector import compute_quote, find_signals, market_crash_due, market_move

from .conftest import TODAY, bars


def test_quote_vs_yesterday_close():
    q = compute_quote("A.MI", bars([100, 102, 96.9]), TODAY)
    assert q.prev_close == 102
    assert q.pct == pytest.approx(-5.0)


def test_no_quote_when_today_missing():
    # festività: l'ultima barra è di ieri
    assert compute_quote("A.MI", bars([100, 102], end=date(2026, 9, 24)), TODAY) is None


def test_dividend_is_not_a_drop():
    # stacco di 4 su 100: il prezzo a 96 è invariato, non un calo del 4%
    q = compute_quote("A.MI", bars([100, 100, 96], dividends=[0, 0, 4.0]), TODAY)
    assert q.prev_close == 96
    assert q.pct == pytest.approx(0.0)


def test_low_and_volume_ratio():
    q = compute_quote("A.MI", bars([100, 100, 97], lows=[100, 100, 95], volumes=[1000, 1000, 3000]), TODAY)
    assert q.low_pct == pytest.approx(-5.0)
    assert q.volume / q.avg_volume_20d == pytest.approx(3.0)


def quotes(*pcts):
    out = []
    for i, p in enumerate(pcts):
        out.append(compute_quote(f"T{i}.MI", bars([100, 100, 100 * (1 + p / 100)]), TODAY))
    return out


def test_market_is_median():
    assert market_move(quotes(-1, 0, 5, -10, 1)) == pytest.approx(0.0)


def test_threshold_and_market_filter():
    cfg = Config(drop_threshold_pct=5, relative_threshold_pct=3)
    qs = quotes(-6, -5.5, -1)
    # mercato a -4%: -6 fa 2 punti peggio (filtrato), con mercato a -1% passa
    assert find_signals(qs, -4.0, cfg, {}) == []
    tickers = [s.quote.ticker for s in find_signals(qs, -1.0, cfg, {})]
    assert tickers == ["T0.MI", "T1.MI"]


def test_market_filter_off():
    cfg = Config(drop_threshold_pct=5, market_filter=False)
    assert len(find_signals(quotes(-6), -5.5, cfg, {})) == 1


def test_realert_only_if_drops_further():
    cfg = Config(drop_threshold_pct=5, realert_step_pct=2)
    already = {"T0.MI": {"pct": -6.0}}
    assert find_signals(quotes(-7.5), 0.0, cfg, already) == []
    sig = find_signals(quotes(-8.1), 0.0, cfg, already)
    assert len(sig) == 1 and sig[0].is_repeat and sig[0].previous_pct == -6.0


def test_market_crash_notice():
    cfg = Config(market_crash_pct=2.5, realert_step_pct=2)
    assert not market_crash_due(-2.0, cfg, None)
    assert market_crash_due(-2.6, cfg, None)
    assert not market_crash_due(-3.0, cfg, -2.6)
    assert market_crash_due(-4.7, cfg, -2.6)
