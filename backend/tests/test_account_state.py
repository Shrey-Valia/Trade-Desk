"""Combine account state — frozen math primitives + per-combine endpoints.

Endpoint tests run through the real auth + purchase flow (conftest
fixtures): every combine is a purchased instance, state is computed for
the signed-in user's ACTIVE combine, and the legacy /state/switch shim
activates the newest combine of the requested tier.
"""

from __future__ import annotations

import pytest

from database import get_session
from models.combine import Combine
from models.trade import Trade
from services.account_tiers import (
    TIERS,
    compute_balance,
    compute_mll,
    is_valid_tier,
    update_hwm,
)
from services.combine_settlement import (
    consistency_ok,
    needs_settlement,
    peak_eod_balance,
    settle_hwm,
    trading_day_start,
)
from tests.conftest import make_combine


# ---------------------------------------------------------------------------
# Math primitives (frozen account_tiers module — tests unchanged)
# ---------------------------------------------------------------------------


def test_tiers_have_correct_starting_balance_and_initial_mll():
    assert TIERS["50K"].starting_balance == 50_000
    assert TIERS["50K"].trailing_distance == 2_000
    assert TIERS["50K"].initial_mll == 48_000

    assert TIERS["100K"].starting_balance == 100_000
    assert TIERS["100K"].trailing_distance == 3_000
    assert TIERS["100K"].initial_mll == 97_000

    assert TIERS["150K"].starting_balance == 150_000
    assert TIERS["150K"].trailing_distance == 4_500
    assert TIERS["150K"].initial_mll == 145_500


def test_tiers_have_topstep_aligned_dll_defaults():
    # Daily Loss Limit ≈ 3% of starting balance, matching the Topstep /
    # Apex industry convention. Display-only for now.
    assert TIERS["50K"].dll_amount == 1_500
    assert TIERS["100K"].dll_amount == 3_000
    assert TIERS["150K"].dll_amount == 4_500


def test_is_valid_tier():
    assert is_valid_tier("50K")
    assert is_valid_tier("100K")
    assert is_valid_tier("150K")
    assert not is_valid_tier("25K")
    assert not is_valid_tier("")


def test_compute_mll_at_initial_hwm():
    # HWM at starting balance → MLL = starting − trailing.
    assert compute_mll("50K", 50_000) == 48_000
    assert compute_mll("100K", 100_000) == 97_000
    assert compute_mll("150K", 150_000) == 145_500


def test_compute_mll_trails_up_with_hwm():
    # 50K combine, HWM walked up to 51_000 → MLL trails to 49_000.
    assert compute_mll("50K", 51_000) == 49_000
    # 100K HWM at 102_500 → MLL 99_500.
    assert compute_mll("100K", 102_500) == 99_500


def test_compute_mll_caps_at_starting_balance():
    # Once HWM > starting + trailing, MLL pins at starting_balance.
    # 50K combine: trailing 2000 → MLL caps at 50_000 once HWM ≥ 52_000.
    assert compute_mll("50K", 52_000) == 50_000
    assert compute_mll("50K", 75_000) == 50_000  # huge HWM, still pinned.
    assert compute_mll("100K", 200_000) == 100_000
    assert compute_mll("150K", 500_000) == 150_000


def test_update_hwm_is_monotonic():
    assert update_hwm(50_000, 50_500) == 50_500   # walks up
    assert update_hwm(50_500, 50_300) == 50_500   # never down
    assert update_hwm(50_500, 50_500) == 50_500   # no change


def test_compute_balance():
    assert compute_balance(50_000, 200, 0) == 50_200
    assert compute_balance(50_000, -300, 50) == 49_750
    assert compute_balance(100_000, 0, 0) == 100_000


# ---------------------------------------------------------------------------
# /api/account/state endpoint — combine-backed
# ---------------------------------------------------------------------------


def test_state_requires_auth(client):
    assert client.get("/api/account/state").status_code == 401


def test_state_404_with_zero_combines(auth_client):
    r = auth_client.get("/api/account/state")
    assert r.status_code == 404
    assert "no active combine" in r.json()["detail"]


