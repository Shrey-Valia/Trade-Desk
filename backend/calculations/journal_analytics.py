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
from datetime import date, datetime, time, timezone
from typing import Iterable
from zoneinfo import ZoneInfo

from models.trade import Trade

# Trading-day clock is Eastern — time-of-day and day-of-week buckets are
# computed in ET so they line up with the session a 0DTE trader runs.
_ET = ZoneInfo("America/New_York")

# Intraday session windows (minutes-of-day, ET). Open through 10:30,
# midday through 13:00, power hour after. Mirrors the design kit.
_OPEN_END_MIN = 10 * 60 + 30        # 10:30
_MIDDAY_END_MIN = 13 * 60           # 13:00
TIME_OF_DAY_ORDER = ("Open", "Midday", "Power hour")
DAY_OF_WEEK_ORDER = ("Mon", "Tue", "Wed", "Thu", "Fri")
_WEEKDAY_LABELS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


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
    avg_hold_min: float | None          # mean hold in minutes (timed trades)


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
class SymbolBucket:
    symbol: str
    trades: int
    closed: int
    win_rate: float | None
    net_pnl: float
    avg_pnl: float | None


@dataclass
class TimeBucket:
    """One window of the trading day or one weekday. Used for both the
    time-of-day and day-of-week breakdowns (same shape)."""

    label: str
    trades: int
    win_rate: float | None
    avg_pnl: float | None
    net_pnl: float


@dataclass
class StreakStats:
    best_win: int               # longest run of consecutive winners (≥0)
    worst_loss: int             # longest run of consecutive losers (≤0)
    current: int                # signed run at the tail (+win / −loss)
    avg_hold_win_min: float | None
    avg_hold_loss_min: float | None


@dataclass
class RiskBlock:
    """Discipline numbers measured against the combine's MLL trail.

    Trade-derived numbers (worst day, largest loss) are always present;
    the trail-relative count (`days_near_mll`) is only computed when the
    caller passes the active tier's trailing distance — the frontend
    sources it from /api/account/state."""

    largest_loss: float | None          # most negative single trade
    worst_day_pnl: float                # most negative realized day
    worst_day_date: str | None
    avg_loss: float | None              # |average loser| (positive)
    max_drawdown: float                 # mirrors equity.max_drawdown
    trail: float | None                 # echo of the tier trail used
    days_near_mll: int | None           # days whose loss > 50% of trail


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
    # Endpoints of the largest peak-to-trough window, for the shaded band.
    drawdown_peak_date: str | None = None
    drawdown_trough_date: str | None = None


@dataclass
class JournalAnalytics:
    kpis: KpiBlock
    by_strategy: list[StrategyBucket]
    by_symbol: list[SymbolBucket]
    by_dte: list[DteBucket]
    by_time_of_day: list[TimeBucket]
    by_day_of_week: list[TimeBucket]
    by_mistake: list[MistakeBucket]
    streaks: StreakStats
    equity: EquityCurve
    risk: RiskBlock


# ---------------------------------------------------------------------------
# Helpers — kept private. Tested via the public compose function above.
# ---------------------------------------------------------------------------


def _is_closed(t: Trade) -> bool:
    return t.status == "closed" and t.realized_pnl is not None


def _safe_div(num: float, den: float) -> float | None:
    if den == 0:
        return None
    return num / den


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _as_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _has_intraday_time(dt: datetime | None) -> bool:
    """A date-only entry serializes to 00:00:00 UTC — we treat that as
    "no intraday timestamp" so back-logged trades don't pollute the
    time-of-day / hold-time stats with a fake midnight."""
    u = _as_utc(dt)
    if u is None:
        return False
    u = u.astimezone(timezone.utc)
    return not (u.hour == 0 and u.minute == 0 and u.second == 0)


def _entry_et_minutes(t: Trade) -> int | None:
    """Minutes-of-day (ET) of the entry, or None when no real intraday
    time was recorded."""
    dt = _as_utc(getattr(t, "entry_date", None))
    if dt is None or not _has_intraday_time(dt):
        return None
    et = dt.astimezone(_ET)
    return et.hour * 60 + et.minute


def _entry_weekday_label(t: Trade) -> str | None:
    dt = _as_utc(getattr(t, "entry_date", None))
    if dt is None:
        return None
    et = dt.astimezone(_ET)
    wd = et.weekday()  # Mon=0 .. Sun=6
    return _WEEKDAY_LABELS[wd] if 0 <= wd < len(_WEEKDAY_LABELS) else None


