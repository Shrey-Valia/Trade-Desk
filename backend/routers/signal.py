"""GET /api/signal/{symbol} — synthesis surface.

Composes the per-ticker verdict by reading the same intermediate values
the model row and chart annotations already compute. No new data
sources — orchestration only.

`?debug=true` adds the raw inputs and a per-lookup status trace so we
can see which value was None and why when a rule should have fired but
didn't (e.g. LSTM model not loaded for that symbol vs. live IV missing
from the chain).
"""

from __future__ import annotations

import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException

from calculations.pc_ratio import pc_ratio as pc_ratio_calc
from calculations.signal_composer import SignalInputs, compose
from calculations.skew import skew_25d
from schemas.signal import (
    MockSweep,
    SignalDebug,
    SignalReason as SignalReasonOut,
    SignalVerdictOut,
)
from services.alpaca_client import get_quotes
from services.cache import cache
from services.finnhub_client import next_earnings_for
from services.mock_flow import directional_bias, get_mock_sweeps

router = APIRouter(prefix="/api/signal", tags=["signal"])
log = logging.getLogger(__name__)

_ET = ZoneInfo("America/New_York")
_VERDICT_TTL = 60


@router.get("/{symbol}", response_model=SignalVerdictOut)
def get_signal(
    symbol: str,
    include_mock_flow: bool = True,
    debug: bool = False,
) -> SignalVerdictOut:
    """`include_mock_flow=false` excludes the simulated sweep input —
    useful for showing how much the mock moved the verdict.
    `debug=true` surfaces the raw scalars + per-lookup status."""
    symbol = symbol.upper()
    cache_key = f"signal:{symbol}:{int(include_mock_flow)}:{int(debug)}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    inputs, sweeps, lookup_status = _gather_inputs(
        symbol, include_mock_flow=include_mock_flow
    )
    verdict = compose(inputs)

    # Pick a BS structure that actually matches the verdict (the composer's
    # fallback is generic; we have the verdict_type now so we can ask BS for
    # a concrete cost/breakeven on the right strategy).
    structure = _structure_for_verdict(symbol, verdict.verdict_type)
    if structure is not None:
        verdict.suggested_structure, verdict.suggested_structure_detail = structure

    debug_payload: SignalDebug | None = None
    if debug:
        debug_payload = SignalDebug(
            predicted_rv=inputs.predicted_rv,
            iv30=inputs.iv30,
            vrp=inputs.vrp,
            skew_25d=inputs.skew_25d,
            pc_ratio=inputs.pc_ratio,
            regime=inputs.regime,
            regime_confidence=inputs.regime_confidence,
            days_to_earnings=inputs.days_to_earnings,
            mc_prob_up_1sigma=inputs.mc_prob_up_1sigma,
            mc_prob_down_1sigma=inputs.mc_prob_down_1sigma,
            mock_flow_direction=inputs.mock_flow_direction,
            mock_flow_strength=inputs.mock_flow_strength,
            lookup_status=lookup_status,
        )

    response = SignalVerdictOut(
        symbol=verdict.symbol,
        verdict=verdict.verdict,
        verdict_type=verdict.verdict_type,
        conviction=verdict.conviction,
        conviction_label=verdict.conviction_label,
        signals_agreeing=[_reason_to_schema(r) for r in verdict.signals_agreeing],
        signals_conflicting=[_reason_to_schema(r) for r in verdict.signals_conflicting],
        thesis=verdict.thesis,
        suggested_structure=verdict.suggested_structure,
        suggested_structure_detail=verdict.suggested_structure_detail,
        mock_flow_used=verdict.mock_flow_used,
        mock_sweeps=[_sweep_to_schema(s) for s in sweeps] if verdict.mock_flow_used else [],
        debug=debug_payload,
    )
    cache.set(cache_key, response, ttl_seconds=_VERDICT_TTL)
    return response


# -- input gathering --------------------------------------------------------


