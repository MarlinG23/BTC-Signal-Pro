"""
Parameter sweep logic — research only, not used by live trading.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict
from typing import Optional

import pandas as pd

from signals.backtester import BacktestEngine, BacktestOptions, BacktestResult

DEFAULT_FEE_PCT = 0.04


def base_options(fee_pct: float = DEFAULT_FEE_PCT) -> BacktestOptions:
    return BacktestOptions(
        taker_fee_pct=fee_pct,
        gate_mode="full",
        confidence_threshold=70.0,
        min_indicators=3,
        min_tp_pct=0.005,
        min_sl_pct=0.003,
    )


def _engine_key(options: BacktestOptions) -> tuple:
    return (
        options.confidence_threshold,
        options.min_indicators,
        options.min_tp_pct,
        options.min_sl_pct,
    )


def _run_variant(
    name: str,
    df: pd.DataFrame,
    signals: list,
    df_4h: Optional[pd.DataFrame],
    fg_history: Optional[list],
    options: BacktestOptions,
    *,
    trend_cache: Optional[tuple[dict, list]] = None,
    fg_cache: Optional[tuple[dict, list]] = None,
) -> dict:
    engine = BacktestEngine()
    result = engine.run_from_signals(
        df,
        signals,
        df_4h=df_4h,
        fg_history=fg_history,
        options=options,
        _trend_cache=trend_cache,
        _fg_cache=fg_cache,
    )
    return {
        "name": name,
        "options": asdict(options),
        "1m_only": BacktestResult.metrics_dict(result, gated=False),
        "gated": BacktestResult.metrics_dict(result, gated=True) if result.has_gated_run else None,
    }


def build_scenarios(fee_pct: float = DEFAULT_FEE_PCT) -> list[tuple[str, BacktestOptions]]:
    base = base_options(fee_pct)
    scenarios: list[tuple[str, BacktestOptions]] = [
        ("baseline_live_gates", deepcopy(base)),
        (
            "a_4h_trend_gate_only",
            BacktestOptions(**{**asdict(base), "gate_mode": "4h_only"}),
        ),
        (
            "b_fg_filter_only",
            BacktestOptions(**{**asdict(base), "gate_mode": "fg_only"}),
        ),
        (
            "c_wider_tp_sl",
            BacktestOptions(
                **{**asdict(base), "min_tp_pct": 0.01, "min_sl_pct": 0.005}
            ),
        ),
        (
            "d_confidence_80",
            BacktestOptions(**{**asdict(base), "confidence_threshold": 80.0}),
        ),
        (
            "e_min_indicators_4",
            BacktestOptions(**{**asdict(base), "min_indicators": 4}),
        ),
    ]

    combo_defs = [
        ("combo_4h_only_wider_tp_sl", {"gate_mode": "4h_only", "min_tp_pct": 0.01, "min_sl_pct": 0.005}),
        ("combo_fg_only_wider_tp_sl", {"gate_mode": "fg_only", "min_tp_pct": 0.01, "min_sl_pct": 0.005}),
        ("combo_full_wider_tp_sl_conf80", {"min_tp_pct": 0.01, "min_sl_pct": 0.005, "confidence_threshold": 80.0}),
        ("combo_full_wider_tp_sl_min4", {"min_tp_pct": 0.01, "min_sl_pct": 0.005, "min_indicators": 4}),
        ("combo_4h_only_conf80", {"gate_mode": "4h_only", "confidence_threshold": 80.0}),
        ("combo_fg_only_conf80", {"gate_mode": "fg_only", "confidence_threshold": 80.0}),
        ("combo_no_gates_wider_tp_sl", {"gate_mode": "none", "min_tp_pct": 0.01, "min_sl_pct": 0.005}),
        (
            "combo_all_signal_tweaks_full_gates",
            {
                "min_tp_pct": 0.01,
                "min_sl_pct": 0.005,
                "confidence_threshold": 80.0,
                "min_indicators": 4,
            },
        ),
    ]
    for name, overrides in combo_defs:
        opts = deepcopy(base)
        for k, v in overrides.items():
            setattr(opts, k, v)
        scenarios.append((name, opts))

    return scenarios


def build_combo_scenarios(fee_pct: float = DEFAULT_FEE_PCT) -> list[tuple[str, BacktestOptions]]:
    """Combination variants (everything after the six isolated tests)."""
    return build_scenarios(fee_pct)[6:]


def run_param_sweep(
    df: pd.DataFrame,
    df_4h: Optional[pd.DataFrame],
    fg_history: Optional[list],
    *,
    days: int = 30,
    fee_pct: float = DEFAULT_FEE_PCT,
    isolated_only: bool = False,
    combos_only: bool = False,
) -> dict:
    if isolated_only and combos_only:
        raise ValueError("isolated_only and combos_only are mutually exclusive")
    all_scenarios = build_scenarios(fee_pct)
    if isolated_only:
        scenarios = all_scenarios[:6]
    elif combos_only:
        scenarios = all_scenarios[6:]
    else:
        scenarios = all_scenarios
    engine = BacktestEngine()

    trend_cache = (
        engine._build_4h_trend_timeline(df_4h) if df_4h is not None else None
    )
    fg_cache = engine._build_fg_lookup(fg_history) if fg_history else None

    signal_cache: dict[tuple, list] = {}
    results = []
    for name, opts in scenarios:
        key = _engine_key(opts)
        if key not in signal_cache:
            _, signal_cache[key] = engine.collect_signals(df, opts)
        results.append(
            _run_variant(
                name,
                df,
                signal_cache[key],
                df_4h,
                fg_history,
                opts,
                trend_cache=trend_cache,
                fg_cache=fg_cache,
            )
        )

    profitable_gated = [
        {"name": r["name"], "gated": r["gated"]}
        for r in results
        if r["gated"] and r["gated"]["total_return_pct"] > 0
    ]
    return {
        "dataset": {
            "days": days,
            "candles_1m": len(df),
            "candles_4h": len(df_4h) if df_4h is not None else 0,
            "fg_days": len(fg_history) if fg_history else 0,
            "taker_fee_pct_per_side": fee_pct,
            "oldest_1m": df.index.min().isoformat() if len(df) else None,
            "newest_1m": df.index.max().isoformat() if len(df) else None,
        },
        "scenarios": results,
        "profitable_gated_with_fees": profitable_gated,
    }


def build_quality_scenarios(fee_pct: float = DEFAULT_FEE_PCT) -> list[tuple[str, BacktestOptions]]:
    """Seven scenarios: isolated quality tweaks + combined (user research set)."""
    base = asdict(base_options(fee_pct))
    return [
        ("baseline_live", BacktestOptions(**base)),
        ("a_wider_tp_1p5pct", BacktestOptions(**{**base, "min_tp_pct": 0.015})),
        ("b_wider_sl_0p8pct", BacktestOptions(**{**base, "min_sl_pct": 0.008})),
        ("c_confidence_80", BacktestOptions(**{**base, "confidence_threshold": 80.0})),
        ("d_min_indicators_4", BacktestOptions(**{**base, "min_indicators": 4})),
        (
            "e_all_four_combined",
            BacktestOptions(
                **{
                    **base,
                    "min_tp_pct": 0.015,
                    "min_sl_pct": 0.008,
                    "confidence_threshold": 80.0,
                    "min_indicators": 4,
                }
            ),
        ),
        (
            "e_combined_no_gates",
            BacktestOptions(
                **{
                    **base,
                    "gate_mode": "none",
                    "min_tp_pct": 0.015,
                    "min_sl_pct": 0.008,
                    "confidence_threshold": 80.0,
                    "min_indicators": 4,
                }
            ),
        ),
    ]


def _compact_row(name: str, opts: BacktestOptions, result: BacktestResult) -> dict:
    row = {
        "name": name,
        "gate_mode": opts.gate_mode,
        "1m_signals": result.total_signals,
        "1m_return_pct": round(result.total_return_pct, 4),
        "1m_win_rate_pct": round(result.win_rate_pct, 2),
        "1m_profit_factor": round(result.profit_factor, 4),
    }
    if result.has_gated_run:
        row.update(
            {
                "gated_signals": result.gated_total_signals,
                "gated_return_pct": round(result.gated_total_return_pct, 4),
                "gated_win_rate_pct": round(result.gated_win_rate_pct, 2),
                "gated_profit_factor": round(result.gated_profit_factor, 4),
            }
        )
    else:
        row.update(
            {
                "gated_signals": result.total_signals,
                "gated_return_pct": round(result.total_return_pct, 4),
                "gated_win_rate_pct": round(result.win_rate_pct, 2),
                "gated_profit_factor": round(result.profit_factor, 4),
            }
        )
    return row


def run_quality_sweep(
    df: pd.DataFrame,
    df_4h: Optional[pd.DataFrame],
    fg_history: Optional[list],
    *,
    days: int = 30,
    fee_pct: float = DEFAULT_FEE_PCT,
) -> dict:
    """Fast sweep: load data once, cache signals per engine config, reuse 4H/F&G."""
    engine = BacktestEngine()
    trend_cache = engine._build_4h_trend_timeline(df_4h) if df_4h is not None else None
    fg_cache = engine._build_fg_lookup(fg_history) if fg_history else None
    signal_cache: dict[tuple, list] = {}
    results = []

    for name, opts in build_quality_scenarios(fee_pct):
        key = _engine_key(opts)
        if key not in signal_cache:
            _, signal_cache[key] = engine.collect_signals(df, opts)
        result = engine.run_from_signals(
            df,
            signal_cache[key],
            df_4h=df_4h,
            fg_history=fg_history,
            options=opts,
            _trend_cache=trend_cache,
            _fg_cache=fg_cache,
        )
        results.append(_compact_row(name, opts, result))

    profitable_1m = [r for r in results if r["1m_return_pct"] > 0]
    profitable_gated = [r for r in results if r["gated_return_pct"] > 0]

    return {
        "dataset": {
            "days": days,
            "candles_1m": len(df),
            "candles_4h": len(df_4h) if df_4h is not None else 0,
            "fg_days": len(fg_history) if fg_history else 0,
            "taker_fee_pct_per_side": fee_pct,
        },
        "results": results,
        "profitable_1m_with_fees": profitable_1m,
        "profitable_gated_with_fees": profitable_gated,
        "any_profitable_with_fees": bool(profitable_1m or profitable_gated),
    }
