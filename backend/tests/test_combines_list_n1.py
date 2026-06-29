"""N+1 fix in the combines list (WS7).

`list_combines` used to call `_payouts_requested` once per combine (inside
`_to_out`), so listing N combines fired N separate "sum the payout events"
queries on top of the per-combine snapshot work — classic N+1. The fix batches
those sums into ONE grouped query (`_payouts_requested_by_combine`) and threads
the precomputed value into `_to_out`.

These tests prove two things:
  1. The response is IDENTICAL — payout_requested / payout_eligible match what
     the per-combine path computes, across multiple combines with multiple
     payout events each.
  2. The batched query actually replaces the per-combine sums: we count the
     payout-sum statements issued for a list call and assert there's at most one
     (grouped), not one-per-combine.
"""

from __future__ import annotations

from datetime import UTC, datetime, time
from zoneinfo import ZoneInfo

from sqlalchemy import event, select

import routers.combines as combines_router
from database import get_session
from models.combine import Combine
from models.combine_event import CombineEvent
from models.trade import Trade
from tests.conftest import make_combine

_PT = ZoneInfo("America/Los_Angeles")


def _noon_pt_on(day_offset: int) -> datetime:
    from datetime import timedelta

    d = (datetime.now(_PT) - timedelta(days=day_offset)).date()
    return datetime.combine(d, time(12, 0), tzinfo=_PT).astimezone(UTC)


def _seed_closed(session, combine_id: int, realized: float, exit_at: datetime) -> None:
    session.add(
        Trade(
            symbol="SPY",
            strategy="long_straddle",
            entry_date=exit_at,
            entry_underlying_price=400.0,
            net_debit_credit=0.0,
            status="closed",
            is_paper=True,
            notes="seed",
            tier="50K",
            combine_id=combine_id,
            exit_date=exit_at,
            exit_underlying_price=400.0,
            realized_pnl=realized,
            legs_json="[]",
        )
    )


def _fund_and_activate(client, combine_id: int, total_profit: float) -> None:
    """FUND + ACTIVATE a combine with a known realized profit across two
    distinct trading days (min-days + consistency), stamping the lifecycle
    timestamps so the snapshot reports it payable."""
    session = next(client.app.dependency_overrides[get_session]())
    half = round(total_profit / 2, 2)
    _seed_closed(session, combine_id, half, _noon_pt_on(2))
    _seed_closed(session, combine_id, round(total_profit - half, 2), _noon_pt_on(1))
    combine = session.get(Combine, combine_id)
    now = datetime.now(UTC)
    combine.funded_at = now
    combine.funded_activated_at = now
    session.add(combine)
    session.commit()
    session.close()


def _seed_payout_event(client, combine_id: int, user_id: int, amount: float) -> None:
    """Write a raw payout event (bypasses the endpoint's idempotency window so a
    test can stack several requested-payout rows on one combine)."""
    session = next(client.app.dependency_overrides[get_session]())
    session.add(
        CombineEvent(
            user_id=user_id,
            combine_id=combine_id,
            type="payout",
            message="seed payout",
            amount=amount,
        )
    )
    session.commit()
    session.close()


def _user_id(client) -> int:
    from models.user import User

    session = next(client.app.dependency_overrides[get_session]())
    uid = session.execute(select(User.id)).scalars().first()
    session.close()
    return uid


