"""Grafico PNG del prezzo per le schede Telegram."""

from __future__ import annotations

import io

import pandas as pd

RED = "#d03b3b"
BLUE = "#2a78d6"
MUTED = "#898781"
GRID = "#e1e0d9"
INK = "#0b0b0b"


def price_chart(ticker: str, close: pd.Series, prev_close: float, price: float, currency: str = "") -> bytes:
    """Ultimi 6 mesi di chiusure, con la chiusura di ieri e il prezzo attuale."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    close = close.dropna()
    close = close[close.index >= close.index[-1] - pd.Timedelta(days=183)]
    fig, ax = plt.subplots(figsize=(8, 4), dpi=110)
    fig.patch.set_facecolor("#fcfcfb")
    ax.set_facecolor("#fcfcfb")
    ax.plot(close.index, close.values, color=BLUE, linewidth=2)
    ax.axhline(prev_close, color=MUTED, linewidth=1, linestyle="--")
    ax.annotate("chiusura ieri", (close.index[0], prev_close), xytext=(4, 4), textcoords="offset points",
                color=MUTED, fontsize=8, bbox={"facecolor": "#fcfcfb", "edgecolor": "none", "pad": 1})
    ax.scatter([close.index[-1]], [price], color=RED, s=40, zorder=3, edgecolors="#fcfcfb", linewidths=2)
    ax.annotate(f"{price:,.2f}".replace(",", "§").replace(".", ",").replace("§", "."), (close.index[-1], price),
                xytext=(-8, -14), textcoords="offset points", ha="right", color=INK, fontsize=9, fontweight="bold")
    ax.set_title(f"{ticker} · ultimi 6 mesi" + (f" ({currency})" if currency else ""), loc="left", fontsize=11, color=INK)
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color("#c3c2b7")
    ax.tick_params(colors=MUTED, labelsize=8, length=0)
    fig.autofmt_xdate()
    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png")
    plt.close(fig)
    return buf.getvalue()
