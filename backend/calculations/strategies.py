"""Canonical strategy-name vocabulary for the journal / analytics layer.

`STRATEGY_TYPES` is the closed set of strategy labels a MANUAL journal trade
may carry (schemas.journal validates the `strategy` field against it).

There is deliberately no server-side leg builder here. Execution presets — the
legs a builder auto-places when you pick "iron condor", "vertical", etc. — live
client-side in `frontend/src/components/positions/tools/StrategyBuilder.tsx`
(`presetLegs`), and the /open-multi endpoint re-prices whatever legs it is
handed. The former `build_legs` in this module duplicated that mapping, was
never called by any endpoint, and had drifted out of sync with the client
presets (different condor wing widths); it was removed 2026-08-05 so there is a
single source of truth for what each structure's legs are.
"""

from __future__ import annotations

STRATEGY_TYPES = (
    "long_straddle",
    "long_call",
    "long_put",
    "short_call",
    "short_put",
    "bull_call_spread",
    "bear_put_spread",
    "bull_put_spread",
    "bear_call_spread",
    "long_strangle",
    "iron_condor",
    "calendar_spread",
)
