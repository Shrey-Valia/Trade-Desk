"""Copy trading — config endpoint + the lead→followers mirror service
(opens with multiplier + clamp, and close cascade)."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select

from models.combine import Combine
from models.trade import Trade
from services.copy_trade import mirror_close, mirror_open
from tests.conftest import make_combine


def _lead_ratio_trade(session, combine: Combine, ratios: list[int]) -> Trade:
    """A multi-leg lead trade whose legs carry the given per-leg contract counts
    (a ratio structure, e.g. [1, 2, 1] for a butterfly)."""
    t = Trade(
        symbol="SPY",
        strategy="butterfly",
        entry_date=datetime.now(timezone.utc),
        entry_underlying_price=500.0,
        net_debit_credit=-1000.0,
        status="open",
        order_type="market",
        is_paper=True,
        notes="ratio structure",
        tier=combine.tier,
        combine_id=combine.id,
    )
    t.legs = [
        {
            "side": "call",
            "action": "buy" if i != 1 else "sell",
            "strike": 500.0 + i * 5,
            "expiry": "2026-06-19",
            "contracts": n,
            "entry_price": 2.0,
        }
        for i, n in enumerate(ratios)
    ]
    t.tags = ["0dte"]
    t.mistake_tags = []
    session.add(t)
    session.commit()
    session.refresh(t)
    return t


def _lead_trade(
    session,
    combine: Combine,
    contracts: int = 5,
    status: str = "open",
    *,
    stop_loss: float | None = None,
    take_profit: float | None = None,
    trail_amount: float | None = None,
    trail_hwm: float | None = None,
) -> Trade:
    t = Trade(
        symbol="SPY",
        strategy="long_call",
        entry_date=datetime.now(timezone.utc),
        entry_underlying_price=500.0,
        net_debit_credit=-1000.0,
        status=status,
        order_type="limit" if status == "working" else "market",
        limit_price=2.0 if status == "working" else None,
        stop_loss=stop_loss,
        take_profit=take_profit,
        trail_amount=trail_amount,
        trail_hwm=trail_hwm,
        is_paper=True,
        notes="0DTE long call · indicative fill",
        tier=combine.tier,
        combine_id=combine.id,
    )
    t.legs = [
        {
            "side": "call",
            "action": "buy",
            "strike": 500.0,
            "expiry": "2026-06-19",
            "contracts": contracts,
            "entry_price": 2.0,
        }
    ]
    t.tags = ["0dte"]
    t.mistake_tags = []
    session.add(t)
    session.commit()
    session.refresh(t)
    return t


def _set_config(client, lead_id, followers):
    """followers: list of (combine_id, multiplier)."""
    return client.put(
        "/api/combines/copy-config",
        json={
            "lead_combine_id": lead_id,
            "followers": [{"combine_id": c, "multiplier": m} for c, m in followers],
        },
    )


# --- config endpoint ------------------------------------------------------


def test_copy_config_sets_lead_followers_and_multiplier(auth_client):
    lead = make_combine(auth_client, "50K", name="Lead")
    f2 = make_combine(auth_client, "50K", name="F2")
    f3 = make_combine(auth_client, "50K", name="F3")

    res = _set_config(auth_client, lead["id"], [(f2["id"], 0.5), (f3["id"], 2.0)])
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["copy_lead_combine_id"] == lead["id"]
    by_id = {c["id"]: c for c in body["combines"]}
    assert by_id[lead["id"]]["copy_follow"] is False  # lead can't follow itself
    assert by_id[f2["id"]]["copy_follow"] is True
    assert by_id[f2["id"]]["copy_multiplier"] == 0.5
    assert by_id[f3["id"]]["copy_multiplier"] == 2.0


def test_copy_config_rejects_foreign_combine(auth_client, second_user_client):
    mine = make_combine(auth_client, "50K")
    theirs = make_combine(second_user_client, "50K")
    res = _set_config(auth_client, mine["id"], [(theirs["id"], 1.0)])
    assert res.status_code == 404


def test_copy_config_off_clears_followers(auth_client):
    lead = make_combine(auth_client, "50K")
    f2 = make_combine(auth_client, "50K")
    _set_config(auth_client, lead["id"], [(f2["id"], 1.0)])
    body = _set_config(auth_client, None, []).json()
    assert body["copy_lead_combine_id"] is None
    assert all(c["copy_follow"] is False for c in body["combines"])


# --- mirror opens ---------------------------------------------------------


def test_mirror_clamps_to_follower_cap_and_tags(auth_client, session_factory):
    lead = make_combine(auth_client, "50K", name="Lead")
    f2 = make_combine(auth_client, "50K", name="F2")
    f3 = make_combine(auth_client, "50K", name="F3")
    _set_config(auth_client, lead["id"], [(f2["id"], 1.0), (f3["id"], 1.0)])

    with session_factory() as s:
        lead_c = s.get(Combine, lead["id"])
        trade = _lead_trade(s, lead_c, contracts=10)
        result = mirror_open(s, lead_c, trade)

        assert sorted(result.mirrored) == sorted([f2["id"], f3["id"]])
        for fid in (f2["id"], f3["id"]):
            mt = s.execute(select(Trade).where(Trade.combine_id == fid)).scalars().one()
            assert mt.legs[0]["contracts"] == 5  # 50K cap → clamped from 10
            assert "copy" in mt.tags
            assert mt.copied_from_trade_id == trade.id
            assert "copied from Lead" in (mt.notes or "")


def test_mirror_preserves_ratio_and_skips_rather_than_distorts(
    auth_client, session_factory
):
    """A ratio structure must mirror ratio-intact when it fits, and be SKIPPED
    (not per-leg clamped into a different position) when a leg overflows the
    follower's cap. 50K cap = 5 contracts."""
    lead = make_combine(auth_client, "50K", name="Lead")
    fits = make_combine(auth_client, "50K", name="Fits")
    over = make_combine(auth_client, "50K", name="Over")

    # Case 1: [1,2,1] total 4 ≤ cap → mirrors ratio-intact.
    _set_config(auth_client, lead["id"], [(fits["id"], 1.0)])
    with session_factory() as s:
        lead_c = s.get(Combine, lead["id"])
        trade = _lead_ratio_trade(s, lead_c, [1, 2, 1])
        result = mirror_open(s, lead_c, trade)
        assert fits["id"] in result.mirrored
        mt = s.execute(
            select(Trade).where(Trade.combine_id == fits["id"])
        ).scalars().one()
        assert [leg["contracts"] for leg in mt.legs] == [1, 2, 1]  # ratio intact

    # Case 2: [1,6,1] has a leg (6) over the cap → would distort to [1,5,1]
    # under the old per-leg clamp; must be SKIPPED instead.
    _set_config(auth_client, lead["id"], [(over["id"], 1.0)])
    with session_factory() as s:
        lead_c = s.get(Combine, lead["id"])
        big = _lead_ratio_trade(s, lead_c, [1, 6, 1])
        result = mirror_open(s, lead_c, big)
        assert over["id"] not in result.mirrored  # skipped, not distorted
        assert any(fid == over["id"] for fid, _ in result.skipped)
        # No mirrored trade was created for the overflowing structure.
        assert (
            s.execute(
                select(Trade).where(Trade.combine_id == over["id"])
            ).scalars().first()
            is None
        )