def test_first_purchase_activates_and_state_reads_50k(auth_client):
    combine = make_combine(auth_client, "50K")
    r = auth_client.get("/api/account/state")
    assert r.status_code == 200
    body = r.json()
    assert body["active_tier"] == "50K"
    assert body["starting_balance"] == 50_000
    assert body["realized_pnl"] == 0
    assert body["balance"] == 50_000
    assert body["high_water_mark"] == 50_000
    assert body["mll"] == 48_000
    # All three tiers still exposed (purchase catalog).
    assert {t["key"] for t in body["tiers"]} == {"50K", "100K", "150K"}
    # Combine identity fields.
    assert body["combine_id"] == combine["id"]
    assert body["combine_name"] == "50K Combine"
    assert body["account_code"] == combine["account_code"]
    assert body["profit_target"] == 3_000
    assert body["objective_progress"] == 0
    assert len(body["combines"]) == 1


def test_balance_includes_realized_pnl_for_active_combine_only(auth_client):
    c50 = make_combine(auth_client, "50K")
    c100 = make_combine(auth_client, "100K")
    _seed_closed_trade(auth_client, combine_id=c50["id"], realized=200)
    _seed_closed_trade(auth_client, combine_id=c50["id"], realized=-50)
    _seed_closed_trade(auth_client, combine_id=c100["id"], realized=1_000)

    # First purchase auto-activated the 50K combine.
    r = auth_client.get("/api/account/state").json()
    assert r["active_tier"] == "50K"
    assert r["realized_pnl"] == 150          # 200 + (-50)
    assert r["balance"] == 50_150
    assert r["high_water_mark"] == 50_150    # running HWM walks up intraday
    # MLL is FIXED intraday from the settled HWM (settled at purchase =
    # 50_000); the +150 only moves it if still KEPT at the next 5pm-PT close.
    assert r["settled_hwm"] == 50_000
    assert r["mll"] == 48_000

    # Activate the 100K combine — its own +1_000 only.
    r2 = auth_client.post(f"/api/combines/{c100['id']}/activate").json()
    assert r2["realized_pnl"] == 1_000
    assert r2["balance"] == 101_000
    assert r2["high_water_mark"] == 101_000  # running HWM
    assert r2["mll"] == 97_000               # fixed floor from settled 100_000


def test_mll_is_fixed_intraday_then_caps_at_starting_balance_after_settlement(
    auth_client,
):
    c = make_combine(auth_client, "50K")
    # +10_000 KEPT at yesterday's close — an end-of-day gain, so the next
    # settlement trails it.
    _seed_closed_trade(
        auth_client, combine_id=c["id"], realized=10_000, exit_at=_yesterday_et_noon()
    )
    r = auth_client.get("/api/account/state").json()
    assert r["balance"] == 60_000
    assert r["high_water_mark"] == 60_000        # running HWM
    # Intraday the floor stays put: settled at purchase (50_000), so MLL is
    # 48_000 even though the running HWM is now 60_000.
    assert r["settled_hwm"] == 50_000
    assert r["mll"] == 48_000

    # Cross a 5pm-PT settlement: settled HWM re-baselines up to yesterday's
    # 60_000 close, and the MLL trail caps at the starting balance (would be
    # 58_000 uncapped).
    _force_resettlement(auth_client, c["id"])
    r2 = auth_client.get("/api/account/state").json()
    assert r2["settled_hwm"] == 60_000
    assert r2["mll"] == 50_000


def test_two_combines_same_tier_are_independent(auth_client):
    a = make_combine(auth_client, "50K", name="A")
    b = make_combine(auth_client, "50K", name="B")
    _seed_closed_trade(auth_client, combine_id=a["id"], realized=500)
    _seed_closed_trade(auth_client, combine_id=b["id"], realized=-400)

    ra = auth_client.post(f"/api/combines/{a['id']}/activate").json()
    assert ra["realized_pnl"] == 500
    assert ra["high_water_mark"] == 50_500
    rb = auth_client.post(f"/api/combines/{b['id']}/activate").json()
    assert rb["realized_pnl"] == -400
    assert rb["high_water_mark"] == 50_000   # never dipped above start
    assert rb["mll"] == 48_000


