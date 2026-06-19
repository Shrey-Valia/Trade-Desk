"""Copy trading — config endpoint + the lead→followers mirror service."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select

from models.combine import Combine
from models.trade import Trade
from services.copy_trade import mirror_open
from tests.conftest import make_combine


def _lead_trade(session, combine: Combine, contracts: int = 5) -> Trade:
    t = Trade(
        symbol="SPY",
        strategy="long_call",
        entry_date=datetime.now(timezone.utc),
        entry_underlying_price=500.0,
        net_debit_credit=-1000.0,
        status="open",
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


# --- config endpoint ------------------------------------------------------


def test_copy_config_sets_lead_and_followers(auth_client):
    lead = make_combine(auth_client, "50K", name="Lead")
    f2 = make_combine(auth_client, "50K", name="F2")
    f3 = make_combine(auth_client, "50K", name="F3")

    res = auth_client.put(
        "/api/combines/copy-config",
        json={"lead_combine_id": lead["id"], "follower_ids": [f2["id"], f3["id"]]},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["copy_lead_combine_id"] == lead["id"]
    follows = {c["id"]: c["copy_follow"] for c in body["combines"]}
    assert follows[lead["id"]] is False  # the lead can't follow itself
    assert follows[f2["id"]] is True
    assert follows[f3["id"]] is True


def test_copy_config_rejects_foreign_combine(auth_client, second_user_client):
    mine = make_combine(auth_client, "50K")
    theirs = make_combine(second_user_client, "50K")
    res = auth_client.put(
        "/api/combines/copy-config",
        json={"lead_combine_id": mine["id"], "follower_ids": [theirs["id"]]},
    )
    assert res.status_code == 404


def test_copy_config_off_clears_followers(auth_client):
    lead = make_combine(auth_client, "50K")
    f2 = make_combine(auth_client, "50K")
    auth_client.put(
        "/api/combines/copy-config",
        json={"lead_combine_id": lead["id"], "follower_ids": [f2["id"]]},
    )
    body = auth_client.put(
        "/api/combines/copy-config", json={"lead_combine_id": None, "follower_ids": []}
    ).json()
    assert body["copy_lead_combine_id"] is None
    assert all(c["copy_follow"] is False for c in body["combines"])


# --- mirror service -------------------------------------------------------


def test_mirror_clamps_to_follower_cap_and_tags(auth_client, session_factory):
    lead = make_combine(auth_client, "50K", name="Lead")
    f2 = make_combine(auth_client, "50K", name="F2")
    f3 = make_combine(auth_client, "50K", name="F3")
    auth_client.put(
        "/api/combines/copy-config",
        json={"lead_combine_id": lead["id"], "follower_ids": [f2["id"], f3["id"]]},
    )

    with session_factory() as s:
        lead_c = s.get(Combine, lead["id"])
        trade = _lead_trade(s, lead_c, contracts=5)
        result = mirror_open(s, lead_c, trade)

        assert sorted(result.mirrored) == sorted([f2["id"], f3["id"]])
        for fid in (f2["id"], f3["id"]):
            mt = s.execute(
                select(Trade).where(Trade.combine_id == fid)
            ).scalars().all()
            assert len(mt) == 1
            # 50K scaling cap starts at 2 → clamped from 5.
            assert mt[0].legs[0]["contracts"] == 2
            assert "copy" in mt[0].tags
            assert "copied from Lead" in (mt[0].notes or "")


def test_mirror_skips_ineligible_follower(auth_client, session_factory):
    lead = make_combine(auth_client, "50K", name="Lead")
    f2 = make_combine(auth_client, "50K", name="F2")
    f3 = make_combine(auth_client, "50K", name="F3")
    auth_client.put(
        "/api/combines/copy-config",
        json={"lead_combine_id": lead["id"], "follower_ids": [f2["id"], f3["id"]]},
    )

    with session_factory() as s:
        # F3 has a failed eval → ineligible.
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
    # b follows, but no lead is configured → opening on `a` mirrors nothing.
    with session_factory() as s:
        a_c = s.get(Combine, a["id"])
        trade = _lead_trade(s, a_c)
        result = mirror_open(s, a_c, trade)
        assert result.mirrored == []
        assert s.execute(
            select(Trade).where(Trade.combine_id == b["id"])
        ).scalars().all() == []