def test_mirror_applies_multiplier(auth_client, session_factory):
    lead = make_combine(auth_client, "50K", name="Lead")
    f2 = make_combine(auth_client, "50K", name="Half")
    f3 = make_combine(auth_client, "50K", name="Full")
    _set_config(auth_client, lead["id"], [(f2["id"], 0.5), (f3["id"], 1.0)])

    with session_factory() as s:
        lead_c = s.get(Combine, lead["id"])
        trade = _lead_trade(s, lead_c, contracts=2)  # within the 50K cap of 5
        mirror_open(s, lead_c, trade)

        half = s.execute(select(Trade).where(Trade.combine_id == f2["id"])).scalars().one()
        full = s.execute(select(Trade).where(Trade.combine_id == f3["id"])).scalars().one()
        assert half.legs[0]["contracts"] == 1  # 2 × 0.5
        assert full.legs[0]["contracts"] == 2  # 2 × 1.0


def test_mirror_skips_ineligible_follower(auth_client, session_factory):
    lead = make_combine(auth_client, "50K", name="Lead")
    f2 = make_combine(auth_client, "50K", name="F2")
    f3 = make_combine(auth_client, "50K", name="F3")
    _set_config(auth_client, lead["id"], [(f2["id"], 1.0), (f3["id"], 1.0)])

    with session_factory() as s:
        f3_c = s.get(Combine, f3["id"])
        f3_c.outcome = "failed"
        s.add(f3_c)
        s.commit()

        lead_c = s.get(Combine, lead["id"])
        trade = _lead_trade(s, lead_c)
        result = mirror_open(s, lead_c, trade)

        assert result.mirrored == [f2["id"]]
        assert (f3["id"], "failed eval") in result.skipped