def test_hwm_preserved_across_activations(auth_client):
    a = make_combine(auth_client, "50K")
    b = make_combine(auth_client, "100K")
    _seed_closed_trade(auth_client, combine_id=a["id"], realized=300)
    auth_client.get("/api/account/state")  # commits HWM 50_300 on A

    auth_client.post(f"/api/combines/{b['id']}/activate")
    _seed_closed_trade(auth_client, combine_id=b["id"], realized=-100)
    auth_client.get("/api/account/state")

    back = auth_client.post(f"/api/combines/{a['id']}/activate").json()
    assert back["active_tier"] == "50K"
    assert back["realized_pnl"] == 300
    # HWM stays at A's peak even after leaving and coming back.
    assert back["high_water_mark"] == 50_300
    # MLL is the fixed-intraday floor from the settled HWM (settled at
    # purchase = 50_000); the intraday +300 doesn't move it.
    assert back["mll"] == 48_000


# ---------------------------------------------------------------------------
# Daily Loss Limit (DLL) — display-only signal, per combine
# ---------------------------------------------------------------------------


def test_dll_clean_state_returns_zero_used(auth_client):
    make_combine(auth_client, "50K")
    r = auth_client.get("/api/account/state").json()
    assert r["dll_used"] == 0
    assert r["dll_budget"] == 1_500           # 50K tier default
    assert r["dll_breached"] is False
    by_key = {t["key"]: t["dll_amount"] for t in r["tiers"]}
    assert by_key == {"50K": 1_500, "100K": 3_000, "150K": 4_500}


def test_dll_used_counts_todays_realized_losses_only(auth_client):
    c = make_combine(auth_client, "50K")
    _seed_closed_trade(auth_client, combine_id=c["id"], realized=-300, exit_at=_today_et_noon())
    _seed_closed_trade(auth_client, combine_id=c["id"], realized=-500, exit_at=_today_et_noon())
    _seed_closed_trade(auth_client, combine_id=c["id"], realized=+100, exit_at=_today_et_noon())
    r = auth_client.get("/api/account/state").json()
    # -300 + -500 + +100 = -700 → dll_used = 700
    assert r["dll_used"] == 700
    assert r["dll_breached"] is False        # 700 < 1500


def test_dll_used_ignores_yesterdays_losses(auth_client):
    c = make_combine(auth_client, "50K")
    _seed_closed_trade(auth_client, combine_id=c["id"], realized=-1_000, exit_at=_yesterday_et_noon())
    _seed_closed_trade(auth_client, combine_id=c["id"], realized=-1_000, exit_at=_yesterday_et_noon())
    _seed_closed_trade(auth_client, combine_id=c["id"], realized=-200, exit_at=_today_et_noon())
    r = auth_client.get("/api/account/state").json()
    assert r["dll_used"] == 200
    assert r["dll_breached"] is False


def test_dll_breached_when_realized_loss_exceeds_budget(auth_client):
    c = make_combine(auth_client, "50K")
    _seed_closed_trade(auth_client, combine_id=c["id"], realized=-900, exit_at=_today_et_noon())
    _seed_closed_trade(auth_client, combine_id=c["id"], realized=-700, exit_at=_today_et_noon())
    r = auth_client.get("/api/account/state").json()
    assert r["dll_used"] == 1_600
    assert r["dll_breached"] is True


def test_dll_used_is_combine_isolated(auth_client):
    c50 = make_combine(auth_client, "50K")
    c100 = make_combine(auth_client, "100K")
    _seed_closed_trade(auth_client, combine_id=c50["id"], realized=-200, exit_at=_today_et_noon())
    _seed_closed_trade(auth_client, combine_id=c100["id"], realized=-2_500, exit_at=_today_et_noon())

    r50 = auth_client.get("/api/account/state").json()
    assert r50["active_tier"] == "50K"
    assert r50["dll_used"] == 200
    assert r50["dll_budget"] == 1_500

    r100 = auth_client.post(f"/api/combines/{c100['id']}/activate").json()
    assert r100["active_tier"] == "100K"
    assert r100["dll_used"] == 2_500
    assert r100["dll_budget"] == 3_000
    assert r100["dll_breached"] is False     # 2500 < 3000


# ---------------------------------------------------------------------------
# Settlement engine — pure helpers (services/combine_settlement)
# ---------------------------------------------------------------------------


def test_settle_hwm_advances_up_only():
    assert settle_hwm(50_000, 50_150) == 50_150   # re-baselines up to the EOD basis
    assert settle_hwm(50_150, 50_000) == 50_150   # never down
    assert settle_hwm(50_000, 50_000) == 50_000