def _gather_inputs(
    symbol: str, *, include_mock_flow: bool
) -> tuple[SignalInputs, list, dict[str, str]]:
    """Pull every scalar the composer needs from existing services, plus
    optional mock sweep flow. Each lookup is wrapped — a single failing
    leg yields None for that input, not a 500 for the whole route.

    Returns the lookup_status dict alongside the inputs so the debug
    payload can distinguish "ok but returned None" from "raised"."""

    # Local imports avoid the chart→signal→ticker cycle at module load.
    from routers.models import _live_implied_vol, _lstm_vol_forecast, _rf_regime
    from routers.ticker import _chain_with_oi_proxy, _pick_near_term_expiry

    status: dict[str, str] = {}

    lstm = _safe(lambda: _lstm_vol_forecast(symbol), "lstm", status)
    regime = _safe(lambda: _rf_regime(), "regime", status)
    quote = _safe(lambda: get_quotes([symbol]).get(symbol), "quote", status)

    predicted_rv = lstm.predicted_rv_7d if lstm else None

    # LIVE IV — always pull from the chain rather than trusting the LSTM
    # row's cached current_iv30. Empirically the LSTM cache can carry a
    # stale or null IV even when the live chain has a usable ATM IV; this
    # was the root cause of Bug A (MSFT VRP rules not firing). Live chain
    # is the single source of truth for IV here.
    iv30_pct = _safe(lambda: _live_implied_vol(symbol), "iv30", status)
    if iv30_pct is None and lstm and lstm.current_iv30 is not None:
        iv30_pct = lstm.current_iv30
        status["iv30"] = "fallback_to_lstm_cache"

    vrp_val = (
        iv30_pct - predicted_rv
        if (iv30_pct is not None and predicted_rv is not None)
        else None
    )

    chain_data = _safe(lambda: _chain_with_oi_proxy(symbol), "chain", status)
    chain = chain_data[0] if chain_data else None

    skew_val: float | None = None
    pc_val: float | None = None
    if chain and quote is not None:
        near = _pick_near_term_expiry(chain)
        if near:
            skew_val = _safe(lambda: skew_25d(chain, near), "skew", status)
        call_vol = sum(c.volume or 0 for c in chain if c.type == "call")
        put_vol = sum(c.volume or 0 for c in chain if c.type == "put")
        pc_val = pc_ratio_calc(call_vol, put_vol)
        status.setdefault("pc_ratio", "ok" if pc_val is not None else "no_volume")

    # Earnings proximity reuses the same cached Finnhub call as the price header.
    days_to_er: int | None = None
    next_er = _safe(lambda: next_earnings_for(symbol), "next_er", status)
    if next_er:
        try:
            er_date = datetime.fromisoformat(next_er).date()
            days_to_er = (er_date - datetime.now(_ET).date()).days
        except ValueError:
            status["next_er"] = "bad_date_format"

    mc_up: float | None = None
    mc_down: float | None = None
    mc_resp = _safe(lambda: _mc_probs(symbol), "mc", status)
    if mc_resp is not None:
        mc_up, mc_down = mc_resp

    flow_direction = None
    flow_strength = None
    sweeps_out: list = []
    if include_mock_flow:
        sweeps_out = _safe(
            lambda: get_mock_sweeps(symbol, spot=quote.price if quote else None),
            "mock_flow",
            status,
        ) or []
        bias = directional_bias(sweeps_out)
        if bias is not None:
            flow_direction, flow_strength = bias

    inputs = SignalInputs(
        symbol=symbol,
        predicted_rv=predicted_rv,
        iv30=iv30_pct,
        vrp=vrp_val,
        skew_25d=skew_val,
        pc_ratio=pc_val,
        regime=regime.regime if regime else None,
        regime_confidence=regime.confidence if regime else None,
        days_to_earnings=days_to_er,
        mc_prob_up_1sigma=mc_up,
        mc_prob_down_1sigma=mc_down,
        mock_flow_direction=flow_direction,
        mock_flow_strength=flow_strength,
    )
    return inputs, sweeps_out, status


# Map composer verdict types to the BS strategy that actually expresses
# them. sell_premium → iron_condor (defined-risk short-vol; preferred over
# naked short_straddle for blast-radius reasons). buy_premium → long
# straddle (the canonical long-vol structure). Directional verdicts go
# to debit spreads — defined risk, defined cost.
_STRATEGY_FOR_VERDICT: dict[str, tuple[str, str]] = {
    "sell_premium": ("iron_condor", "Iron condor (defined-risk short vol)"),
    "buy_premium": ("long_straddle", "Long straddle (ATM)"),
    "directional_long": ("bull_call_spread", "Bull call spread"),
    "directional_short": ("bear_put_spread", "Bear put spread"),
}


def _structure_for_verdict(symbol: str, verdict_type: str) -> tuple[str, str] | None:
    """Fetch the BS-pricer's cost/BE for the strategy matching this verdict."""
    match = _STRATEGY_FOR_VERDICT.get(verdict_type)
    if match is None:
        return None
    strategy_type, label = match
    try:
        from routers.bs import get_strategy
    except ImportError:
        return None
    try:
        resp = get_strategy(symbol, strategy_type)
    except HTTPException:
        return None
    cost = abs(resp.cost_debit_credit)
    side = "credit" if resp.cost_debit_credit < 0 else "debit"
    be = resp.breakevens
    be_clause = f"BE ${be[0]:.0f}/${be[-1]:.0f}" if be else "no breakeven within ±20% band"
    detail = f"{side} ${cost:.2f}, {be_clause}"
    return label, detail


def _mc_probs(symbol: str) -> tuple[float | None, float | None]:
    """Pull P(>+1σ) and P(<-1σ) from MC. Re-runs MC if the cache is cold —
    same as the chart calling /api/mc once the user opens the panel."""
    from routers.mc import _resolve_default_horizon, run_mc

    horizon = _resolve_default_horizon(symbol)
    resp = run_mc(symbol, horizon=horizon)
    upper = next((p for p in resp.probabilities if p.label.startswith("+1σ")), None)
    lower = next(
        (p for p in resp.probabilities if p.label.startswith("−1σ") or p.label.startswith("-1σ")),
        None,
    )
    return (
        upper.prob_close_above if upper else None,
        (1.0 - lower.prob_close_above) if lower else None,
    )


def _safe(fn, label: str, status: dict[str, str] | None = None):
    """Run `fn` and swallow any exception, logging context. Records a
    status entry: 'ok' / 'returned_none' / 'raised:<ExcClass>'."""
    try:
        result = fn()
    except HTTPException as exc:
        if status is not None:
            status[label] = f"http_{exc.status_code}"
        return None
    except Exception as exc:  # noqa: BLE001
        log.exception("signal: %s lookup failed", label)
        if status is not None:
            status[label] = f"raised:{type(exc).__name__}"
        return None
    if status is not None:
        status[label] = "ok" if result is not None else "returned_none"
    return result


def _reason_to_schema(r) -> SignalReasonOut:
    return SignalReasonOut(label=r.label, detail=r.detail, weight=r.weight)


def _sweep_to_schema(s) -> MockSweep:
    return MockSweep(
        strike=s.strike,
        expiry=s.expiry,
        side=s.side,
        premium=s.premium,
        contracts=s.contracts,
        aggressor=s.aggressor,
        timestamp=s.timestamp,
        is_mock=s.is_mock,
    )
