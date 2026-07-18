"""Portfolio-level Greek aggregation — net book exposure + beta-weighted delta.

Per-position greeks (from the journal analytics engine) arrive scaled to
position units: delta/gamma are share-equivalents (per-share greek × sign ×
contracts × 100), theta/vega are position dollars per day / per vol point.
Theta and vega are directly summable across symbols. Delta and gamma sum
meaningfully per symbol; ACROSS symbols the industry answer is beta-weighting:

    SPY-weighted delta = Σ  delta_i × (S_i / S_SPY) × beta_i

which restates every position as "equivalent SPY shares" — the single number
(ThinkorSwim Analyze / Tastytrade delta) a multi-position book is steered by.

Betas are a static table over the curated trading universe (regression betas
vs SPY, refreshed by hand — the standard brokerage approach; Tasty pins
these too). Unknown symbols fall back to 1.0.
"""

from __future__ import annotations

from typing import Any

# Hand-maintained ~60-day regression betas vs SPY for the tradeable/curated
# universe. Order of magnitude matters more than the second decimal: QQQ
# carries ~1.2× SPY's move, IWM ~1.1×, DIA ~0.95×.
SYMBOL_BETAS: dict[str, float] = {
    "SPY": 1.00,
    "QQQ": 1.18,
    "IWM": 1.12,
    "DIA": 0.95,
}
DEFAULT_BETA = 1.0


def beta_for(symbol: str) -> float:
    return SYMBOL_BETAS.get(symbol.upper(), DEFAULT_BETA)


def aggregate_portfolio_greeks(
    positions: list[dict[str, Any]],
    spy_spot: float | None,
) -> dict[str, Any]:
    """Aggregate per-position greek rows into the portfolio view.

    `positions`: [{symbol, spot, delta, gamma, theta, vega}] — one row per
    open position, greeks already position-scaled (see module docstring).
    `spy_spot`: live SPY price for the beta-weighting normalizer; None →
    beta_weighted_delta is None (never silently unnormalized).

    Returns {positions, net: {...}, beta_weighted_delta, spy_spot,
    by_symbol: [...]} with by_symbol sorted by |beta-weighted delta| desc so
    the biggest exposure reads first.
    """
    net = {"delta": 0.0, "gamma": 0.0, "theta": 0.0, "vega": 0.0}
    per_symbol: dict[str, dict[str, float]] = {}
    for p in positions:
        sym = str(p["symbol"]).upper()
        row = per_symbol.setdefault(
            sym,
            {"spot": float(p.get("spot") or 0.0), "delta": 0.0, "gamma": 0.0,
             "theta": 0.0, "vega": 0.0},
        )
        for k in ("delta", "gamma", "theta", "vega"):
            v = float(p.get(k) or 0.0)
            row[k] += v
            net[k] += v

    by_symbol = []
    bw_total: float | None = 0.0 if spy_spot and spy_spot > 0 else None
    for sym, row in per_symbol.items():
        beta = beta_for(sym)
        bw = (
            row["delta"] * (row["spot"] / spy_spot) * beta
            if bw_total is not None and row["spot"] > 0 and spy_spot
            else None
        )
        if bw_total is not None and bw is not None:
            bw_total += bw
        by_symbol.append(
            {
                "symbol": sym,
                "beta": beta,
                "spot": row["spot"],
                "delta": round(row["delta"], 2),
                "gamma": round(row["gamma"], 4),
                "theta": round(row["theta"], 2),
                "vega": round(row["vega"], 2),
                "beta_weighted_delta": None if bw is None else round(bw, 2),
            }
        )
    by_symbol.sort(
        key=lambda r: abs(r["beta_weighted_delta"] or 0.0), reverse=True
    )

    return {
        "positions": len(positions),
        "net": {k: round(v, 4 if k == "gamma" else 2) for k, v in net.items()},
        "beta_weighted_delta": None if bw_total is None else round(bw_total, 2),
        "spy_spot": spy_spot,
        "by_symbol": by_symbol,
    }
