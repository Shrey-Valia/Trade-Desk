"""Cross-trade analytics for the Trade Desk journal.

Pure functions over a list of Trade ORM rows (or any iterable of dict-
likes with the right fields). The router wraps these in a single GET
endpoint that the frontend hits.

Metrics are deliberately the standard journal vocabulary — same
definitions a trader sees in TradeZella / TraderSync / OptionsPro:

  Win rate            = wins / closed
  Net P&L             = Σ realized_pnl (closed only)
  Profit factor       = Σ wins / |Σ losses|        (∞ when no losers)
  Average winner      = Σ wins / count(wins)
  Average loser       = Σ losses / count(losers)   (negative value)
  Expectancy          = Σ realized_pnl / closed
  Avg R               = Σ r_multiple / count(R-positions)

Open trades are excluded from realized-P&L math (their unrealized P&L
lives on the chart, not in the journal aggregates).
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Iterable

from models.trade import Trade


# ---------------------------------------------------------------------------
# Public dataclasses — mirror what the frontend consumes via schemas/.
# ---------------------------------------------------------------------------


@dataclass
class KpiBlock:
    total_trades: int
    open_trades: int
    closed_trades: int
    win_rate: float | None              # 0..1 fraction of closed
    net_pnl: float
    profit_factor: float | None
    avg_winner: float | None
    avg_loser: float | None             # negative
    expectancy: float | None            # avg $ per trade
    avg_r: float | None
    largest_winner: float | None
    largest_loser: float | None


@dataclass
class StrategyBucket:
    strategy: str
    trades: int
    closed: int
    win_rate: float | None
    net_pnl: float
    avg_pnl: float | None
    profit_factor: float | None
    avg_r: float | None


@dataclass
class DteBucket:
    label: str                          # "0-7", "8-21", "22-45", "45+"
    trades: int
    win_rate: float | None
    avg_pnl: float | None
    net_pnl: float


@dataclass
class MistakeBucket:
    tag: str
    trades: int
    net_pnl: float                      # cumulative P&L on trades carrying the tag
    avg_pnl: float | None
    total_r: float | None               # cumulative R for those trades


@dataclass
class EquityPoint:
    date: str                           # ISO date
    cumulative_pnl: float


@dataclass
class EquityCurve:
    points: list[EquityPoint] = field(default_factory=list)
    max_drawdown: float = 0.0
    peak_pnl: float = 0.0
    final_pnl: float = 0.0


@dataclass
class JournalAnalytics:
    kpis: KpiBlock
    by_strategy: list[StrategyBucket]
    by_dte: list[DteBucket]
    by_mistake: list[MistakeBucket]
    equity: EquityCurve


# ---------------------------------------------------------------------------
# Helpers — kept private. Tested via the public compose function above.
# ---------------------------------------------------------------------------


def _is_closed(t: Trade) -> bool:
    return t.status == "closed" and t.realized_pnl is not None


def _safe_div(num: float, den: float) -> float | None:
    if den == 0:
        return None
    return num / den


def _nearest_dte_at_entry(t: Trade) -> int | None:
    """DTE-at-entry = (nearest leg expiry − entry_date), in calendar days."""
    if t.entry_date is None:
        return None
    legs = t.legs or []
    if not legs:
        return None
    entry_d = t.entry_date.date() if isinstance(t.entry_date, datetime) else t.entry_date
    nearest: int | None = None
    for leg in legs:
        exp_raw = leg.get("expiry")
        if exp_raw is None:
            continue
        if isinstance(exp_raw, str):
            try:
                exp_d = date.fromisoformat(exp_raw)
            except ValueError:
                continue
        elif isinstance(exp_raw, date):
            exp_d = exp_raw
        else:
            continue
        diff = (exp_d - entry_d).days
        if nearest is None or diff < nearest:
            nearest = diff
    return nearest


def _dte_bucket(dte: int) -> str:
    if dte < 0:
        return "expired"
    if dte <= 7:
        return "0-7"
    if dte <= 21:
        return "8-21"
    if dte <= 45:
        return "22-45"
    return "45+"


# Order labels for the DTE breakdown so the frontend can render in a
# sensible left-to-right progression.
DTE_BUCKET_ORDER = ("0-7", "8-21", "22-45", "45+", "expired")


# ---------------------------------------------------------------------------
# Composers
# ---------------------------------------------------------------------------


def compute_kpis(trades: Iterable[Trade]) -> KpiBlock:
    trades = list(trades)
    closed = [t for t in trades if _is_closed(t)]
    open_count = sum(1 for t in trades if t.status == "open")

    wins = [t for t in closed if (t.realized_pnl or 0) > 0]
    losers = [t for t in closed if (t.realized_pnl or 0) < 0]

    sum_wins = sum((t.realized_pnl or 0) for t in wins)
    sum_losses_abs = abs(sum((t.realized_pnl or 0) for t in losers))
    net_pnl = sum((t.realized_pnl or 0) for t in closed)

    win_rate = _safe_div(len(wins), len(closed))
    profit_factor: float | None
    if not closed:
        profit_factor = None
    elif sum_losses_abs == 0:
        profit_factor = math.inf if sum_wins > 0 else None
    else:
        profit_factor = sum_wins / sum_losses_abs

    avg_winner = _safe_div(sum_wins, len(wins))
    avg_loser = _safe_div(-sum_losses_abs, len(losers))
    expectancy = _safe_div(net_pnl, len(closed))

    r_values = [t.r_multiple for t in closed if t.r_multiple is not None]
    avg_r = _safe_div(sum(r_values), len(r_values)) if r_values else None

    largest_winner = max((t.realized_pnl or 0) for t in wins) if wins else None
    largest_loser = min((t.realized_pnl or 0) for t in losers) if losers else None

    return KpiBlock(
        total_trades=len(trades),
        open_trades=open_count,
        closed_trades=len(closed),
        win_rate=win_rate,
        net_pnl=net_pnl,
        profit_factor=(
            None if profit_factor is None
            else (float("inf") if math.isinf(profit_factor) else float(profit_factor))
        ),
        avg_winner=avg_winner,
        avg_loser=avg_loser,
        expectancy=expectancy,
        avg_r=avg_r,
        largest_winner=largest_winner,
        largest_loser=largest_loser,
    )


def compute_by_strategy(trades: Iterable[Trade]) -> list[StrategyBucket]:
    """One row per distinct strategy. Open trades count in `trades`
    but only closed trades drive the P&L metrics."""
    by_strat: dict[str, list[Trade]] = defaultdict(list)
    for t in trades:
        by_strat[t.strategy].append(t)

    out: list[StrategyBucket] = []
    for strat, ts in by_strat.items():
        closed = [t for t in ts if _is_closed(t)]
        wins = [t for t in closed if (t.realized_pnl or 0) > 0]
        losers = [t for t in closed if (t.realized_pnl or 0) < 0]
        sum_wins = sum((t.realized_pnl or 0) for t in wins)
        sum_losses_abs = abs(sum((t.realized_pnl or 0) for t in losers))
        net = sum((t.realized_pnl or 0) for t in closed)

        win_rate = _safe_div(len(wins), len(closed))
        avg_pnl = _safe_div(net, len(closed))
        if not closed:
            pf: float | None = None
        elif sum_losses_abs == 0:
            pf = math.inf if sum_wins > 0 else None
        else:
            pf = sum_wins / sum_losses_abs

        r_values = [t.r_multiple for t in closed if t.r_multiple is not None]
        avg_r = _safe_div(sum(r_values), len(r_values)) if r_values else None

        out.append(StrategyBucket(
            strategy=strat,
            trades=len(ts),
            closed=len(closed),
            win_rate=win_rate,
            net_pnl=net,
            avg_pnl=avg_pnl,
            profit_factor=(
                None if pf is None
                else (float("inf") if math.isinf(pf) else float(pf))
            ),
            avg_r=avg_r,
        ))

    # Sort by net P&L descending so the strongest strategies surface first.
    out.sort(key=lambda b: b.net_pnl, reverse=True)
    return out


def compute_by_dte(trades: Iterable[Trade]) -> list[DteBucket]:
    """Bucket CLOSED trades by their entry-time DTE, return one row per
    bucket in canonical order. Open trades are excluded from the math
    but counted in `trades` if you want a count column."""
    by_bucket: dict[str, list[Trade]] = defaultdict(list)
    for t in trades:
        if not _is_closed(t):
            continue
        dte = _nearest_dte_at_entry(t)
        if dte is None:
            continue
        by_bucket[_dte_bucket(dte)].append(t)

    rows: list[DteBucket] = []
    for label in DTE_BUCKET_ORDER:
        ts = by_bucket.get(label, [])
        if not ts:
            # Still emit a zero-row so the chart shows the empty bucket.
            rows.append(DteBucket(
                label=label, trades=0, win_rate=None, avg_pnl=None, net_pnl=0.0,
            ))
            continue
        wins = [t for t in ts if (t.realized_pnl or 0) > 0]
        net = sum((t.realized_pnl or 0) for t in ts)
        rows.append(DteBucket(
            label=label,
            trades=len(ts),
            win_rate=_safe_div(len(wins), len(ts)),
            avg_pnl=_safe_div(net, len(ts)),
            net_pnl=net,
        ))
    return rows


def compute_by_mistake(trades: Iterable[Trade]) -> list[MistakeBucket]:
    """One row per mistake tag that appears on ≥1 CLOSED trade.

    Total P&L / R per tag is what makes this view useful: it answers
    'what behavior is costing me money'. A single trade with two tags
    contributes to BOTH buckets (the trader was doing two things wrong)."""
    by_tag: dict[str, list[Trade]] = defaultdict(list)
    for t in trades:
        if not _is_closed(t):
            continue
        for tag in t.mistake_tags:
            by_tag[tag].append(t)

    out: list[MistakeBucket] = []
    for tag, ts in by_tag.items():
        net = sum((t.realized_pnl or 0) for t in ts)
        r_values = [t.r_multiple for t in ts if t.r_multiple is not None]
        out.append(MistakeBucket(
            tag=tag,
            trades=len(ts),
            net_pnl=net,
            avg_pnl=_safe_div(net, len(ts)),
            total_r=sum(r_values) if r_values else None,
        ))

    # Sort by most-costly (lowest net_pnl) first — the leak the trader
    # most needs to address sits at the top.
    out.sort(key=lambda b: b.net_pnl)
    return out


def compute_equity_curve(trades: Iterable[Trade]) -> EquityCurve:
    """Cumulative realized P&L sorted by exit_date, plus max drawdown.

    Trades without an exit_date are skipped (open or no-exit-recorded).
    Drawdown is the largest peak-to-trough decline in cumulative P&L."""
    closed = [
        t for t in trades
        if _is_closed(t) and t.exit_date is not None
    ]
    closed.sort(key=lambda t: t.exit_date or datetime.min.replace(tzinfo=timezone.utc))

    points: list[EquityPoint] = []
    cumulative = 0.0
    peak = 0.0
    max_dd = 0.0
    for t in closed:
        cumulative += float(t.realized_pnl or 0)
        exit_d = (
            t.exit_date.date().isoformat()
            if isinstance(t.exit_date, datetime)
            else str(t.exit_date)
        )
        points.append(EquityPoint(date=exit_d, cumulative_pnl=round(cumulative, 2)))
        if cumulative > peak:
            peak = cumulative
        dd = peak - cumulative
        if dd > max_dd:
            max_dd = dd

    return EquityCurve(
        points=points,
        max_drawdown=round(max_dd, 2),
        peak_pnl=round(peak, 2),
        final_pnl=round(cumulative, 2),
    )


def compose(trades: Iterable[Trade]) -> JournalAnalytics:
    trades = list(trades)
    return JournalAnalytics(
        kpis=compute_kpis(trades),
        by_strategy=compute_by_strategy(trades),
        by_dte=compute_by_dte(trades),
        by_mistake=compute_by_mistake(trades),
        equity=compute_equity_curve(trades),
    )


__all__ = [
    "DTE_BUCKET_ORDER",
    "DteBucket",
    "EquityCurve",
    "EquityPoint",
    "JournalAnalytics",
    "KpiBlock",
    "MistakeBucket",
    "StrategyBucket",
    "compose",
    "compute_by_dte",
    "compute_by_mistake",
    "compute_by_strategy",
    "compute_equity_curve",
    "compute_kpis",
]