def test_peak_eod_balance_trails_completed_closes_only():
    from datetime import timedelta

    d0 = trading_day_start(_now())     # current (incomplete) trading day
    d1 = d0 - timedelta(days=1)
    d2 = d0 - timedelta(days=2)

    # No completed days → the peak is the starting balance.
    assert peak_eod_balance(50_000, {}, d0) == 50_000
    # Today's bucket is in flight — ignored no matter how large.
    assert peak_eod_balance(50_000, {d0: 9_999.0}, d0) == 50_000
    # A give-back day: the intraday peak is invisible, only the close counts.
    assert peak_eod_balance(50_000, {d1: 0.0}, d0) == 50_000
    # The HIGHEST completed close wins, not the latest one.
    assert peak_eod_balance(50_000, {d2: 3_000.0, d1: -3_000.0}, d0) == 53_000
    # Losing closes never pull the basis below the start.
    assert peak_eod_balance(50_000, {d2: -1_000.0, d1: -500.0}, d0) == 50_000


def test_needs_settlement_when_never_settled_or_boundary_passed():
    now = _now()
    assert needs_settlement(None, now) is True              # never settled
    assert needs_settlement(now, now) is False              # already this day
    # A settlement stamped before the current trading day → settle again.
    assert needs_settlement(trading_day_start(now), now) is False
    from datetime import timedelta

    assert needs_settlement(trading_day_start(now) - timedelta(seconds=1), now) is True


def test_consistency_rule():
    assert consistency_ok(1_600, 3_200) is True    # exactly 50%
    assert consistency_ok(2_900, 3_100) is False   # one day dominates
    assert consistency_ok(0, 0) is True            # no profit yet → vacuous
    assert consistency_ok(-100, -500) is True      # net loss → vacuous


# ---------------------------------------------------------------------------
# EOD trailing convention — settlement trails the close, not the intraday peak
# ---------------------------------------------------------------------------


def test_settlement_ignores_intraday_peak_given_back(auth_client):
    """A +3_000 morning given back by the close moves the floor $0 — the
    advertised convention. The old engine trailed the intraday realized
    peak (settled 53_000 → MLL 50_000); the EOD rule leaves 48_000."""
    c = make_combine(auth_client, "50K")
    _seed_closed_trade(
        auth_client, combine_id=c["id"], realized=3_000, exit_at=_yesterday_et_noon()
    )
    r = auth_client.get("/api/account/state").json()
    assert r["high_water_mark"] == 53_000    # intraday running peak observed
    # ... given back before the close.
    _seed_closed_trade(
        auth_client, combine_id=c["id"], realized=-3_000, exit_at=_yesterday_et_noon()
    )

    _force_resettlement(auth_client, c["id"])
    r2 = auth_client.get("/api/account/state").json()
    assert r2["balance"] == 50_000
    assert r2["settled_hwm"] == 50_000       # floor unmoved
    assert r2["mll"] == 48_000
    # The running HWM re-seeds to the balance at the boundary — it is
    # intraday display only and never drives the MLL.
    assert r2["high_water_mark"] == 50_000


def test_settlement_trails_gains_kept_at_the_close(auth_client):
    c = make_combine(auth_client, "50K")
    # +1_500 KEPT at yesterday's close → the floor rises by the kept amount.
    _seed_closed_trade(
        auth_client, combine_id=c["id"], realized=1_500, exit_at=_yesterday_et_noon()
    )
    _force_resettlement(auth_client, c["id"])
    r = auth_client.get("/api/account/state").json()
    assert r["settled_hwm"] == 51_500
    assert r["mll"] == 49_500                # 51_500 − 2_000, below the cap


def test_settlement_floor_never_moves_down_across_days(auth_client):
    c = make_combine(auth_client, "50K")
    _seed_closed_trade(
        auth_client, combine_id=c["id"], realized=1_000, exit_at=_days_ago_et_noon(2)
    )
    _force_resettlement(auth_client, c["id"])
    r = auth_client.get("/api/account/state").json()
    assert r["settled_hwm"] == 51_000
    assert r["mll"] == 49_000

    # A losing day closes lower — the floor holds, it never trails down.
    _seed_closed_trade(
        auth_client, combine_id=c["id"], realized=-800, exit_at=_yesterday_et_noon()
    )
    _force_resettlement(auth_client, c["id"])
    r2 = auth_client.get("/api/account/state").json()
    assert r2["balance"] == 50_200
    assert r2["settled_hwm"] == 51_000       # monotone
    assert r2["mll"] == 49_000


