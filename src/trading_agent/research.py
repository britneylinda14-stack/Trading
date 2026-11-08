"""Parameter sweeps with an in-sample / out-of-sample split.

Every parameter combination runs as a portfolio on the in-sample period. Combinations
are ranked by in-sample Sharpe; the out-of-sample columns show how each one did on data
it was never tuned on. A robust strategy keeps most of its edge out of sample across many
neighbouring parameter sets, not just the single best one.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from .engine import BacktestResult, PortfolioBacktester
from .instruments import Instrument
from .metrics import compute_metrics
from .risk import RiskConfig
from .strategies import get_strategy

DEFAULT_GRIDS: dict[str, dict[str, list]] = {
    "ema_cross": {"fast": [20, 50, 100], "slow": [100, 200, 300], "atr_mult": [2.0, 3.0, 4.0]},
    "donchian": {"entry": [20, 55, 100], "exit": [10, 20], "atr_mult": [2.0, 3.0]},
    "mean_reversion": {
        "lookback": [10, 20, 40],
        "entry_z": [1.5, 2.0, 2.5],
        "max_er": [0.2, 0.3, 1.0],
    },
    "session_breakout": {
        "range_end": [6, 7, 8],
        "session_end": [12, 16, 20],
        "stop_mult": [0.5, 1.0],
    },
    "atm_pullback": {
        "swing": [3, 5],
        "fib_max": [0.618, 0.786],
        "divergence": [True, False],
        "tp_r": [2.0, 3.0],
    },
}

KEY_METRICS = ["sharpe", "cagr_pct", "max_drawdown_pct", "total_return_pct", "trades", "avg_r"]


def expand_grid(grid: dict[str, list]) -> list[dict]:
    keys = list(grid)
    return [dict(zip(keys, values, strict=True)) for values in itertools.product(*grid.values())]


def run_portfolio(
    instruments: list[Instrument],
    strategy: str,
    params: dict,
    data: dict[str, pd.DataFrame],
    risk: RiskConfig,
    calendar=None,
    flatten_on_events: bool = False,
    trade_from=None,
    trade_until=None,
) -> tuple[BacktestResult, dict]:
    strat = get_strategy(strategy, **params)
    sliced = data
    if trade_until is not None:
        cut = pd.Timestamp(trade_until)
        sliced = {k: v[v.index < cut] for k, v in data.items()}
    engine = PortfolioBacktester(
        [(inst, strat) for inst in instruments], risk, calendar, flatten_on_events
    )
    result = engine.run(sliced, trade_from)
    return result, compute_metrics(result)


@dataclass
class SweepResult:
    table: pd.DataFrame
    strategy: str
    split: pd.Timestamp

    @property
    def best(self) -> pd.Series:
        return self.table.iloc[0]

    def summary(self) -> str:
        t = self.table
        n = len(t)
        positive_is = (t["is_sharpe"] > 0).sum()
        positive_oos = (t["oos_sharpe"] > 0).sum()
        best = self.best
        param_cols = [c for c in t.columns if not c.startswith(("is_", "oos_"))]
        best_params = ", ".join(f"{c}={best[c]}" for c in param_cols)
        top = t.head(max(1, n // 5))
        lines = [
            f"## {self.strategy}: {n} parameter sets, split at {self.split.date()}",
            "",
            f"- Best in-sample: `{best_params}`: in-sample Sharpe {best['is_sharpe']:.2f} "
            f"(CAGR {best['is_cagr_pct']:.1f}%), out-of-sample Sharpe {best['oos_sharpe']:.2f} "
            f"(CAGR {best['oos_cagr_pct']:.1f}%, max DD {best['oos_max_drawdown_pct']:.1f}%)",
            f"- Sets with positive Sharpe: {positive_is}/{n} in-sample, {positive_oos}/{n} "
            "out-of-sample",
            f"- Top 20% by in-sample Sharpe: median out-of-sample Sharpe "
            f"{top['oos_sharpe'].median():.2f}",
            f"- All sets: median out-of-sample Sharpe {t['oos_sharpe'].median():.2f}",
        ]
        return "\n".join(lines)


def sweep(
    instruments: list[Instrument],
    strategy: str,
    data: dict[str, pd.DataFrame],
    split: str | pd.Timestamp,
    grid: dict[str, list] | None = None,
    risk: RiskConfig | None = None,
    calendar=None,
    flatten_on_events: bool = False,
    progress=None,
) -> SweepResult:
    risk = risk or RiskConfig()
    split = pd.Timestamp(split)
    first = min(df.index[0] for df in data.values())
    last = max(df.index[-1] for df in data.values())
    if not first < split < last:
        raise ValueError(
            f"split {split.date()} must fall inside the data range {first.date()} .. {last.date()}"
        )
    combos = expand_grid(grid or DEFAULT_GRIDS[strategy])
    rows = []
    for n, params in enumerate(combos, 1):
        try:
            get_strategy(strategy, **params)
        except ValueError:
            continue
        common = dict(risk=risk, calendar=calendar, flatten_on_events=flatten_on_events)
        _, ins = run_portfolio(instruments, strategy, params, data, trade_until=split, **common)
        _, oos = run_portfolio(instruments, strategy, params, data, trade_from=split, **common)
        row = dict(params)
        row.update({f"is_{k}": ins[k] for k in KEY_METRICS})
        row.update({f"oos_{k}": oos[k] for k in KEY_METRICS})
        rows.append(row)
        if progress:
            progress(n, len(combos), params)
    table = pd.DataFrame(rows).sort_values("is_sharpe", ascending=False, ignore_index=True)
    return SweepResult(table, strategy, split)


def write_sweep(result: SweepResult, out_dir: str | Path) -> Path:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    result.table.to_csv(out / "sweep.csv", index=False)
    (out / "summary.md").write_text(result.summary() + "\n")
    return out
