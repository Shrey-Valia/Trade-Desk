"""Combine account state — frozen math primitives + per-combine endpoints.

Endpoint tests run through the real auth + purchase flow (conftest
fixtures): every combine is a purchased instance, state is computed for
the signed-in user's ACTIVE combine, and the legacy /state/switch shim
activates the newest combine of the requested tier.
"""

from __future__ import annotations

from database import get_session
from models.trade import Trade
from services.account_tiers import (
    TIERS,
    compute_balance,
    compute_mll,
    is_valid_tier,
    update_hwm,
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
    assert TIERS["100K"].trailing_distance == 4_000
    assert TIERS["100K"].initial_mll == 96_000

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
    assert compute_mll("100K", 100_000) == 96_000
    assert compute_mll("150K", 150_000) == 145_500


def test_compute_mll_trails_up_with_hwm():
    # 50K combine, HWM walked up to 51_000 → MLL trails to 49_000.
    assert compute_mll("50K", 51_000) == 49_000
    # 100K HWM at 102_500 → MLL 98_500.
    assert compute_mll("100K", 102_500) == 98_500


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


def test_legacy_switch_activates_combine_of_tier(auth_client):
    make_combine(auth_client, "50K")
    make_combine(auth_client, "100K")
    r = auth_client.post("/api/account/state/switch", json={"tier": "100K"})
    assert r.status_code == 200
    body = r.json()
    assert body["active_tier"] == "100K"
    assert body["starting_balance"] == 100_000
    assert body["mll"] == 96_000


def test_legacy_switch_404_when_no_combine_on_tier(auth_client):
    make_combine(auth_client, "50K")
    r = auth_client.post("/api/account/state/switch", json={"tier": "150K"})
    assert r.status_code == 404


def test_switch_to_unknown_tier_fails(auth_client):
    r = auth_client.post("/api/account/state/switch", json={"tier": "25K"})
    # Pydantic Literal rejects with 422; that's the safer 4xx for us.
    assert r.status_code in (400, 422)


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
    assert r["high_water_mark"] == 50_150
    assert r["mll"] == 48_150                # trails up by +150

    # Activate the 100K combine — its own +1_000 only.
    r2 = auth_client.post(f"/api/combines/{c100['id']}/activate").json()
    assert r2["realized_pnl"] == 1_000
    assert r2["balance"] == 101_000
    assert r2["high_water_mark"] == 101_000
    assert r2["mll"] == 97_000


def test_mll_is_capped_at_starting_balance_via_endpoint(auth_client):
    c = make_combine(auth_client, "50K")
    _seed_closed_trade(auth_client, combine_id=c["id"], realized=10_000)
    r = auth_client.get("/api/account/state").json()
    assert r["balance"] == 60_000
    assert r["high_water_mark"] == 60_000
    # MLL would be 58_000 if uncapped; caps at 50_000.
    assert r["mll"] == 50_000


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
    assert back["mll"] == 48_300


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
    from datetime import datetime, time, timedelta
    from zoneinfo import ZoneInfo

    et = ZoneInfo("America/New_York")
    yday = datetime.now(et).date() - timedelta(days=1)
    noon_et = datetime.combine(yday, time(12, 0), tzinfo=et)
    return noon_et.astimezone(ZoneInfo("UTC"))
