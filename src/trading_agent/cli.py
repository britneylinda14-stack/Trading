from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from .calendar import EventCalendar
from .data import load_csv, load_mt5_csv, load_yahoo
from .engine import PortfolioBacktester
from .instruments import INSTRUMENTS, get_instrument
from .metrics import compute_metrics, per_instrument
from .report import write_report
from .research import DEFAULT_GRIDS, sweep, write_sweep
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
TABLE_FMT = ("display.float_format", "{:,.2f}".format, "display.width", 200)


def _parse_params(items: list[str]) -> dict:
    params = {}
    for item in items:
        key, _, value = item.partition("=")
        params[key] = json.loads(value)
    return params


def _parse_grid(items: list[str]) -> dict[str, list] | None:
    if not items:
        return None
    grid = {}
    for item in items:
        key, _, values = item.partition("=")
        grid[key] = [json.loads(v) for v in values.split(",")]
    return grid


def _add_common(p: argparse.ArgumentParser) -> None:
    p.add_argument(
        "-i",
        "--instrument",
        nargs="+",
        default=["EUR_USD"],
        help=f"One or more of: {', '.join(INSTRUMENTS)}, or 'all'",
    )
    p.add_argument("-s", "--strategy", default="ema_cross", choices=list(STRATEGIES))
    p.add_argument("--start", default="2010-01-01")
    p.add_argument("--end", default=None)
    p.add_argument("--interval", default="1d", help="Yahoo interval: 1d, 1h, ...")
    p.add_argument("--csv", help="Use a local CSV (time,open,high,low,close) instead of Yahoo")
    p.add_argument("--mt5-csv", help="Use a MetaTrader 5 bars export instead of Yahoo")
    p.add_argument("--equity", type=float, default=10_000)
    p.add_argument("--risk", type=float, default=0.01, help="Risk per trade (fraction)")
    p.add_argument("--max-open-risk", type=float, default=0.05)
    p.add_argument("--max-daily-loss", type=float, default=0.03)
    p.add_argument("--max-drawdown", type=float, default=0.25)
    p.add_argument("--max-leverage", type=float, default=None)
    p.add_argument("--take-profit-r", type=float, default=None)
    p.add_argument(
        "--news-filter",
        action="store_true",
        help="No new entries around FOMC, CPI and NFP releases",
    )
    p.add_argument("--flatten-on-events", action="store_true", help="Also close open trades")
    p.add_argument("--news-window", type=float, default=2.0, help="Hours before/after event")
    p.add_argument("--events-csv", help="Extra events CSV: date[,time_et],event[,currency]")
    p.add_argument("--out", default="reports")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="trading-agent")
    sub = p.add_subparsers(dest="command", required=True)

    bt = sub.add_parser("backtest", help="Run a backtest")
    _add_common(bt)
    bt.add_argument(
        "-p",
        "--param",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help="Strategy parameter, e.g. -p fast=20 -p slow=100",
    )
    bt.add_argument(
        "--portfolio",
        action="store_true",
        help="Trade all instruments together with shared equity and risk budget",
    )

    rs = sub.add_parser("research", help="Parameter sweep with out-of-sample validation")
    _add_common(rs)
    rs.add_argument("--split", default="2020-01-01", help="Out-of-sample start date")
    rs.add_argument(
        "-g",
        "--grid",
        action="append",
        default=[],
        metavar="KEY=V1,V2",
        help="Override the default grid, e.g. -g entry=20,55 -g exit=10,20",
    )

    sub.add_parser("instruments", help="List supported instruments")
    return p


def _instruments(args) -> list:
    names = list(INSTRUMENTS) if args.instrument == ["all"] else args.instrument
    if (args.csv or args.mt5_csv) and len(names) != 1:
        raise SystemExit("--csv/--mt5-csv require exactly one --instrument")
    return [get_instrument(n) for n in names]


def _load(inst, args) -> pd.DataFrame:
    if args.mt5_csv:
        return load_mt5_csv(args.mt5_csv)
    if args.csv:
        return load_csv(args.csv)
    return load_yahoo(inst, args.start, args.end, args.interval)


