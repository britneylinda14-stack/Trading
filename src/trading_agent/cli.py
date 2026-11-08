from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from .data import load_csv, load_mt5_csv, load_yahoo
from .engine import Backtester
from .instruments import INSTRUMENTS, get_instrument
from .metrics import compute_metrics
from .report import write_report
from .risk import RiskConfig
from .strategies import STRATEGIES, get_strategy

SUMMARY_COLS = [
    "total_return_pct",
    "cagr_pct",
    "max_drawdown_pct",
    "sharpe",
    "trades",
    "win_rate_pct",
    "profit_factor",
    "avg_r",
]


def _parse_params(items: list[str]) -> dict:
    params = {}
    for item in items:
        key, _, value = item.partition("=")
        params[key] = json.loads(value)
    return params


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="trading-agent", description=__doc__)
    sub = p.add_subparsers(dest="command", required=True)

    bt = sub.add_parser("backtest", help="Run a backtest")
    bt.add_argument(
        "-i",
        "--instrument",
        nargs="+",
        default=["EUR_USD"],
        help=f"One or more of: {', '.join(INSTRUMENTS)}",
    )
    bt.add_argument("-s", "--strategy", default="ema_cross", choices=list(STRATEGIES))
    bt.add_argument(
        "-p",
        "--param",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help="Strategy parameter, e.g. -p fast=20 -p slow=100",
    )
    bt.add_argument("--start", default="2015-01-01")
    bt.add_argument("--end", default=None)
    bt.add_argument("--interval", default="1d", help="Yahoo interval: 1d, 1h, ...")
    bt.add_argument("--csv", help="Use a local CSV (time,open,high,low,close) instead of Yahoo")
    bt.add_argument("--mt5-csv", help="Use a MetaTrader 5 bars export instead of Yahoo")
    bt.add_argument("--equity", type=float, default=10_000)
    bt.add_argument("--risk", type=float, default=0.01, help="Risk per trade (fraction)")
    bt.add_argument("--max-daily-loss", type=float, default=0.03)
    bt.add_argument("--max-drawdown", type=float, default=0.25)
    bt.add_argument("--max-leverage", type=float, default=None)
    bt.add_argument("--take-profit-r", type=float, default=None)
    bt.add_argument("--out", default="reports")

    sub.add_parser("instruments", help="List supported instruments")
    return p


def cmd_backtest(args: argparse.Namespace) -> pd.DataFrame:
    if (args.csv or args.mt5_csv) and len(args.instrument) != 1:
        raise SystemExit("--csv/--mt5-csv require exactly one --instrument")
    risk = RiskConfig(
        initial_equity=args.equity,
        risk_per_trade=args.risk,
        max_daily_loss=args.max_daily_loss,
        max_drawdown=args.max_drawdown,
        max_leverage=args.max_leverage,
        take_profit_r=args.take_profit_r,
    )
    params = _parse_params(args.param)
    rows = {}
    for name in args.instrument:
        inst = get_instrument(name)
        if args.mt5_csv:
            bars = load_mt5_csv(args.mt5_csv)
        elif args.csv:
            bars = load_csv(args.csv)
        else:
            bars = load_yahoo(inst, args.start, args.end, args.interval)
        result = Backtester(inst, get_strategy(args.strategy, **params), risk).run(bars)
        metrics = compute_metrics(result)
        out = write_report(result, metrics, bars, Path(args.out) / f"{inst.name}_{args.strategy}")
        rows[inst.name] = metrics
        for event in result.events:
            print(f"[{inst.name}] {event}")
        if result.skipped_signals:
            print(
                f"[{inst.name}] warning: {result.skipped_signals} signals skipped because the "
                "risk budget was smaller than 1 unit; raise --equity or --risk"
            )
        print(
            f"[{inst.name}] {len(bars)} bars {bars.index[0].date()} -> "
            f"{bars.index[-1].date()} | report: {out}"
        )
    table = pd.DataFrame(rows).T[SUMMARY_COLS]
    with pd.option_context(
        "display.float_format", "{:,.2f}".format, "display.width", 200, "display.max_columns", None
    ):
        print()
        print(table)
    return table


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    if args.command == "backtest":
        cmd_backtest(args)
    elif args.command == "instruments":
        for inst in INSTRUMENTS.values():
            print(
                f"{inst.name:10} {inst.kind:7} yahoo={inst.yahoo_symbol:9} "
                f"spread={inst.spread} max_leverage={inst.max_leverage}:1"
            )


if __name__ == "__main__":
    main()