def test_mirror_noop_when_not_lead(auth_client, session_factory):
    a = make_combine(auth_client, "50K")
    b = make_combine(auth_client, "50K")
    with session_factory() as s:
        a_c = s.get(Combine, a["id"])
        trade = _lead_trade(s, a_c)
        result = mirror_open(s, a_c, trade)
        assert result.mirrored == []
        assert s.execute(
            select(Trade).where(Trade.combine_id == b["id"])
        ).scalars().all() == []


# --- mirror closes (cascade) ----------------------------------------------


def test_lead_close_cascades_to_followers_scaled(
    auth_client, session_factory, monkeypatch
):
    # The lead's realized is RECOMPUTED server-side (WS1 integrity fix) — the
    # client's realized_pnl is ignored — so pin the recompute spot via a mocked
    # quote and assert the follower gets the LEAD'S RECOMPUTED P&L × the
    # contract ratio (1/2), whatever that recompute is.
    import routers.journal as journal_router
    from dataclasses import dataclass

    @dataclass
    class _Q:
        price: float

    monkeypatch.setattr(
        journal_router, "get_quotes", lambda syms: {s: _Q(price=505.0) for s in syms}
    )

    lead = make_combine(auth_client, "50K", name="Lead")
    f2 = make_combine(auth_client, "50K", name="Half")
    _set_config(auth_client, lead["id"], [(f2["id"], 0.5)])

    with session_factory() as s:
        lead_c = s.get(Combine, lead["id"])
        trade = _lead_trade(s, lead_c, contracts=2)  # follower → 1 contract (×0.5)
        mirror_open(s, lead_c, trade)
        lead_id = trade.id

    # Close the lead through the real journal endpoint → cascade. realized_pnl
    # in the body is ignored; the server recomputes.
    res = auth_client.patch(
        f"/api/journal/trades/{lead_id}",
        json={"status": "closed", "realized_pnl": 400, "exit_underlying_price": 505.0},
    )
    assert res.status_code == 200, res.text
    lead_realized = res.json()["realized_pnl"]
    assert lead_realized != 400  # the client's number was ignored

    with session_factory() as s:
        copy = s.execute(
            select(Trade).where(Trade.copied_from_trade_id == lead_id)
        ).scalars().one()
        assert copy.status == "closed"
        assert copy.close_reason == "copy"
        # Follower holds 1 of the lead's 2 contracts → half the recomputed P&L.
        assert copy.realized_pnl == round(lead_realized * 0.5, 2)


