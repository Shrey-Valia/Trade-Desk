"""Copy trading — config endpoint + the lead→followers mirror service
(opens with multiplier + clamp, and close cascade)."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select

from models.combine import Combine
from models.trade import Trade
from services.copy_trade import mirror_open
from tests.conftest import make_combine


def _lead_trade(
    session, combine: Combine, contracts: int = 5, status: str = "open"
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


def test_lead_close_cascades_to_followers_scaled(auth_client, session_factory):
    lead = make_combine(auth_client, "50K", name="Lead")
    f2 = make_combine(auth_client, "50K", name="Half")
    _set_config(auth_client, lead["id"], [(f2["id"], 0.5)])

    with session_factory() as s:
        lead_c = s.get(Combine, lead["id"])
        trade = _lead_trade(s, lead_c, contracts=2)  # follower → 1 contract (×0.5)
        mirror_open(s, lead_c, trade)
        lead_id = trade.id

    # Close the lead through the real journal endpoint → cascade.
    res = auth_client.patch(
        f"/api/journal/trades/{lead_id}",
        json={"status": "closed", "realized_pnl": 400, "exit_underlying_price": 505.0},
    )
    assert res.status_code == 200, res.text

    with session_factory() as s:
        copy = s.execute(
            select(Trade).where(Trade.copied_from_trade_id == lead_id)
        ).scalars().one()
        assert copy.status == "closed"
        assert copy.close_reason == "copy"
        assert copy.realized_pnl == 200.0  # 400 × (1/2) contract ratio


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