def _hold_minutes(t: Trade) -> int | None:
    """Hold duration in minutes. Requires a real intraday entry time and
    an exit on/after it — otherwise the span is meaningless."""
    entry = _as_utc(getattr(t, "entry_date", None))
    exit_dt = _as_utc(getattr(t, "exit_date", None))
    if entry is None or exit_dt is None or not _has_intraday_time(entry):
        return None
    delta = (exit_dt - entry).total_seconds() / 60.0
    if delta < 0:
        return None
    return int(round(delta))


def _time_of_day_bucket(minutes: int) -> str:
    if minutes < _OPEN_END_MIN:
        return "Open"
    if minutes < _MIDDAY_END_MIN:
        return "Midday"
    return "Power hour"


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

    holds = [h for h in (_hold_minutes(t) for t in closed) if h is not None]
    avg_hold_min = _mean(holds)

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
        avg_hold_min=avg_hold_min,
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
    peak_date: str | None = None
    max_dd = 0.0
    dd_peak_date: str | None = None
    dd_trough_date: str | None = None
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
            peak_date = exit_d
        dd = peak - cumulative
        if dd > max_dd:
            max_dd = dd
            dd_trough_date = exit_d
            dd_peak_date = peak_date  # the peak this trough fell from

    return EquityCurve(
        points=points,
        max_drawdown=round(max_dd, 2),
        peak_pnl=round(peak, 2),
        final_pnl=round(cumulative, 2),
        drawdown_peak_date=dd_peak_date,
        drawdown_trough_date=dd_trough_date,
    )


def compute_by_symbol(trades: Iterable[Trade]) -> list[SymbolBucket]:
    """One row per traded symbol. Like compute_by_strategy — open trades
    count toward `trades` but only closed trades drive the P&L."""
    by_sym: dict[str, list[Trade]] = defaultdict(list)
    for t in trades:
        by_sym[t.symbol].append(t)

    out: list[SymbolBucket] = []
    for sym, ts in by_sym.items():
        closed = [t for t in ts if _is_closed(t)]
        wins = [t for t in closed if (t.realized_pnl or 0) > 0]
        net = sum((t.realized_pnl or 0) for t in closed)
        out.append(SymbolBucket(
            symbol=sym,
            trades=len(ts),
            closed=len(closed),
            win_rate=_safe_div(len(wins), len(closed)),
            net_pnl=net,
            avg_pnl=_safe_div(net, len(closed)),
        ))
    out.sort(key=lambda b: b.net_pnl, reverse=True)
    return out


def _time_buckets(
    trades: Iterable[Trade],
    key_fn,
    order: tuple[str, ...],
) -> list[TimeBucket]:
    """Shared builder for time-of-day / day-of-week breakdowns. `key_fn`
    maps a closed trade to a bucket label (or None to skip it). Emits one
    row per label in `order`, including empty buckets so the chart keeps
    a stable axis."""
    by_label: dict[str, list[Trade]] = defaultdict(list)
    for t in trades:
        if not _is_closed(t):
            continue
        label = key_fn(t)
        if label is None:
            continue
        by_label[label].append(t)

    rows: list[TimeBucket] = []
    for label in order:
        ts = by_label.get(label, [])
        if not ts:
            rows.append(TimeBucket(label=label, trades=0, win_rate=None, avg_pnl=None, net_pnl=0.0))
            continue
        wins = [t for t in ts if (t.realized_pnl or 0) > 0]
        net = sum((t.realized_pnl or 0) for t in ts)
        rows.append(TimeBucket(
            label=label,
            trades=len(ts),
            win_rate=_safe_div(len(wins), len(ts)),
            avg_pnl=_safe_div(net, len(ts)),
            net_pnl=net,
        ))
    return rows


def compute_by_time_of_day(trades: Iterable[Trade]) -> list[TimeBucket]:
    """Bucket closed trades into Open / Midday / Power hour by ET entry
    time. Trades without a real intraday timestamp are excluded (their
    entry minute is unknown — see _has_intraday_time)."""
    def key(t: Trade) -> str | None:
        mins = _entry_et_minutes(t)
        return _time_of_day_bucket(mins) if mins is not None else None
    return _time_buckets(trades, key, TIME_OF_DAY_ORDER)


def compute_by_day_of_week(trades: Iterable[Trade]) -> list[TimeBucket]:
    """Bucket closed trades by ET entry weekday (Mon–Fri)."""
    return _time_buckets(trades, _entry_weekday_label, DAY_OF_WEEK_ORDER)