def test_list_reports_correct_netted_payouts_across_combines(auth_client):
    """Two funded combines, each with prior payout events of different sizes.
    The list must net each combine's requested payouts off its own eligible
    split — proving the batched sums map back to the right combine."""
    uid = _user_id(auth_client)

    a = make_combine(auth_client, "50K", name="A")
    b = make_combine(auth_client, "50K", name="B")

    # A: $3,000 realized → $2,400 eligible (80/20). Prior payouts total $1,000.
    _fund_and_activate(auth_client, a["id"], 3_000.0)
    _seed_payout_event(auth_client, a["id"], uid, 600.0)
    _seed_payout_event(auth_client, a["id"], uid, 400.0)

    # B: $5,000 realized → $4,000 eligible. Prior payouts total $250.
    _fund_and_activate(auth_client, b["id"], 5_000.0)
    _seed_payout_event(auth_client, b["id"], uid, 250.0)

    listing = auth_client.get("/api/combines").json()
    by_name = {c["name"]: c for c in listing["combines"]}

    assert by_name["A"]["payout_requested"] == 1_000.0
    assert by_name["A"]["payout_eligible"] == 1_400.0  # 2,400 − 1,000
    assert by_name["B"]["payout_requested"] == 250.0
    assert by_name["B"]["payout_eligible"] == 3_750.0  # 4,000 − 250


def test_list_matches_per_combine_to_out(auth_client):
    """The batched list path must produce byte-identical CombineOut rows to the
    single-combine `_to_out` path it replaced. We compare each row in the list
    response against `_to_out(session, combine)` computed in isolation."""
    uid = _user_id(auth_client)
    a = make_combine(auth_client, "50K", name="A")
    b = make_combine(auth_client, "50K", name="B")
    _fund_and_activate(auth_client, a["id"], 3_000.0)
    _seed_payout_event(auth_client, a["id"], uid, 500.0)
    _fund_and_activate(auth_client, b["id"], 1_000.0)

    listing = auth_client.get("/api/combines").json()
    by_id = {c["id"]: c for c in listing["combines"]}

    session = next(auth_client.app.dependency_overrides[get_session]())
    for cid in (a["id"], b["id"]):
        combine = session.get(Combine, cid)
        expected = combines_router._to_out(session, combine).model_dump(mode="json")
        # created_at serialization can differ by trailing precision between the
        # two paths; compare the load-bearing money/identity fields explicitly.
        got = by_id[cid]
        for field in (
            "id", "name", "payout_requested", "payout_eligible",
            "realized_pnl", "balance", "funded", "funded_activated",
        ):
            assert got[field] == expected[field], (field, cid)
    session.close()


def test_list_payout_sums_are_one_grouped_query(auth_client):
    """The whole point: listing N combines fires AT MOST ONE payout-sum query,
    not one per combine. We hook SQLAlchemy's cursor-execute event, count
    statements that sum CombineEvent.amount for type='payout', and assert it's
    grouped (≤1) even with several combines."""
    uid = _user_id(auth_client)
    ids = []
    for i in range(4):
        c = make_combine(auth_client, "50K", name=f"C{i}")
        _fund_and_activate(auth_client, c["id"], 2_000.0)
        _seed_payout_event(auth_client, c["id"], uid, 100.0)
        ids.append(c["id"])

    from database import engine as _default_engine  # noqa: F401

    # The TestClient runs against the conftest db_engine via the override; grab
    # it off a live session so we instrument the SAME engine the request uses.
    session = next(auth_client.app.dependency_overrides[get_session]())
    bind = session.get_bind()
    session.close()

    payout_sum_stmts: list[str] = []

    def _before_exec(conn, cursor, statement, parameters, context, executemany):
        s = statement.lower()
        if "sum(" in s and "combine_events" in s and "payout" in str(parameters).lower():
            payout_sum_stmts.append(statement)
        elif "sum(" in s and "combine_events" in s and "amount" in s:
            # Grouped form binds 'payout' as a parameter, not inline — catch it
            # by the grouping shape too.
            payout_sum_stmts.append(statement)

    event.listen(bind, "before_cursor_execute", _before_exec)
    try:
        res = auth_client.get("/api/combines")
        assert res.status_code == 200
        assert len(res.json()["combines"]) == 4
    finally:
        event.remove(bind, "before_cursor_execute", _before_exec)

    # Pre-fix this would have been 4 (one sum per combine). Batched → exactly 1:
    # one grouped query ran (so the count is non-zero — the matcher isn't a
    # no-op) and it ran only once.
    assert len(payout_sum_stmts) == 1, payout_sum_stmts
    assert "group by" in payout_sum_stmts[0].lower()