def test_full_close_cancels_working_follower_without_booking_pnl(
    auth_client, session_factory
):
    """recent-waves #8: a follower whose OWN order never filled (still
    'working' — followers fill independently through the monitor) must be
    CANCELLED when the lead full-closes, NOT flipped to 'closed' with
    fabricated realized P&L on an order that never executed (which would
    corrupt the follower combine's balance / payout eligibility)."""
    lead = make_combine(auth_client, "50K", name="Lead")
    f2 = make_combine(auth_client, "50K", name="F2")
    _set_config(auth_client, lead["id"], [(f2["id"], 1.0)])

    with session_factory() as s:
        lead_c = s.get(Combine, lead["id"])
        trade = _lead_trade(s, lead_c, contracts=2)  # open lead
        mirror_open(s, lead_c, trade)
        lead_id = trade.id
        # Force the follower copy to WORKING (its own limit hasn't filled yet).
        copy = s.execute(
            select(Trade).where(Trade.copied_from_trade_id == lead_id)
        ).scalars().one()
        copy.status = "working"
        copy.realized_pnl = None
        s.add(copy)
        s.commit()
        # Full-close the lead and cascade.
        trade.status = "closed"
        trade.realized_pnl = 500.0
        trade.exit_date = datetime.now(timezone.utc)
        s.add(trade)
        s.commit()
        mirror_close(s, trade, final_slice_pnl=500.0)

    with session_factory() as s:
        copy = s.execute(
            select(Trade).where(Trade.copied_from_trade_id == lead_id)
        ).scalars().one()
        assert copy.status == "cancelled"       # cancelled, not closed
        assert copy.realized_pnl is None        # NO fabricated P&L


def test_lead_cancel_cascades_to_followers(auth_client, session_factory):
    lead = make_combine(auth_client, "50K", name="Lead")
    f2 = make_combine(auth_client, "50K", name="F2")
    _set_config(auth_client, lead["id"], [(f2["id"], 1.0)])

    with session_factory() as s:
        lead_c = s.get(Combine, lead["id"])
        trade = _lead_trade(s, lead_c, contracts=2, status="working")
        mirror_open(s, lead_c, trade)
        lead_id = trade.id
        # The mirrored copy is a working order too.
        copy = s.execute(
            select(Trade).where(Trade.copied_from_trade_id == lead_id)
        ).scalars().one()
        assert copy.status == "working"

    # Cancel the lead working order → cascade.
    res = auth_client.post(f"/api/journal/trades/{lead_id}/cancel")
    assert res.status_code == 200, res.text

    with session_factory() as s:
        copy = s.execute(
            select(Trade).where(Trade.copied_from_trade_id == lead_id)
        ).scalars().one()
        assert copy.status == "cancelled"


# --- custom multiplier clamp ----------------------------------------------


def test_custom_multiplier_clamps_to_cap(auth_client, session_factory):
    """An arbitrary >1 multiplier scales then clamps to the follower's cap."""
    lead = make_combine(auth_client, "50K", name="Lead")
    f2 = make_combine(auth_client, "50K", name="Big")
    # 3.5× is a non-preset value the new numeric input allows.
    res = _set_config(auth_client, lead["id"], [(f2["id"], 3.5)])
    assert res.status_code == 200, res.text
    assert {c["id"]: c["copy_multiplier"] for c in res.json()["combines"]}[f2["id"]] == 3.5

    with session_factory() as s:
        lead_c = s.get(Combine, lead["id"])
        trade = _lead_trade(s, lead_c, contracts=3)  # 3 × 3.5 = 10.5 → 11, capped at 5
        mirror_open(s, lead_c, trade)
        copy = s.execute(
            select(Trade).where(Trade.combine_id == f2["id"])
        ).scalars().one()
        assert copy.legs[0]["contracts"] == 5  # clamped to the 50K cap


# --- per-follower SL/TP override ------------------------------------------


