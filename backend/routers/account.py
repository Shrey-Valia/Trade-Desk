"""Account state — the active combine's snapshot for the terminal header.

GET  /api/account/state          active combine's computed snapshot

Multi-user world: state is computed per the signed-in user's active
COMBINE (services/combine_state), not a global AccountState row. The
response keeps every pre-multi-user field name so the terminal header
needed no changes, and adds combine identity fields + the user's
combine list for the header switcher.

Zero combines (fresh signup, or everything archived) → 404
"no active combine" — the frontend renders its purchase CTA off that.
Combine switching lives in POST /api/combines/{id}/activate.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from database import get_session
from models.combine import Combine
from models.user import DLL_MODE_STRENGTH, User
from services.account_tiers import ALL_TIERS, TIERS, resolve_dll_budget
from services.auth import get_current_user
from services.combine_settlement import trading_day_start
from services.combine_state import combine_snapshot

router = APIRouter(prefix="/api/account", tags=["account"])


class TierSpec(BaseModel):
    key: str
    label: str
    starting_balance: float
    trailing_distance: float
    initial_mll: float
    dll_amount: float


class CombineSummary(BaseModel):
    id: int
    name: str
    tier: str
    account_code: str
    status: str


class AccountStateOut(BaseModel):
    # -- pre-multi-user fields (names unchanged; terminal header reads these) --
    active_tier: str
    starting_balance: float
    realized_pnl: float = Field(..., description="Sum of closed-trade realized P&L on the active combine.")
    balance: float = Field(..., description="starting_balance + realized_pnl. Unrealized is added client-side.")
    today_realized: float = Field(
        ...,
        description=(
            "Signed realized P&L within the current 5pm-PT trading day — the daily"
            " RPL. The header shows BAL = eod_balance + today_realized + URPL."
        ),
    )
    eod_balance: float = Field(
        ...,
        description=(
            "Balance carried into today (starting + realized BEFORE today's 5pm-PT"
            " window). The EOD baseline for the daily P&L decomposition."
        ),
    )
    high_water_mark: float = Field(..., description="Running (monotonic) HWM.")
    settled_hwm: float = Field(
        ..., description="Settled HWM — basis of the fixed-intraday MLL floor."
    )
    mll: float = Field(
        ...,
        description=(
            "MLL floor — FIXED intraday (from the settled HWM); re-baselines UP"
            " only at the 5pm-PT settlement. The combine FAILS if balance (incl."
            " live URPL, folded client-side) ≤ this."
        ),
    )
    status: Literal["active", "passed", "failed"] = Field(
        ..., description="Settlement outcome. FAILED (MLL breach) is permanent."
    )
    day_locked: bool = Field(
        ...,
        description=(
            "True when today's realized loss has hit the DLL — no further trading"
            " today (the combine survives); lifts at the 5pm-PT settlement."
        ),
    )
    dll_used: float = Field(
        ...,
        description=(
            "Today's realized loss on the active combine (5pm-PT trading day),"
            " clamped to ≥0. Frontend folds in any active-position UPL at"
            " display time, mirroring the BAL pattern."
        ),
    )
    dll_budget: float
    dll_breached: bool
    dll_disabled: bool = Field(
        default=False,
        description=(
            "True when the owner has switched the Daily Loss Limit OFF for the"
            " active tier (Topstep dropped the DLL in 2024). No day-lock / DLL"
            " breach applies; dll_budget then carries the tier DEFAULT amount as"
            " a display reference, not an enforced limit."
        ),
    )
    # -- PASS / profit-target progress (realized-based) ------------------------
    days_traded: int = Field(
        ..., description="Distinct 5pm-PT trading days with ≥1 closed trade."
    )
    min_trading_days: int = Field(..., description="Min distinct trading days to pass.")
    largest_day_profit: float = Field(
        ..., description="Biggest single trading day's realized P&L (consistency basis)."
    )
    consistency_ok: bool = Field(
        ...,
        description=(
            "True when no single day's realized profit exceeds 50% of total"
            " realized profit (or there is no realized profit yet)."
        ),
    )
    tiers: list[TierSpec]
    # -- combine identity (multi-user shell) ----------------------------------
    combine_id: int
    combine_name: str
    account_code: str
    combine_status: str = Field(..., description="Lifecycle: active | archived.")
    profit_target: float = Field(..., description="Realized profit needed to PASS (6%).")
    objective_progress: float = Field(..., description="realized/target clamped to [0,1].")
    max_contracts: int = Field(
        ...,
        description=(
            "Scaling-plan cap: max contracts per position at the current built"
            " equity. Fixed intraday; re-evaluates at the 5pm-PT settlement."
        ),
    )
    # -- funded-account lifecycle ---------------------------------------------
    funded: bool = Field(..., description="True once the eval passed (auto-funded).")
    payout_eligible: float = Field(
        ..., description="Trader's split of realized profit (gross; Payouts page nets prior requests)."
    )
    # -- pricing + activation -------------------------------------------------
    profit_split: float = Field(..., description="Trader's profit share (0.80 or 0.50).")
    pricing_path: str = Field(..., description="activation | no_activation.")
    activation_required: bool = Field(
        ..., description="Funded but not yet activated — payouts locked until the fee is paid."
    )
    activation_fee: float = Field(..., description="Activation fee owed to unlock payouts.")
    funded_activated: bool = Field(..., description="True once the funded account is activated.")
    combines: list[CombineSummary]


@router.get("/state", response_model=AccountStateOut)
def get_account_state(
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> AccountStateOut:
    combine = _active_combine_or_404(session, user)
    snap = combine_snapshot(session, combine)
    all_combines = session.execute(
        select(Combine)
        .where(Combine.user_id == user.id)
        .order_by(Combine.created_at.desc(), Combine.id.desc())
    ).scalars().all()

    return AccountStateOut(
        active_tier=combine.tier,
        starting_balance=snap.starting_balance,
        realized_pnl=snap.realized_pnl,
        balance=snap.balance,
        today_realized=snap.today_realized,
        eod_balance=snap.eod_balance,
        high_water_mark=snap.hwm,
        settled_hwm=snap.settled_hwm,
        mll=snap.mll,
        status=snap.outcome,  # type: ignore[arg-type]
        day_locked=snap.day_locked,
        dll_used=snap.dll_used,
        dll_budget=snap.dll_budget,
        dll_breached=snap.dll_breached,
        dll_disabled=snap.dll_disabled,
        days_traded=snap.days_traded,
        min_trading_days=snap.min_trading_days,
        largest_day_profit=snap.largest_day_profit,
        consistency_ok=snap.consistency_ok,
        tiers=_tier_specs(),
        combine_id=combine.id,
        combine_name=combine.name,
        account_code=combine.account_code,
        combine_status=combine.status,
        profit_target=snap.profit_target,
        objective_progress=snap.objective_progress,
        max_contracts=snap.max_contracts,
        funded=snap.funded,
        payout_eligible=snap.payout_eligible,
        profit_split=snap.profit_split,
        pricing_path=snap.pricing_path,
        activation_required=snap.activation_required,
        activation_fee=snap.activation_fee,
        funded_activated=snap.funded_activated,
        combines=[
            CombineSummary(
                id=c.id,
                name=c.name,
                tier=c.tier,
                account_code=c.account_code,
                status=c.status,
            )
            for c in all_combines
        ],
    )


class DllOverrideEntryIn(BaseModel):
    """One structured personal DLL override: dollar amount + enforcement mode.
    Modes (TopstepX signature): "alert" = event only; "liquidate" = flatten
    the open book but keep trading allowed; "liquidate_block" = flatten +
    day-lock until the 5pm-PT reset (the historical behavior)."""

    amount: float = Field(gt=0)
    mode: Literal["alert", "liquidate", "liquidate_block"] = "liquidate_block"


class DllOverrideEntryOut(BaseModel):
    amount: float
    mode: Literal["alert", "liquidate", "liquidate_block"]
    # When this override was last set/changed (ISO-8601 UTC). None for legacy
    # rows written before modes existed. Drives the same-day tighten-only
    # lock-in on liquidate_block overrides.
    set_at: str | None = None


class ProfitTargetSpec(BaseModel):
    """Personal daily profit target ('protect the green day'). At +amount of
    day P&L (realized + open URPL — same basis as the DLL check), lock=true
    flattens the book and day-locks until the 5pm-PT reset; lock=false only
    records a once-per-day combine event."""

    amount: float = Field(gt=0)
    lock: bool = False


class DllOverridesOut(BaseModel):
    overrides: dict[str, DllOverrideEntryOut] = Field(
        default_factory=dict,
        description=(
            "User's per-tier personal DLL overrides: {amount (dollars), mode,"
            " set_at}. Legacy bare-float rows read back as mode"
            " 'liquidate_block'."
        ),
    )
    disabled: list[str] = Field(
        default_factory=list,
        description=(
            "Tier keys with the Daily Loss Limit switched OFF (the DLL-off"
            " toggle). The MLL floor still binds for these tiers."
        ),
    )
    profit_target: ProfitTargetSpec | None = Field(
        default=None,
        description="Personal daily profit target (per-user). null when unset.",
    )


class DllOverridesIn(BaseModel):
    # Values may be a bare number (legacy compat → mode "liquidate_block") or
    # a structured {amount, mode} entry.
    overrides: dict[str, float | DllOverrideEntryIn]
    # Tier keys to switch the DLL OFF for. Omitted (None) leaves the existing
    # disabled set untouched, so a pure amount-edit doesn't clear it.
    disabled: list[str] | None = None
    # Personal daily profit target. OMITTED → left untouched; explicit null →
    # cleared; {amount, lock} → set. (Distinguished via model_fields_set.)
    profit_target: ProfitTargetSpec | None = None


def _overrides_out(user: User) -> DllOverridesOut:
    pt = user.profit_target
    return DllOverridesOut(
        overrides={
            k: DllOverrideEntryOut(amount=v["amount"], mode=v["mode"], set_at=v.get("set_at"))
            for k, v in user.dll_override_entries.items()
        },
        disabled=user.dll_disabled,
        profit_target=ProfitTargetSpec(**pt) if pt else None,
    )


@router.get("/dll-overrides", response_model=DllOverridesOut)
def get_dll_overrides(
    user: User = Depends(get_current_user),
) -> DllOverridesOut:
    """The user's per-tier DLL overrides (+ enforcement modes), disable flags,
    and personal daily profit target (available with zero combines, so the
    Settings editor works before any account is purchased)."""
    return _overrides_out(user)


@router.put("/dll-overrides", response_model=DllOverridesOut)
def set_dll_overrides(
    payload: DllOverridesIn,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> DllOverridesOut:
    """Set per-tier personal DLL overrides (+ enforcement mode), the DLL-off
    disable flags, and the personal daily profit target.

    Override values: a bare number (legacy shape) maps to mode
    "liquidate_block"; structured values carry {amount, mode}. Amounts are
    clamped to the 1-10%-of-starting-balance band; unknown tiers → 422. All
    of it is ENFORCED server-side (combine_state resolves the blocking budget
    mode-aware; order_monitor drives the alert/liquidate triggers and the
    profit-target flatten).

    SAME-DAY TIGHTEN-ONLY LOCK-IN (Topstep rule — the simple, honest
    version): once a "liquidate_block" override exists for a tier (stamped
    with set_at when written), it cannot be RAISED, REMOVED, or WEAKENED
    (mode strength: liquidate_block > liquidate > alert) — nor can that
    tier's DLL be switched OFF — until the next 5pm-PT trading-day boundary.
    Tightening (lowering the amount) is always allowed and re-stamps the
    lock. liquidate_block overrides stamped on a PRIOR trading day (and
    legacy unstamped rows) are freely editable. Violations → 409.

    profit_target: omitted → untouched; explicit null → cleared;
    {amount, lock} → set."""
    now = datetime.now(timezone.utc)
    day_start = trading_day_start(now)
    existing = user.dll_override_entries

    cleaned: dict[str, dict] = {}
    for tier_key, value in payload.overrides.items():
        if tier_key not in TIERS:
            raise HTTPException(422, f"unknown tier {tier_key}")
        if isinstance(value, DllOverrideEntryIn):
            amount, mode = float(value.amount), value.mode
        else:  # bare number — legacy compat, maps to today's behavior
            amount, mode = float(value), "liquidate_block"
        cleaned[tier_key] = {
            "amount": resolve_dll_budget(tier_key, amount),  # type: ignore[arg-type]
            "mode": mode,
        }

    if payload.disabled is not None:
        for tier_key in payload.disabled:
            if tier_key not in TIERS:
                raise HTTPException(422, f"unknown tier {tier_key}")

    # Same-day tighten-only lock-in on existing liquidate_block overrides.
    for tier_key, old in existing.items():
        if old["mode"] != "liquidate_block" or not old.get("set_at"):
            continue
        try:
            stamped = datetime.fromisoformat(old["set_at"])
        except ValueError:
            continue
        if stamped.tzinfo is None:
            stamped = stamped.replace(tzinfo=timezone.utc)
        if stamped < day_start:
            continue  # set on a prior trading day — freely editable
        locked_msg = (
            f"{tier_key} daily loss limit is locked in for today — it can only"
            " be tightened until the next 5pm-PT reset"
        )
        new = cleaned.get(tier_key)
        if new is None:
            raise HTTPException(409, f"{locked_msg} (it cannot be removed).")
        if DLL_MODE_STRENGTH[new["mode"]] < DLL_MODE_STRENGTH["liquidate_block"]:
            raise HTTPException(409, f"{locked_msg} (its mode cannot be weakened).")
        if new["amount"] > old["amount"] + 1e-9:
            raise HTTPException(409, f"{locked_msg} (the amount cannot be raised).")
        disabled_next = payload.disabled if payload.disabled is not None else user.dll_disabled
        if tier_key in disabled_next:
            raise HTTPException(409, f"{locked_msg} (the DLL cannot be switched off).")

    # Stamp set_at: preserved when an entry is unchanged, refreshed otherwise
    # (so a fresh liquidate_block override locks in for the rest of the day).
    for tier_key, new in cleaned.items():
        old = existing.get(tier_key)
        if old is not None and old["amount"] == new["amount"] and old["mode"] == new["mode"]:
            new["set_at"] = old.get("set_at")
        else:
            new["set_at"] = now.isoformat()

    user.dll_override_entries = cleaned
    if payload.disabled is not None:
        user.dll_disabled = list(payload.disabled)
    if "profit_target" in payload.model_fields_set:
        user.profit_target = (
            None
            if payload.profit_target is None
            else {"amount": payload.profit_target.amount, "lock": payload.profit_target.lock}
        )
    session.add(user)
    session.commit()
    return _overrides_out(user)


def _active_combine_or_404(session: Session, user: User) -> Combine:
    if user.active_combine_id is None:
        raise HTTPException(404, "no active combine")
    combine = session.execute(
        select(Combine).where(
            Combine.id == user.active_combine_id,
            Combine.user_id == user.id,
            Combine.status != "archived",
        )
    ).scalar_one_or_none()
    if combine is None:
        raise HTTPException(404, "no active combine")
    return combine


def _tier_specs() -> list[TierSpec]:
    return [
        TierSpec(
            key=k,
            label=TIERS[k].label,
            starting_balance=TIERS[k].starting_balance,
            trailing_distance=TIERS[k].trailing_distance,
            initial_mll=TIERS[k].initial_mll,
            dll_amount=TIERS[k].dll_amount,
        )
        for k in ALL_TIERS
    ]