def test_lazy_settlement_across_multiple_days_trails_the_peak_close(auth_client):
    """Two boundaries pass without a read: the single lazy settlement still
    trails the HIGHEST completed close (51_000), not just the latest
    boundary's balance (50_200) — the floor is read-timing independent."""
    c = make_combine(auth_client, "50K")
    _seed_closed_trade(
        auth_client, combine_id=c["id"], realized=1_000, exit_at=_days_ago_et_noon(2)
    )
    _seed_closed_trade(
        auth_client, combine_id=c["id"], realized=-800, exit_at=_yesterday_et_noon()
    )
    _force_resettlement(auth_client, c["id"])
    r = auth_client.get("/api/account/state").json()
    assert r["balance"] == 50_200
    assert r["settled_hwm"] == 51_000
    assert r["mll"] == 49_000


# ---------------------------------------------------------------------------
# Settlement engine — PASS / FAIL / day-lock through the endpoint
# ---------------------------------------------------------------------------


def test_combine_fails_permanently_on_mll_breach(auth_client):
    c = make_combine(auth_client, "50K")
    # Floor is 48_000 (settled at purchase). A -2_500 realized loss drops
    # balance to 47_500 ≤ 48_000 → FAILED.
    _seed_closed_trade(auth_client, combine_id=c["id"], realized=-2_500)
    r = auth_client.get("/api/account/state").json()
    assert r["balance"] == 47_500
    assert r["status"] == "failed"

    # FAILED is terminal: a later winning trade does NOT un-fail it.
    _seed_closed_trade(auth_client, combine_id=c["id"], realized=+5_000)
    r2 = auth_client.get("/api/account/state").json()
    assert r2["balance"] == 52_500
    assert r2["status"] == "failed"


def test_combine_passes_on_target_min_days_and_consistency(auth_client):
    c = make_combine(auth_client, "50K")
    # 50K target = 3_000. Two distinct trading days, neither > 50% of total.
    _seed_closed_trade(
        auth_client, combine_id=c["id"], realized=1_600, exit_at=_yesterday_et_noon()
    )
    _seed_closed_trade(
        auth_client, combine_id=c["id"], realized=1_600, exit_at=_today_et_noon()
    )
    r = auth_client.get("/api/account/state").json()
    assert r["realized_pnl"] == 3_200
    assert r["days_traded"] == 2
    assert r["consistency_ok"] is True
    assert r["status"] == "passed"


def test_pass_blocked_until_min_trading_days(auth_client):
    c = make_combine(auth_client, "50K")
    # Target met in a SINGLE day → min-trading-days not satisfied.
    _seed_closed_trade(
        auth_client, combine_id=c["id"], realized=3_500, exit_at=_today_et_noon()
    )
    r = auth_client.get("/api/account/state").json()
    assert r["realized_pnl"] == 3_500          # target met
    assert r["days_traded"] == 1
    assert r["min_trading_days"] == 2
    assert r["status"] == "active"             # not yet passed


def test_pass_blocked_when_consistency_violated(auth_client):
    c = make_combine(auth_client, "50K")
    # Two days, target met, but one day is 2_900/3_100 ≈ 94% > 50%.
    _seed_closed_trade(
        auth_client, combine_id=c["id"], realized=2_900, exit_at=_yesterday_et_noon()
    )
    _seed_closed_trade(
        auth_client, combine_id=c["id"], realized=200, exit_at=_today_et_noon()
    )
    r = auth_client.get("/api/account/state").json()
    assert r["realized_pnl"] == 3_100          # target met
    assert r["days_traded"] == 2
    assert r["consistency_ok"] is False
    assert r["status"] == "active"             # blocked by consistency


def test_day_locked_at_dll_without_failing(auth_client):
    c = make_combine(auth_client, "50K")
    # Exactly the DLL budget (1_500): day-locks (≥) but does not breach (>),
    # and balance 48_500 stays above the 48_000 floor → still active.
    _seed_closed_trade(
        auth_client, combine_id=c["id"], realized=-1_500, exit_at=_today_et_noon()
    )
    r = auth_client.get("/api/account/state").json()
    assert r["dll_used"] == 1_500
    assert r["day_locked"] is True
    assert r["dll_breached"] is False          # uses >, not ≥
    assert r["status"] == "active"