def compute_streaks(trades: Iterable[Trade]) -> StreakStats:
    """Win/loss streaks over closed trades in exit-date order, plus the
    average hold (minutes) split by winners and losers.

    A breakeven trade (realized_pnl == 0) counts as a win, matching the
    rest of the journal's win convention."""
    closed = [t for t in trades if _is_closed(t) and t.exit_date is not None]
    closed.sort(key=lambda t: (t.exit_date, getattr(t, "id", 0)))

    best = worst = run = 0
    for t in closed:
        win = (t.realized_pnl or 0) >= 0
        run = (run + 1) if (win and run > 0) else (run - 1) if (not win and run < 0) else (1 if win else -1)
        best = max(best, run)
        worst = min(worst, run)

    current = 0
    for t in reversed(closed):
        win = (t.realized_pnl or 0) >= 0
        if current == 0:
            current = 1 if win else -1
        elif win and current > 0:
            current += 1
        elif not win and current < 0:
            current -= 1
        else:
            break

    win_holds: list[float] = []
    loss_holds: list[float] = []
    for t in closed:
        h = _hold_minutes(t)
        if h is None:
            continue
        (win_holds if (t.realized_pnl or 0) >= 0 else loss_holds).append(h)

    return StreakStats(
        best_win=best,
        worst_loss=worst,
        current=current,
        avg_hold_win_min=_mean(win_holds),
        avg_hold_loss_min=_mean(loss_holds),
    )


def compute_risk(trades: Iterable[Trade], trail: float | None = None) -> RiskBlock:
    """Discipline numbers vs the combine MLL trail.

    `trail` is the active tier's trailing distance (e.g. 2000 for the 50K
    combine). When provided, `days_near_mll` counts realized trading days
    whose loss exceeded 50% of the trail. Without it that field is None
    and the frontend simply omits the count."""
    closed = [t for t in trades if _is_closed(t)]
    losers = [t for t in closed if (t.realized_pnl or 0) < 0]
    largest_loss = min((t.realized_pnl or 0) for t in losers) if losers else None
    sum_losses_abs = abs(sum((t.realized_pnl or 0) for t in losers))
    avg_loss = -(_safe_div(sum_losses_abs, len(losers)) or 0.0) if losers else None

    # Per-day realized net, bucketed by exit day.
    by_day: dict[str, float] = defaultdict(float)
    for t in closed:
        if t.exit_date is None:
            continue
        exit_d = (
            t.exit_date.date().isoformat()
            if isinstance(t.exit_date, datetime)
            else str(t.exit_date)
        )
        by_day[exit_d] += float(t.realized_pnl or 0)

    worst_day_date: str | None = None
    worst_day_pnl = 0.0
    for d, pnl in by_day.items():
        if pnl < worst_day_pnl or worst_day_date is None:
            worst_day_pnl = pnl
            worst_day_date = d

    days_near_mll: int | None = None
    if trail is not None and trail > 0:
        days_near_mll = sum(1 for pnl in by_day.values() if -pnl > 0.5 * trail)

    eq = compute_equity_curve(trades)

    return RiskBlock(
        largest_loss=largest_loss,
        worst_day_pnl=round(worst_day_pnl, 2),
        worst_day_date=worst_day_date,
        avg_loss=avg_loss,
        max_drawdown=eq.max_drawdown,
        trail=trail,
        days_near_mll=days_near_mll,
    )


def compose(trades: Iterable[Trade], trail: float | None = None) -> JournalAnalytics:
    trades = list(trades)
    return JournalAnalytics(
        kpis=compute_kpis(trades),
        by_strategy=compute_by_strategy(trades),
        by_symbol=compute_by_symbol(trades),
        by_dte=compute_by_dte(trades),
        by_time_of_day=compute_by_time_of_day(trades),
        by_day_of_week=compute_by_day_of_week(trades),
        by_mistake=compute_by_mistake(trades),
        streaks=compute_streaks(trades),
        equity=compute_equity_curve(trades),
        risk=compute_risk(trades, trail),
    )


__all__ = [
    "DAY_OF_WEEK_ORDER",
    "DTE_BUCKET_ORDER",
    "TIME_OF_DAY_ORDER",
    "DteBucket",
    "EquityCurve",
    "EquityPoint",
    "JournalAnalytics",
    "KpiBlock",
    "MistakeBucket",
    "RiskBlock",
    "StrategyBucket",
    "StreakStats",
    "SymbolBucket",
    "TimeBucket",
    "compose",
    "compute_by_day_of_week",
    "compute_by_dte",
    "compute_by_mistake",
    "compute_by_strategy",
    "compute_by_symbol",
    "compute_by_time_of_day",
    "compute_equity_curve",
    "compute_kpis",
    "compute_risk",
    "compute_streaks",
]
