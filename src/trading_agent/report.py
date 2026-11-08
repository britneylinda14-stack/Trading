from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

from .engine import BacktestResult  # noqa: E402
from .metrics import drawdown  # noqa: E402


def write_report(
    result: BacktestResult, metrics: dict, bars: pd.DataFrame, out_dir: str | Path
) -> Path:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    result.trades_frame().to_csv(out / "trades.csv", index=False)
    result.equity.to_csv(out / "equity.csv")
    (out / "summary.json").write_text(
        json.dumps({"metrics": metrics, "events": result.events}, indent=2, default=str)
    )

    fig, axes = plt.subplots(
        3, 1, figsize=(12, 9), sharex=True, gridspec_kw={"height_ratios": [2, 2, 1]}
    )
    title = f"{result.instrument.name} | {result.strategy}"
    axes[0].plot(bars.index, bars["close"], color="#555", lw=0.8)
    for t in result.trades:
        color = "#1a9850" if t.direction > 0 else "#d73027"
        axes[0].axvspan(t.entry_time, t.exit_time, color=color, alpha=0.12, lw=0)
    axes[0].set_title(f"{title} - price (green=long, red=short)")
    axes[1].plot(result.equity.index, result.equity, color="#2166ac")
    axes[1].set_title(
        f"Equity  return {metrics['total_return_pct']:.1f}%  "
        f"CAGR {metrics['cagr_pct']:.1f}%  Sharpe {metrics['sharpe']:.2f}"
    )
    dd = drawdown(result.equity) * 100
    axes[2].fill_between(dd.index, dd, 0, color="#b2182b", alpha=0.5)
    axes[2].set_title(f"Drawdown %  (max {metrics['max_drawdown_pct']:.1f}%)")
    for ax in axes:
        ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(out / "equity.png", dpi=110)
    plt.close(fig)
    return out
