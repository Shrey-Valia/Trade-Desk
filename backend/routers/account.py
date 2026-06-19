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

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from database import get_session
from models.combine import Combine
from models.user import User
from services.account_tiers import ALL_TIERS, TIERS
from services.auth import get_current_user
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
        high_water_mark=snap.hwm,
        settled_hwm=snap.settled_hwm,
        mll=snap.mll,
        status=snap.outcome,  # type: ignore[arg-type]
        day_locked=snap.day_locked,
        dll_used=snap.dll_used,
        dll_budget=snap.dll_budget,
        dll_breached=snap.dll_breached,
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