def test_follower_sltp_override_and_fallback(auth_client, session_factory):
    """A follower with its own SL/TP uses them; one without inherits the lead's."""
    lead = make_combine(auth_client, "50K", name="Lead")
    over = make_combine(auth_client, "50K", name="Override")
    inherit = make_combine(auth_client, "50K", name="Inherit")
    # `over` sets its own brackets; `inherit` leaves them null.
    res = auth_client.put(
        "/api/combines/copy-config",
        json={
            "lead_combine_id": lead["id"],
            "followers": [
                {"combine_id": over["id"], "multiplier": 1.0,
                 "stop_loss": 490.0, "take_profit": 520.0},
                {"combine_id": inherit["id"], "multiplier": 1.0},
            ],
        },
    )
    assert res.status_code == 200, res.text
    by_id = {c["id"]: c for c in res.json()["combines"]}
    assert by_id[over["id"]]["copy_stop_loss"] == 490.0
    assert by_id[over["id"]]["copy_take_profit"] == 520.0
    assert by_id[inherit["id"]]["copy_stop_loss"] is None

    with session_factory() as s:
        lead_c = s.get(Combine, lead["id"])
        trade = _lead_trade(s, lead_c, contracts=2, stop_loss=495.0, take_profit=510.0)
        mirror_open(s, lead_c, trade)

        over_t = s.execute(
            select(Trade).where(Trade.combine_id == over["id"])
        ).scalars().one()
        inherit_t = s.execute(
            select(Trade).where(Trade.combine_id == inherit["id"])
        ).scalars().one()
        # Override follower uses its own levels.
        assert over_t.stop_loss == 490.0
        assert over_t.take_profit == 520.0
        # Inherit follower falls back to the lead's levels.
        assert inherit_t.stop_loss == 495.0
        assert inherit_t.take_profit == 510.0


def test_clearing_follow_clears_sltp_override(auth_client, session_factory):
    """Un-following a combine wipes its stale SL/TP overrides."""
    lead = make_combine(auth_client, "50K", name="Lead")
    f2 = make_combine(auth_client, "50K", name="F2")
    auth_client.put(
        "/api/combines/copy-config",
        json={
            "lead_combine_id": lead["id"],
            "followers": [{"combine_id": f2["id"], "multiplier": 1.0,
                           "stop_loss": 490.0, "take_profit": 520.0}],
        },
    )
    # Drop f2 from the follower set.
    body = _set_config(auth_client, lead["id"], []).json()
    by_id = {c["id"]: c for c in body["combines"]}
    assert by_id[f2["id"]]["copy_follow"] is False
    assert by_id[f2["id"]]["copy_stop_loss"] is None
    assert by_id[f2["id"]]["copy_take_profit"] is None


# --- trailing-stop independence -------------------------------------------


def test_mirror_resets_trail_hwm_keeps_config(auth_client, session_factory):
    """The mirror copies trail_amount but seeds its OWN high-water (None)."""
    lead = make_combine(auth_client, "50K", name="Lead")
    f2 = make_combine(auth_client, "50K", name="F2")
    _set_config(auth_client, lead["id"], [(f2["id"], 1.0)])

    with session_factory() as s:
        lead_c = s.get(Combine, lead["id"])
        # Lead is already trailing off a high-water of 3.50.
        trade = _lead_trade(s, lead_c, contracts=2, trail_amount=0.25, trail_hwm=3.50)
        mirror_open(s, lead_c, trade)
        copy = s.execute(
            select(Trade).where(Trade.combine_id == f2["id"])
        ).scalars().one()
        assert copy.trail_amount == 0.25  # config copied
        assert copy.trail_hwm is None     # but NOT the lead's high-water


# --- proportional partial cascade (WS-A seam) -----------------------------


def test_partial_cascade_closes_followers_proportionally(auth_client, session_factory):
    """Lead closes 4 of 8 → a 0.5× follower (4 contracts) closes 2, stays open."""
    lead = make_combine(auth_client, "50K", name="Lead")
    f2 = make_combine(auth_client, "100K", name="Half")  # 100K cap=10, fits 4
    _set_config(auth_client, lead["id"], [(f2["id"], 0.5)])

    with session_factory() as s:
        lead_c = s.get(Combine, lead["id"])
        trade = _lead_trade(s, lead_c, contracts=8)  # follower → 4 (×0.5)
        mirror_open(s, lead_c, trade)
        lead_id = trade.id

        copy = s.execute(
            select(Trade).where(Trade.copied_from_trade_id == lead_id)
        ).scalars().one()
        assert copy.legs[0]["contracts"] == 4

        # Simulate WS-A's lead-side partial close: reduce lead legs by 4,
        # accumulate realized on the closed slice, then cascade.
        legs = trade.legs
        legs[0]["contracts"] = 8 - 4
        trade.legs = legs
        trade.realized_pnl = 400.0  # booked on the 4-contract lead slice
        trade.exit_underlying_price = 505.0
        s.add(trade)
        s.commit()

        n = mirror_close(s, trade, closed_qty=4)
        assert n == 1

        copy = s.execute(
            select(Trade).where(Trade.copied_from_trade_id == lead_id)
        ).scalars().one()
        # Closed 2 of 4 → stays OPEN with 2 left.
        assert copy.status == "open"
        assert copy.legs[0]["contracts"] == 2
        # Realized accrues on the booked slice: 400 × (2 closed / 4 lead) = 200.
        assert copy.realized_pnl == 200.0


