"""Account state — the active combine's snapshot for the terminal header.

GET  /api/account/state          active combine's computed snapshot
POST /api/account/state/switch   LEGACY tier-switch (see below)

Multi-user world: state is computed per the signed-in user's active
COMBINE (services/combine_state), not a global AccountState row. The
response keeps every pre-multi-user field name so the terminal header
needed no changes, and adds combine identity fields + the user's
combine list for the header switcher.

Zero combines (fresh signup, or everything archived) → 404
"no active combine" — the frontend renders its purchase CTA off that.

POST /state/switch is kept for back-compat with the old TierPill: it
activates the user's newest non-archived combine of the requested tier.
New code should use POST /api/combines/{id}/activate. Deprecated.
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
    high_water_mark: float
    mll: float
    dll_used: float = Field(
        ...,
        description=(
            "Today's realized loss on the active combine (ET trading day),"
            " clamped to ≥0. Frontend folds in any active-position UPL at"
            " display time, mirroring the BAL pattern."
        ),
    )
    dll_budget: float
    dll_breached: bool
    tiers: list[TierSpec]
    # -- combine identity (multi-user shell) ----------------------------------
    combine_id: int
    combine_name: str
    account_code: str
    combine_status: str
    profit_target: float = Field(..., description="Display-only objective — no enforcement.")
    objective_progress: float = Field(..., description="realized/target clamped to [0,1].")
    combines: list[CombineSummary]


class SwitchTierRequest(BaseModel):
    tier: Literal["50K", "100K", "150K"]


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
        mll=snap.mll,
        dll_used=snap.dll_used,
        dll_budget=snap.dll_budget,
        dll_breached=snap.dll_breached,
        tiers=_tier_specs(),
        combine_id=combine.id,
        combine_name=combine.name,
        account_code=combine.account_code,
        combine_status=combine.status,
        profit_target=snap.profit_target,
        objective_progress=snap.objective_progress,
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


@router.post("/state/switch", response_model=AccountStateOut)
def switch_tier(
    payload: SwitchTierRequest,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> AccountStateOut:
    """DEPRECATED back-compat shim for the pre-combine TierPill —
    activates the newest non-archived combine of the requested tier.
    Use POST /api/combines/{id}/activate instead."""
    combine = session.execute(
        select(Combine)
        .where(
            Combine.user_id == user.id,
            Combine.tier == payload.tier,
            Combine.status != "archived",
        )
        .order_by(Combine.created_at.desc(), Combine.id.desc())
        .limit(1)
    ).scalar_one_or_none()
    if combine is None:
        raise HTTPException(404, f"no combine on tier {payload.tier}")
    user.active_combine_id = combine.id
    session.add(user)
    session.commit()
    return get_account_state(user=user, session=session)


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