# ---------------------------------------------------------------------------
# Funded-account lifecycle — auto-fund, reset, payout, events
# ---------------------------------------------------------------------------


def test_pass_auto_funds_and_activation_rebaselines(auth_client):
    c = make_combine(auth_client, "50K")
    # Two distinct days, target met (3_200 ≥ 3_000), consistency ok → passes.
    _seed_closed_trade(
        auth_client, combine_id=c["id"], realized=1_600, exit_at=_yesterday_et_noon()
    )
    _seed_closed_trade(
        auth_client, combine_id=c["id"], realized=1_600, exit_at=_today_et_noon()
    )
    r = auth_client.get("/api/account/state").json()
    assert r["status"] == "passed"
    assert r["funded"] is True
    # Default activation path → payouts locked until the $149 fee is paid.
    assert r["activation_required"] is True
    assert r["payout_eligible"] == 0
    # Activation restarts funded-stage accounting at the tier start: the
    # eval profit stays with the firm (NOT instantly withdrawable) and the
    # HWM/MLL re-seed.
    assert auth_client.post(f"/api/combines/{c['id']}/activate-account").status_code == 200
    r2 = auth_client.get("/api/account/state").json()
    assert r2["activation_required"] is False
    assert r2["payout_eligible"] == 0
    assert r2["realized_pnl"] == 0
    assert r2["balance"] == 50_000
    assert r2["settled_hwm"] == 50_000
    assert r2["mll"] == 48_000
    # Funded-stage profit accrues payout at the 80/20 split from here.
    _seed_closed_trade(auth_client, combine_id=c["id"], realized=1_000)
    r3 = auth_client.get("/api/account/state").json()
    assert r3["balance"] == 51_000
    assert r3["payout_eligible"] == pytest.approx(800)  # 0.80 × 1_000


def test_reset_failed_combine_restarts_eval_and_keeps_history(auth_client):
    c = make_combine(auth_client, "50K")
    # -2_500 → balance 47_500 ≤ 48_000 floor → FAILED.
    _seed_closed_trade(auth_client, combine_id=c["id"], realized=-2_500)
    assert auth_client.get("/api/account/state").json()["status"] == "failed"

    rr = auth_client.post(f"/api/combines/{c['id']}/reset")
    assert rr.status_code == 200
    body = rr.json()
    assert body["outcome"] == "active"
    assert body["funded"] is False

    state = auth_client.get("/api/account/state").json()
    assert state["status"] == "active"
    # The pre-reset trade is excluded from the eval (entry before eval_reset_at).
    assert state["realized_pnl"] == 0
    assert state["balance"] == 50_000
    # History is preserved — the trade row still exists in the journal.
    trades = auth_client.get("/api/journal/trades").json()["trades"]
    assert len(trades) == 1


def test_reset_rejected_when_not_failed(auth_client):
    c = make_combine(auth_client, "50K")
    r = auth_client.post(f"/api/combines/{c['id']}/reset")
    assert r.status_code == 409


def test_payout_request_nets_and_blocks_when_empty(auth_client):
    c = make_combine(auth_client, "50K")
    _seed_closed_trade(
        auth_client, combine_id=c["id"], realized=1_600, exit_at=_yesterday_et_noon()
    )
    _seed_closed_trade(
        auth_client, combine_id=c["id"], realized=1_600, exit_at=_today_et_noon()
    )
    auth_client.get("/api/account/state")  # funds the account
    # Activate the funded account (activation path) to unlock payouts.
    assert auth_client.post(f"/api/combines/{c['id']}/activate-account").status_code == 200

    # FUNDED-STAGE profit across five winning days (each ≥ the $150 bar) so
    # the payout policy gates clear: 5 × 640 = 3_200 since activation.
    from datetime import timedelta

    for offset in range(5):
        _seed_closed_trade(
            auth_client,
            combine_id=c["id"],
            realized=640,
            exit_at=_now() - timedelta(days=offset),
        )

    p = auth_client.post(f"/api/combines/{c['id']}/payout")
    assert p.status_code == 200, p.text
    assert p.json()["amount"] == pytest.approx(2_560)  # 0.80 × 3_200

    # Available is now zero → a second request is blocked.
    assert auth_client.post(f"/api/combines/{c['id']}/payout").status_code == 409

    card = next(
        x
        for x in auth_client.get("/api/combines").json()["combines"]
        if x["id"] == c["id"]
    )
    assert card["payout_requested"] == pytest.approx(2_560)
    assert card["payout_eligible"] == 0
    # The booked payout DEBITS the balance: 50_000 + 3_200 − 2_560.
    assert card["balance"] == pytest.approx(50_640)


