from typing import Literal

from pydantic import BaseModel


class BsLegIn(BaseModel):
    strike: float
    type: Literal["call", "put"]
    side: Literal["long", "short"]
    quantity: int = 1
    expiry: str  # ISO date


class BsRequest(BaseModel):
    symbol: str
    legs: list[BsLegIn]
    iv_override: float | None = None
    rate: float | None = None  # if None, server fetches DGS3MO


class BsPoint(BaseModel):
    price: float
    pnl: float


class BsGreeks(BaseModel):
    delta: float
    gamma: float
    theta: float
    vega: float


class BsResponse(BaseModel):
    payoff_at_expiry: list[BsPoint]
    current_value: list[BsPoint]
    cost_debit_credit: float                # negative = credit
    max_gain: float | None                  # None when unlimited_gain
    max_loss: float | None                  # None when unlimited_loss
    unlimited_gain: bool
    unlimited_loss: bool
    edge_pnl_low: float                     # PnL at the leftmost displayed price
    edge_pnl_high: float                    # PnL at the rightmost displayed price
    breakevens: list[float]
    greeks: BsGreeks
    prob_profit: float | None               # P(payoff_at_expiry > 0) from MC