def test_partial_cascade_books_per_slice_not_accumulated_total(auth_client, session_factory):
    """Two sequential scale-outs book EACH slice's P&L proportionally to the
    follower — not the lead's running accumulated realized total. Regression: the
    cascade read lead_trade.realized_pnl (accumulated), so the 2nd scale-out
    re-booked the lead's whole history onto the follower (over-inflating P&L)."""
    lead = make_combine(auth_client, "50K", name="Lead")
    f1 = make_combine(auth_client, "100K", name="Mirror")  # 1.0× → matches lead size
    _set_config(auth_client, lead["id"], [(f1["id"], 1.0)])

    with session_factory() as s:
        lead_c = s.get(Combine, lead["id"])
        trade = _lead_trade(s, lead_c, contracts=4)  # follower → 4 (×1.0)
        mirror_open(s, lead_c, trade)
        lead_id = trade.id

        # Scale-out #1: close 1 of 4, slice +100. Lead realized total → 100.
        legs = trade.legs
        legs[0]["contracts"] = 3
        trade.legs = legs
        trade.realized_pnl = 100.0
        s.add(trade)
        s.commit()
        mirror_close(s, trade, closed_qty=1, slice_pnl=100.0)
        copy = s.execute(
            select(Trade).where(Trade.copied_from_trade_id == lead_id)
        ).scalars().one()
        assert copy.legs[0]["contracts"] == 3
        assert copy.realized_pnl == 100.0  # 100 × (1/1)

        # Scale-out #2: close 1 more, slice +120. Lead realized ACCUMULATES → 220.
        legs = trade.legs
        legs[0]["contracts"] = 2
        trade.legs = legs
        trade.realized_pnl = 220.0  # running total, NOT this slice
        s.add(trade)
        s.commit()
        mirror_close(s, trade, closed_qty=1, slice_pnl=120.0)
        copy = s.execute(
            select(Trade).where(Trade.copied_from_trade_id == lead_id)
        ).scalars().one()
        assert copy.legs[0]["contracts"] == 2
        # Per-slice: 100 + 120 = 220 (NOT 100 + 220 = 320 from the accumulated total).
        assert copy.realized_pnl == 220.0


def test_partial_cascade_full_unwind_closes_follower(auth_client, session_factory):
    """Cascading partials that exhaust the follower's contracts close it."""
    lead = make_combine(auth_client, "50K", name="Lead")
    f2 = make_combine(auth_client, "50K", name="F2")
    _set_config(auth_client, lead["id"], [(f2["id"], 1.0)])

    with session_factory() as s:
        lead_c = s.get(Combine, lead["id"])
        trade = _lead_trade(s, lead_c, contracts=2)  # follower → 2
        mirror_open(s, lead_c, trade)
        lead_id = trade.id

        # Close the entire lead position in one partial (closed_qty == size).
        legs = trade.legs
        legs[0]["contracts"] = 0
        trade.legs = legs
        trade.realized_pnl = 300.0
        trade.exit_underlying_price = 506.0
        s.add(trade)
        s.commit()

        mirror_close(s, trade, closed_qty=2)

        copy = s.execute(
            select(Trade).where(Trade.copied_from_trade_id == lead_id)
        ).scalars().one()
        assert copy.status == "closed"
        assert copy.legs[0]["contracts"] == 0
        assert copy.close_reason == "copy"
        assert copy.realized_pnl == 300.0