def test_payout_rejected_when_not_funded(auth_client):
    c = make_combine(auth_client, "50K")
    assert auth_client.post(f"/api/combines/{c['id']}/payout").status_code == 409


def test_events_ledger_records_funded(auth_client):
    c = make_combine(auth_client, "50K")
    _seed_closed_trade(
        auth_client, combine_id=c["id"], realized=1_600, exit_at=_yesterday_et_noon()
    )
    _seed_closed_trade(
        auth_client, combine_id=c["id"], realized=1_600, exit_at=_today_et_noon()
    )
    auth_client.get("/api/account/state")  # logs the funded event
    events = auth_client.get("/api/combines/events").json()
    assert any(e["type"] == "funded" for e in events)


def test_events_ledger_records_failed_and_reset(auth_client):
    c = make_combine(auth_client, "50K")
    _seed_closed_trade(auth_client, combine_id=c["id"], realized=-2_500)
    auth_client.get("/api/account/state")  # logs failed
    auth_client.post(f"/api/combines/{c['id']}/reset")  # logs reset
    types = {e["type"] for e in auth_client.get("/api/combines/events").json()}
    assert "failed" in types
    assert "reset" in types


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _seed_closed_trade(client, combine_id: int, realized: float, exit_at=None) -> None:
    """Write a closed trade directly via the test session so we don't
    have to route through the journal entry validation."""
    session = next(client.app.dependency_overrides[get_session]())
    trade = Trade(
        symbol="SPY",
        strategy="long_straddle",
        entry_date=_now(),
        entry_underlying_price=400.0,
        net_debit_credit=0.0,
        status="closed",
        is_paper=True,
        notes="seeded",
        tier="50K",
        combine_id=combine_id,
        exit_date=exit_at if exit_at is not None else _now(),
        exit_underlying_price=400.0,
        realized_pnl=realized,
        legs_json="[]",
    )
    session.add(trade)
    session.commit()
    session.close()


def _force_resettlement(client, combine_id: int) -> None:
    """Clear a combine's last_settled_at so the next state read crosses a
    5pm-PT boundary and re-baselines the settled HWM up to the peak
    END-OF-DAY balance among completed trading days. Lets a test exercise
    post-settlement behavior (e.g. the MLL cap) without waiting for a real
    5pm-PT rollover."""
    session = next(client.app.dependency_overrides[get_session]())
    combine = session.get(Combine, combine_id)
    combine.last_settled_at = None
    session.add(combine)
    session.commit()
    session.close()


def _now():
    from datetime import datetime, timezone

    return datetime.now(timezone.utc)


def _today_et_noon():
    """Today at 12:00 ET — safely inside today's ET trading day on any
    UTC offset. Returned as a UTC-aware datetime to match how the
    journal POST path persists exit timestamps."""
    from datetime import datetime, time
    from zoneinfo import ZoneInfo

    et = ZoneInfo("America/New_York")
    now_et = datetime.now(et)
    noon_et = datetime.combine(now_et.date(), time(12, 0), tzinfo=et)
    return noon_et.astimezone(ZoneInfo("UTC"))


def _yesterday_et_noon():
    return _days_ago_et_noon(1)


def _days_ago_et_noon(days: int):
    """N days ago at 12:00 ET — inside a COMPLETED 5pm-PT trading day, so a
    forced resettlement counts it in the end-of-day balance basis."""
    from datetime import datetime, time, timedelta
    from zoneinfo import ZoneInfo

    et = ZoneInfo("America/New_York")
    day = datetime.now(et).date() - timedelta(days=days)
    noon_et = datetime.combine(day, time(12, 0), tzinfo=et)
    return noon_et.astimezone(ZoneInfo("UTC"))