def _risk(args) -> RiskConfig:
    try:
        return _build_risk(args)
    except ValueError as exc:
        raise SystemExit(f"error: {exc}") from None


def _build_risk(args) -> RiskConfig:
    return RiskConfig(
        initial_equity=args.equity,
        risk_per_trade=args.risk,
        max_open_risk=args.max_open_risk,
        max_daily_loss=args.max_daily_loss,
        max_drawdown=args.max_drawdown,
        max_leverage=args.max_leverage,
        take_profit_r=args.take_profit_r,
    )


def _calendar(args) -> EventCalendar | None:
    if not (args.news_filter or args.flatten_on_events):
        return None
    window = pd.Timedelta(hours=args.news_window)
    return EventCalendar.default(extra_csv=args.events_csv, before=window, after=window)


def _report_run(name, result, bars, args) -> dict:
    metrics = compute_metrics(result)
    out = write_report(result, metrics, bars, Path(args.out) / f"{name}_{args.strategy}")
    for event in result.events:
        print(f"[{name}] {event}")
    if result.skipped_signals:
        print(
            f"[{name}] warning: {result.skipped_signals} signals skipped because the "
            "risk budget allowed less than 1 unit; raise --equity or --risk"
        )
    if result.blackout_skips:
        print(f"[{name}] {result.blackout_skips} entries blocked by the news filter")
    print(f"[{name}] report: {out}")
    return metrics


def cmd_backtest(args: argparse.Namespace) -> pd.DataFrame:
    risk, calendar = _risk(args), _calendar(args)
    strategy = get_strategy(args.strategy, **_parse_params(args.param))
    instruments = _instruments(args)
    data = {inst.name: _load(inst, args) for inst in instruments}
    rows = {}
    if args.portfolio:
        engine = PortfolioBacktester(
            [(inst, strategy) for inst in instruments], risk, calendar, args.flatten_on_events
        )
        result = engine.run(data)
        rows["PORTFOLIO"] = _report_run("PORTFOLIO", result, None, args)
        with pd.option_context(*TABLE_FMT):
            print()
            print(per_instrument(result))
    else:
        for inst in instruments:
            engine = PortfolioBacktester([(inst, strategy)], risk, calendar, args.flatten_on_events)
            result = engine.run({inst.name: data[inst.name]})
            rows[inst.name] = _report_run(inst.name, result, data[inst.name], args)
    table = pd.DataFrame(rows).T[SUMMARY_COLS]
    with pd.option_context(*TABLE_FMT, "display.max_columns", None):
        print()
        print(table)
    return table


def cmd_research(args: argparse.Namespace):
    instruments = _instruments(args)
    data = {inst.name: _load(inst, args) for inst in instruments}
    grid = _parse_grid(args.grid) or DEFAULT_GRIDS[args.strategy]

    def progress(n, total, params):
        print(f"  [{n}/{total}] {params}", flush=True)

    try:
        result = _run_sweep(args, instruments, data, grid, progress)
    except ValueError as exc:
        raise SystemExit(f"error: {exc}") from None
    out = write_sweep(result, Path(args.out) / "research" / args.strategy)
    _print_sweep(result, out)
    return result


def _run_sweep(args, instruments, data, grid, progress):
    return sweep(
        instruments,
        args.strategy,
        data,
        args.split,
        grid,
        _risk(args),
        _calendar(args),
        args.flatten_on_events,
        progress,
    )


def _print_sweep(result, out) -> None:
    with pd.option_context(*TABLE_FMT, "display.max_columns", None):
        print()
        print(result.table.head(10))
    print()
    print(result.summary())
    print(f"\nfull table: {out / 'sweep.csv'}")


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    if args.command == "backtest":
        cmd_backtest(args)
    elif args.command == "research":
        cmd_research(args)
    elif args.command == "instruments":
        for inst in INSTRUMENTS.values():
            print(
                f"{inst.name:10} {inst.kind:7} yahoo={inst.yahoo_symbol:9} "
                f"spread={inst.spread} max_leverage={inst.max_leverage}:1"
            )


if __name__ == "__main__":
    main()
