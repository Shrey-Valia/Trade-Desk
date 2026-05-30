"""Combine-tier account state endpoints.

GET  /api/account/state               read the current tier's snapshot
POST /api/account/state/switch        switch which tier is active

Read-side computes balance/MLL/HWM live from the trades table + the
persisted high-water mark, so the dashboard always reflects up-to-date
numbers without needing trade-close hooks. The HWM is monotonic per
tier — once a tier hits a new high, that high is sticky.

No trade enforcement here. MLL is reported for display; the trade open
path doesn't gate on it.
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from database import get_session
from models.account_state import AccountState
from models.trade import Trade
from services.account_tiers import (
    ALL_TIERS,
    TIERS,
    TierKey,
    compute_balance,
    compute_mll,
    is_valid_tier,
    update_hwm,
)

router = APIRouter(prefix="/api/account", tags=["account"])


class TierSpec(BaseModel):
    key: str
    label: str
    starting_balance: float
    trailing_distance: float
    initial_mll: float


class AccountStateOut(BaseModel):
    active_tier: str
    starting_balance: float
    realized_pnl: float = Field(..., description="Sum of closed-trade realized P&L on this tier.")
    balance: float = Field(..., description="starting_balance + realized_pnl. Unrealized is added client-side.")
    high_water_mark: float
    mll: float
    tiers: list[TierSpec]


class SwitchTierRequest(BaseModel):
    tier: Literal["50K", "100K", "150K"]


@router.get("/state", response_model=AccountStateOut)
def get_account_state(session: Session = Depends(get_session)) -> AccountStateOut:
    state = _get_or_seed_state(session)
    tier_key = state.active_tier
    tier = TIERS[tier_key]

    realized_sum = _realized_sum_for_tier(session, tier_key)
    balance_excl_upl = compute_balance(tier.starting_balance, realized_sum, 0.0)

    # HWM walks up monotonically. We update from realized P&L only at
    # read time. (Open-position UPL doesn't bump HWM until it's
    # realized — that's the conservative read of Topstep's rule.)
    prior_hwm = state.get_hwm(tier_key)
    new_hwm = update_hwm(prior_hwm, balance_excl_upl)
    if new_hwm != prior_hwm:
        state.set_hwm(tier_key, new_hwm)
        session.add(state)
        session.commit()

    mll = compute_mll(tier_key, new_hwm)

    return AccountStateOut(
        active_tier=tier_key,
        starting_balance=tier.starting_balance,
        realized_pnl=realized_sum,
        balance=balance_excl_upl,
        high_water_mark=new_hwm,
        mll=mll,
        tiers=_tier_specs(),
    )


@router.post("/state/switch", response_model=AccountStateOut)
def switch_tier(
    payload: SwitchTierRequest,
    session: Session = Depends(get_session),
) -> AccountStateOut:
    if not is_valid_tier(payload.tier):
        raise HTTPException(400, f"unknown tier: {payload.tier}")
    state = _get_or_seed_state(session)
    state.active_tier = payload.tier
    session.add(state)
    session.commit()
    return get_account_state(session)


def _get_or_seed_state(session: Session) -> AccountState:
    state = session.get(AccountState, 1)
    if state is None:
        state = AccountState(id=1)
        session.add(state)
        session.commit()
        session.refresh(state)
    return state


def _realized_sum_for_tier(session: Session, tier_key: TierKey) -> float:
    """Sum of realized_pnl across closed trades on this tier."""
    rows = session.execute(
        select(Trade.realized_pnl)
        .where(Trade.tier == tier_key)
        .where(Trade.status == "closed")
    ).all()
    return float(sum((r[0] or 0.0) for r in rows))


def _tier_specs() -> list[TierSpec]:
    return [
        TierSpec(
            key=k,
            label=TIERS[k].label,
            starting_balance=TIERS[k].starting_balance,
            trailing_distance=TIERS[k].trailing_distance,
            initial_mll=TIERS[k].initial_mll,
        )
        for k in ALL_TIERS
    ]
