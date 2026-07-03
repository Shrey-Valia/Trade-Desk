"""Per-combine account math — the multi-user successor to the
single-AccountState read path, now with the settlement engine AND the
funded-account lifecycle folded in.

Same computation pattern as before, keyed by combine_id: realized P&L
from closed trades, balance via the frozen compute_balance, a RUNNING
HWM advanced monotonically intraday, and DLL from realized losses. On
top of that this module drives the combine engine
(services/combine_settlement): a lazy 5pm-PT settlement re-baselines the
SETTLED HWM up, the MLL floor is computed from that settled HWM (so it
is fixed intraday), the DLL window is the current 5pm-PT trading day,
and the realized-based PASS/FAIL outcome is persisted on the combine.

Lifecycle: passing the eval AUTO-FUNDS the account (funded_at stamped).
ACTIVATION (routers/combines.py) stamps the funded-stage accounting epoch
(`funded_epoch_at`) and re-seeds the HWM basis to the tier start: from
that instant only trades opened at/after the epoch count, booked payouts
DEBIT the balance every consumer sees, and payout eligibility accrues
from funded-stage profit only — the profit used to PASS stays with the
firm. A funded account keeps trading against the trailing MLL, so
passed → failed is a legal terminal transition. A reset (after a fail)
stamps `eval_reset_at` and the eval math here only counts trades opened
at/after that point — the trade history is kept. Each meaningful
transition (funded / failed / settled) is written to the combine_events
ledger so the dashboard live-feed can show it.

Used by both routers/account.py (active-combine snapshot) and
routers/combines.py (per-card snapshots) so the numbers can't drift.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from models.combine import Combine
from models.combine_event import CombineEvent
from models.trade import Trade
from models.user import User
from services.account_tiers import (
    TIERS,
    compute_balance,
    compute_mll,
    resolve_dll_budget,
    update_hwm,
)
from services.combine_objectives import (
    objective_progress,
    payout_eligible,
    profit_target,
)
from services.pricing import activation_fee as activation_fee_for
from services.scaling_plan import max_contracts as scaling_max_contracts
from services.combine_settlement import (
    MIN_TRADING_DAYS,
    consistency_ok,
    needs_settlement,
    settle_hwm,
    trading_day_start,
)


@dataclass(frozen=True)
class CombineSnapshot:
    combine: Combine
    starting_balance: float
    realized_pnl: float
    balance: float
    # Realized P&L within the current 5pm-PT trading day (signed) — the
    # daily RPL the header shows. eod_balance is the balance carried into
    # today (starting + realized BEFORE today's window), so the header can
    # render BAL = eod_balance + RPL(today) + URPL and have it reconcile.
    today_realized: float
    eod_balance: float
    hwm: float
    settled_hwm: float
    mll: float
    dll_used: float
    dll_budget: float
    dll_breached: bool
    day_locked: bool
    # DLL-off toggle: True when the owner has switched the Daily Loss Limit OFF
    # for this tier. The dll_budget is then +inf (no day-lock / breach); the
    # API serializes it specially since inf is JSON-unsafe.
    dll_disabled: bool
    profit_target: float
    objective_progress: float
    # --- scaling plan: max position size (contracts) by built equity ---
    max_contracts: int
    # --- settlement engine: PASS / FAIL ---
    outcome: str  # "active" | "passed" | "failed"
    days_traded: int
    min_trading_days: int
    largest_day_profit: float
    consistency_ok: bool
    # --- funded-account lifecycle ---
    funded: bool
    funded_at: datetime | None
    payout_eligible: float
    # --- pricing + activation ---
    pricing_path: str
    profit_split: float
    # True once the funded account is activated (no_activation: at funding;
    # activation: when the $149 fee is paid). Payouts are gated on this.
    funded_activated: bool
    # Activation fee still owed to unlock payouts ($149 if required, else 0).
    activation_required: bool
    activation_fee: float


def realized_sum_for_combine(
    session: Session, combine_id: int, since: datetime | None = None
) -> float:
    stmt = (
        select(Trade.realized_pnl)
        .where(Trade.combine_id == combine_id)
        .where(Trade.status == "closed")
    )
    if since is not None:
        stmt = stmt.where(Trade.entry_date >= since)
    rows = session.execute(stmt).all()
    return float(sum((r[0] or 0.0) for r in rows))


def _closed_exits(
    session: Session, combine_id: int, since: datetime | None = None
) -> list[tuple[datetime, float]]:
    """(exit_date, realized_pnl) for this combine's closed trades, exit
    coerced to UTC-aware. `since` (the combine's eval_reset_at) excludes
    trades opened before an eval restart. Shared by the DLL window and the
    per-day buckets so both read the same source."""
    stmt = (
        select(Trade.exit_date, Trade.realized_pnl)
        .where(Trade.combine_id == combine_id)
        .where(Trade.status == "closed")
        .where(Trade.exit_date.is_not(None))
    )
    if since is not None:
        stmt = stmt.where(Trade.entry_date >= since)
    rows = session.execute(stmt).all()
    out: list[tuple[datetime, float]] = []
    for exit_dt, pnl in rows:
        if exit_dt is None:
            continue
        if exit_dt.tzinfo is None:
            exit_dt = exit_dt.replace(tzinfo=timezone.utc)
        out.append((exit_dt, float(pnl or 0.0)))
    return out


def dll_used_today_for_combine(
    session: Session, combine_id: int, now: datetime, since: datetime | None = None
) -> float:
    """Today's realized loss on this combine within the current 5pm-PT
    trading-day window [trading_day_start, now], clamped to ≥0. Frontend
    folds open-position URPL in at display time for the live DLL test."""
    day_start = trading_day_start(now)
    today_realized = 0.0
    for exit_dt, pnl in _closed_exits(session, combine_id, since):
        if exit_dt >= day_start:
            today_realized += pnl
    return max(0.0, -today_realized)


def realized_today_for_combine(
    session: Session, combine_id: int, now: datetime, since: datetime | None = None
) -> float:
    """Signed realized P&L within the current 5pm-PT trading-day window
    [trading_day_start, now] — the daily RPL shown in the header.
    (dll_used_today_for_combine is the clamped loss-only view of the same
    window; this is the signed value for display + the EOD decomposition.)"""
    day_start = trading_day_start(now)
    total = 0.0
    for exit_dt, pnl in _closed_exits(session, combine_id, since):
        if exit_dt >= day_start:
            total += pnl
    return total


def realized_by_trading_day(
    session: Session, combine_id: int, since: datetime | None = None
) -> dict[datetime, float]:
    """Realized P&L on this combine bucketed by 5pm-PT trading day (keyed
    by the day's start instant). Drives the min-trading-days count and the
    consistency rule — both realized-based, like fail/settlement."""
    by_day: dict[datetime, float] = {}
    for exit_dt, pnl in _closed_exits(session, combine_id, since):
        day = trading_day_start(exit_dt)
        by_day[day] = by_day.get(day, 0.0) + pnl
    return by_day


def payouts_booked(session: Session, combine_id: int) -> float:
    """Sum of payout amounts already booked on this combine. A booked
    payout DEBITS the funded-stage balance (and with it the HWM basis and
    the MLL fail test) — withdrawn money stops counting as equity."""
    rows = session.execute(
        select(CombineEvent.amount).where(
            CombineEvent.combine_id == combine_id, CombineEvent.type == "payout"
        )
    ).all()
    return float(sum((r[0] or 0.0) for r in rows))


def has_open_book(session: Session, combine_id: int) -> bool:
    """True when the combine has any OPEN position or WORKING order."""
    return (
        session.execute(
            select(Trade.id)
            .where(
                Trade.combine_id == combine_id,
                Trade.status.in_(("open", "working")),
            )
            .limit(1)
        ).scalar_one_or_none()
        is not None
    )


def record_event(
    session: Session,
    combine: Combine,
    type_: str,
    message: str,
    amount: float | None = None,
) -> None:
    """Append a row to the combine_events ledger. Caller owns the commit."""
    session.add(
        CombineEvent(
            user_id=combine.user_id,
            combine_id=combine.id,
            type=type_,
            message=message,
            amount=amount,
        )
    )


def combine_snapshot(session: Session, combine: Combine) -> CombineSnapshot:
    """Full computed state for one combine. Advances the persisted RUNNING
    HWM monotonically (realized-only), runs the lazy 5pm-PT settlement,
    computes the fixed-intraday MLL floor, persists a realized-based
    PASS/FAIL outcome, AUTO-FUNDS on a pass, and logs each transition. All
    persisted decisions are realized-based; the frontend folds live URPL in
    for display only."""
    tier = TIERS[combine.tier]
    now = datetime.now(timezone.utc)
    # Funded-stage epoch: once activated, accounting restarts — only trades
    # opened at/after the epoch count, and booked payouts debit the balance.
    # Pre-activation (eval, or funded-but-unactivated) the eval basis applies.
    epoch = combine.funded_epoch_at
    funded_stage = epoch is not None
    since = epoch if funded_stage else combine.eval_reset_at

    realized = realized_sum_for_combine(session, combine.id, since)
    payouts = payouts_booked(session, combine.id) if funded_stage else 0.0
    balance = compute_balance(tier.starting_balance, realized, 0.0) - payouts
    dirty = False

    # RUNNING HWM — monotonic, updated intraday from realized balance.
    new_hwm = update_hwm(combine.hwm, balance)
    if new_hwm != combine.hwm:
        combine.hwm = new_hwm
        dirty = True

    # Lazy 5pm-PT settlement: once a boundary has passed, the settled HWM
    # re-baselines UP to the running HWM (never down) and we stamp the time
    # so we settle once per trading day. The DLL day resets implicitly —
    # it derives from the 5pm-PT window below, not a persisted flag.
    # Archived combines are frozen: no settlement (or events) on read.
    if combine.status != "archived" and needs_settlement(combine.last_settled_at, now):
        combine.settled_hwm = settle_hwm(combine.settled_hwm, new_hwm)
        combine.last_settled_at = now
        record_event(session, combine, "settled", "Daily settlement — MLL re-baselined.")
        dirty = True

    # MLL floor — FIXED intraday, from the SETTLED HWM. Only settlement
    # moves it (always up).
    mll = compute_mll(combine.tier, combine.settled_hwm)  # type: ignore[arg-type]

    # Scaling plan — max contracts by built equity (settled profit above
    # start). Fixed intraday like the MLL; only settlement re-evaluates it.
    settled_profit = max(0.0, combine.settled_hwm - tier.starting_balance)
    max_contracts = scaling_max_contracts(combine.tier, settled_profit)

    # DLL — today's realized loss within the current 5pm-PT trading day,
    # tested against the user's per-tier override (clamped) or the tier default.
    dll_used = dll_used_today_for_combine(session, combine.id, now, since)
    # Daily RPL (signed) + the balance carried into today, so the header can
    # show BAL = eod_balance + RPL(today) + URPL transparently. Both sides
    # net the funded-stage payout debit, so the decomposition still holds.
    today_realized = realized_today_for_combine(session, combine.id, now, since)
    eod_balance = (
        compute_balance(tier.starting_balance, realized - today_realized, 0.0) - payouts
    )
    owner = session.get(User, combine.user_id)
    dll_override = owner.dll_overrides.get(combine.tier) if owner else None
    # DLL-off toggle: when the owner has disabled the DLL for this tier the
    # budget stays numeric (tier default, for display) but the day-lock /
    # breach tests are suppressed — the DLL no longer binds, only the MLL.
    dll_disabled = bool(owner and not owner.dll_enabled_for(combine.tier))
    dll_budget = resolve_dll_budget(
        combine.tier, dll_override, disabled=dll_disabled
    )  # type: ignore[arg-type]
    day_locked = (not dll_disabled) and dll_used >= dll_budget

    # PASS progress (realized-based), bucketed per 5pm-PT trading day.
    by_day = realized_by_trading_day(session, combine.id, since)
    days_traded = len(by_day)
    total_realized = sum(by_day.values()) if by_day else 0.0
    largest_day_profit = max(by_day.values()) if by_day else 0.0
    consistency = consistency_ok(largest_day_profit, total_realized)
    target = profit_target(combine.tier)
    target_met = target > 0 and realized >= target
    min_days_met = days_traded >= MIN_TRADING_DAYS

    # Outcome precedence: FAILED is terminal (MLL breach) and wins; PASSED
    # auto-funds but is NOT safe — a funded account keeps trading against the
    # trailing MLL, so passed → failed is a legal terminal transition. An
    # archived combine keeps its recorded outcome. The lazy fail here tests a
    # REALIZED-only balance, so it stamps only on a FLAT book: with open or
    # working trades it understates live equity — the auto-liquidation
    # monitor (order_monitor) owns the live-equity fail in that case.
    outcome = combine.outcome
    if outcome == "active" and combine.status != "archived":
        if balance <= mll and not has_open_book(session, combine.id):
            outcome = "failed"
            combine.outcome = outcome
            record_event(
                session, combine, "failed", "Evaluation failed — MLL floor breached."
            )
            dirty = True
        elif target_met and min_days_met and consistency:
            outcome = "passed"
            combine.outcome = outcome
            combine.funded_at = now  # auto-fund on pass
            # Activation is ALWAYS an explicit step (one unified flow): the
            # account stays un-activated until the trader clicks Activate via
            # /activate-account — which charges $149 on the activation path and
            # $0 on the no-activation path.
            record_event(
                session,
                combine,
                "funded",
                "Evaluation passed — account funded.",
            )
            dirty = True
    elif outcome == "passed" and combine.status != "archived":
        if balance <= mll and not has_open_book(session, combine.id):
            outcome = "failed"
            combine.outcome = outcome
            record_event(
                session,
                combine,
                "failed",
                "Funded account closed — trailing max loss breached.",
            )
            dirty = True

    funded = combine.funded_at is not None
    funded_activated = combine.funded_activated_at is not None
    # Payouts unlock only once the funded account is activated. In the funded
    # stage `realized` is the SINCE-EPOCH sum, so eligibility starts at 0 on
    # activation — the eval profit is not withdrawable. Gross of prior
    # requests; the payout endpoint nets those before booking.
    eligible = payout_eligible(realized, funded and funded_activated, combine.profit_split)
    activation_required = funded and not funded_activated
    # Fee owed to activate ($149 on the activation path, $0 on no-activation).
    activation_fee = activation_fee_for(combine.pricing_path) if activation_required else 0.0

    if dirty:
        session.add(combine)
        session.commit()

    return CombineSnapshot(
        combine=combine,
        starting_balance=tier.starting_balance,
        realized_pnl=realized,
        balance=balance,
        today_realized=today_realized,
        eod_balance=eod_balance,
        hwm=new_hwm,
        settled_hwm=combine.settled_hwm,
        mll=mll,
        dll_used=dll_used,
        dll_budget=dll_budget,
        dll_breached=(not dll_disabled) and dll_used > dll_budget,
        day_locked=day_locked,
        dll_disabled=dll_disabled,
        profit_target=target,
        objective_progress=objective_progress(combine.tier, realized),
        max_contracts=max_contracts,
        outcome=outcome,
        days_traded=days_traded,
        min_trading_days=MIN_TRADING_DAYS,
        largest_day_profit=largest_day_profit,
        consistency_ok=consistency,
        funded=funded,
        funded_at=combine.funded_at,
        payout_eligible=eligible,
        pricing_path=combine.pricing_path,
        profit_split=combine.profit_split,
        funded_activated=funded_activated,
        activation_required=activation_required,
        activation_fee=activation_fee,
    )
