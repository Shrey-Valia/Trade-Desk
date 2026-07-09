"""Billing periods — "Billed monthly, cancel anytime", made true in the
simulation.

provision_combine seeds paid_through = purchase + 30 days; the daily
renew_combines job runs each boundary: auto-renew (one simulated Payment at
the monthly price per 30-day period, one banked reset credit per period,
capped) or archive when cancel_at_period_end is set. reset_combine spends a
banked credit before charging the fee, and /api/payments/history exposes
the ledger. Migration coverage: legacy rows get paid_through backfilled and
users get reset_credits = 0.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.pool import StaticPool

from database import get_session
from jobs.renew_combines import renew_combines
from models.combine import Combine
from models.combine_event import CombineEvent
from models.payment import Payment
from models.trade import Trade
from models.user import User
from tests.conftest import make_combine


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _user(session_factory, email="trader@test.local") -> User:
    with session_factory() as s:
        return s.execute(select(User).where(User.email == email)).scalar_one()


def _set_paid_through(session_factory, combine_id: int, when: datetime) -> None:
    with session_factory() as s:
        c = s.get(Combine, combine_id)
        c.paid_through = when
        s.add(c)
        s.commit()


def _set_credits(session_factory, n: int, email="trader@test.local") -> None:
    with session_factory() as s:
        u = s.execute(select(User).where(User.email == email)).scalar_one()
        u.reset_credits = n
        s.add(u)
        s.commit()


def _paid_payments(session_factory, combine_id: int) -> list[Payment]:
    with session_factory() as s:
        return (
            s.execute(
                select(Payment).where(
                    Payment.combine_id == combine_id, Payment.status == "paid"
                )
            )
            .scalars()
            .all()
        )


def _events(client, type_: str) -> list[dict]:
    return [e for e in client.get("/api/combines/events").json() if e["type"] == type_]


def _card(client, combine_id: int) -> dict:
    return next(
        c for c in client.get("/api/combines").json()["combines"] if c["id"] == combine_id
    )


def _fail_combine(client, session_factory, combine_id: int) -> None:
    """Drive the ACTIVE combine to a FAILED outcome (-2,500 ≤ the 48,000
    floor on 50K), persisting it via a state read."""
    with session_factory() as s:
        s.add(
            Trade(
                symbol="SPY",
                strategy="long_straddle",
                entry_date=_now(),
                entry_underlying_price=400.0,
                net_debit_credit=0.0,
                status="closed",
                is_paper=True,
                notes="seed",
                tier="50K",
                combine_id=combine_id,
                exit_date=_now(),
                exit_underlying_price=400.0,
                realized_pnl=-2_500.0,
                legs_json="[]",
            )
        )
        s.commit()
    assert client.get("/api/account/state").json()["status"] == "failed"


# ---------------------------------------------------------------------------
# Billing period seeding
# ---------------------------------------------------------------------------


def test_purchase_seeds_paid_through_30_days_out(auth_client):
    c = make_combine(auth_client, "50K")
    assert c["cancel_at_period_end"] is False
    paid_through = datetime.fromisoformat(c["paid_through"])
    delta = paid_through - _now()
    assert timedelta(days=29) < delta < timedelta(days=31)


def test_list_exposes_reset_credits_top_level(auth_client):
    make_combine(auth_client, "50K")
    listing = auth_client.get("/api/combines").json()
    assert listing["reset_credits"] == 0


# ---------------------------------------------------------------------------
# Renewal job — extend + bill + bank a credit
# ---------------------------------------------------------------------------


def test_renewal_extends_period_bills_and_banks_credit(
    auth_client, session_factory
):
    c = make_combine(auth_client, "50K")
    old = _now() - timedelta(days=1)
    _set_paid_through(session_factory, c["id"], old)

    summary = renew_combines(session_factory=session_factory)
    assert summary["renewed"] == 1
    assert summary["periods"] == 1

    with session_factory() as s:
        combine = s.get(Combine, c["id"])
        # Extended FROM the old boundary, not from `now`.
        assert combine.paid_through == old + timedelta(days=30)
        assert combine.status == "active"
    # The rebill mirrors the purchase ledger row: status 'paid' at the
    # combine's monthly price (50K, activation path, 80/20 → $69).
    paid = _paid_payments(session_factory, c["id"])
    assert len(paid) == 2  # purchase + renewal
    assert all(p.amount == 69.0 for p in paid)
    assert _user(session_factory).reset_credits == 1
    renewal_events = _events(auth_client, "renewal")
    assert len(renewal_events) == 1
    assert renewal_events[0]["amount"] == 69.0
    assert "reset credit" in renewal_events[0]["message"].lower()


def test_renewal_multi_period_gap_bills_each_period(auth_client, session_factory):
    c = make_combine(auth_client, "50K")
    old = _now() - timedelta(days=65)
    _set_paid_through(session_factory, c["id"], old)

    summary = renew_combines(session_factory=session_factory)
    assert summary["periods"] == 3  # 65 days late → 3 completed periods

    with session_factory() as s:
        combine = s.get(Combine, c["id"])
        assert combine.paid_through == old + timedelta(days=90)
        assert combine.paid_through > _now()
    assert len(_paid_payments(session_factory, c["id"])) == 4  # purchase + 3
    assert _user(session_factory).reset_credits == 3
    assert len(_events(auth_client, "renewal")) == 3


def test_renewal_caps_banked_credits_at_12(auth_client, session_factory):
    c = make_combine(auth_client, "50K")
    _set_credits(session_factory, 12)
    _set_paid_through(session_factory, c["id"], _now() - timedelta(days=1))

    renew_combines(session_factory=session_factory)

    assert _user(session_factory).reset_credits == 12  # capped, not 13
    # The rebill itself still books.
    assert len(_paid_payments(session_factory, c["id"])) == 2
    assert "reset credit" not in _events(auth_client, "renewal")[0]["message"].lower()


def test_renewal_is_idempotent_per_boundary(auth_client, session_factory):
    c = make_combine(auth_client, "50K")
    _set_paid_through(session_factory, c["id"], _now() - timedelta(days=1))

    renew_combines(session_factory=session_factory)
    second = renew_combines(session_factory=session_factory)

    assert second["renewed"] == 0
    assert len(_paid_payments(session_factory, c["id"])) == 2  # not 3
    assert _user(session_factory).reset_credits == 1


def test_renewal_skips_future_boundaries(auth_client, session_factory):
    c = make_combine(auth_client, "50K")  # paid_through ~30 days out
    summary = renew_combines(session_factory=session_factory)
    assert summary["renewed"] == 0
    assert summary["archived"] == 0
    assert len(_paid_payments(session_factory, c["id"])) == 1  # purchase only


def test_renewal_lazily_seeds_null_paid_through(auth_client, session_factory):
    c = make_combine(auth_client, "50K")
    with session_factory() as s:
        combine = s.get(Combine, c["id"])
        combine.paid_through = None  # simulate a legacy row
        s.add(combine)
        s.commit()

    summary = renew_combines(session_factory=session_factory)
    assert summary["seeded"] == 1
    with session_factory() as s:
        assert s.get(Combine, c["id"]).paid_through > _now()
    assert len(_paid_payments(session_factory, c["id"])) == 1  # nothing billed


# ---------------------------------------------------------------------------
# Cancel at period end — archive at the boundary
# ---------------------------------------------------------------------------


def test_canceled_combine_archives_at_boundary(auth_client, session_factory):
    keeper = make_combine(auth_client, "50K", name="Keeper")
    c = make_combine(auth_client, "100K", name="Goner")
    # The newest purchase is NOT auto-activated; point the user at it so the
    # archive has an active selection to repoint.
    assert auth_client.post(f"/api/combines/{c['id']}/activate").status_code == 200

    assert auth_client.post(f"/api/combines/{c['id']}/cancel").status_code == 200
    _set_paid_through(session_factory, c["id"], _now() - timedelta(days=1))

    summary = renew_combines(session_factory=session_factory)
    assert summary["archived"] == 1
    assert summary["renewed"] == 0

    with session_factory() as s:
        combine = s.get(Combine, c["id"])
        assert combine.status == "archived"
        # Mirrors the archive endpoint: selection repoints to the survivor.
        assert _user(session_factory).active_combine_id == keeper["id"]
    # No rebill on the way out.
    assert len(_paid_payments(session_factory, c["id"])) == 1
    ended = _events(auth_client, "sub_ended")
    assert len(ended) == 1
    assert ended[0]["message"] == "Subscription ended — combine archived."


def test_period_end_archive_cancels_resting_working_orders(auth_client, session_factory):
    """recent-waves #10: the AUTOMATIC period-end archive must cancel resting
    (unfilled) orders so a dead combine leaves no GTC zombie working orders."""
    from datetime import datetime, timezone
    from models.trade import Trade

    c = make_combine(auth_client, "50K", name="Goner")
    with session_factory() as s:
        t = Trade(
            symbol="SPY", strategy="long_call",
            entry_date=datetime.now(timezone.utc), entry_underlying_price=100.0,
            net_debit_credit=0.0, status="working", order_type="limit",
            limit_price=1.0, is_paper=True, tier="50K",
            combine_id=c["id"], legs_json="[]", origin="execution",
        )
        s.add(t)
        s.commit()
        tid = t.id
    assert auth_client.post(f"/api/combines/{c['id']}/cancel").status_code == 200
    _set_paid_through(session_factory, c["id"], _now() - timedelta(days=1))

    summary = renew_combines(session_factory=session_factory)
    assert summary["archived"] == 1
    with session_factory() as s:
        assert s.get(Combine, c["id"]).status == "archived"
        assert s.get(Trade, tid).status == "cancelled"   # zombie order pulled


def test_resume_before_boundary_renews_instead_of_archiving(
    auth_client, session_factory
):
    c = make_combine(auth_client, "50K")
    assert auth_client.post(f"/api/combines/{c['id']}/cancel").status_code == 200
    assert auth_client.post(f"/api/combines/{c['id']}/resume").status_code == 200
    _set_paid_through(session_factory, c["id"], _now() - timedelta(days=1))

    summary = renew_combines(session_factory=session_factory)
    assert summary["archived"] == 0
    assert summary["renewed"] == 1
    with session_factory() as s:
        assert s.get(Combine, c["id"]).status == "active"


# ---------------------------------------------------------------------------
# Cancel / resume endpoints
# ---------------------------------------------------------------------------


def test_cancel_sets_flag_and_records_event(auth_client):
    c = make_combine(auth_client, "50K")
    res = auth_client.post(f"/api/combines/{c['id']}/cancel")
    assert res.status_code == 200, res.text
    assert res.json()["cancel_at_period_end"] is True
    # Idempotent: a second cancel changes nothing and records nothing new.
    again = auth_client.post(f"/api/combines/{c['id']}/cancel")
    assert again.status_code == 200
    assert len(_events(auth_client, "sub_cancel")) == 1


def test_cancel_allowed_on_failed_combine(auth_client, session_factory):
    c = make_combine(auth_client, "50K")
    _fail_combine(auth_client, session_factory, c["id"])
    res = auth_client.post(f"/api/combines/{c['id']}/cancel")
    assert res.status_code == 200, res.text
    assert res.json()["cancel_at_period_end"] is True


def test_cancel_409_on_archived(auth_client):
    c = make_combine(auth_client, "50K")
    auth_client.post(f"/api/combines/{c['id']}/archive")
    assert auth_client.post(f"/api/combines/{c['id']}/cancel").status_code == 409


def test_resume_clears_flag_and_records_event(auth_client):
    c = make_combine(auth_client, "50K")
    auth_client.post(f"/api/combines/{c['id']}/cancel")
    res = auth_client.post(f"/api/combines/{c['id']}/resume")
    assert res.status_code == 200, res.text
    assert res.json()["cancel_at_period_end"] is False
    assert len(_events(auth_client, "sub_resume")) == 1
    # Resuming an un-canceled combine is a no-op.
    auth_client.post(f"/api/combines/{c['id']}/resume")
    assert len(_events(auth_client, "sub_resume")) == 1


def test_resume_409_once_archived(auth_client):
    c = make_combine(auth_client, "50K")
    auth_client.post(f"/api/combines/{c['id']}/archive")
    res = auth_client.post(f"/api/combines/{c['id']}/resume")
    assert res.status_code == 409
    assert "archived" in res.json()["detail"]


# ---------------------------------------------------------------------------
# Reset credits — consumed before the fee
# ---------------------------------------------------------------------------


def test_reset_consumes_banked_credit_before_fee(auth_client, session_factory):
    c = make_combine(auth_client, "50K")
    _fail_combine(auth_client, session_factory, c["id"])
    _set_credits(session_factory, 2)

    res = auth_client.post(f"/api/combines/{c['id']}/reset")
    assert res.status_code == 200, res.text
    assert res.json()["outcome"] == "active"

    with session_factory() as s:
        pay = s.execute(
            select(Payment).where(Payment.status == "reset_credit")
        ).scalars().one()
        assert pay.amount == 0.0
        assert pay.combine_id == c["id"]
        # No fee was charged.
        assert s.execute(
            select(Payment).where(Payment.status == "reset_paid")
        ).scalars().first() is None
    assert _user(session_factory).reset_credits == 1
    assert auth_client.get("/api/combines").json()["reset_credits"] == 1
    reset_events = _events(auth_client, "reset")
    assert reset_events[0]["amount"] == 0.0
    assert (
        reset_events[0]["message"]
        == "Evaluation reset — free reset credit used (1 remaining)."
    )


def test_reset_books_fee_when_no_credits(auth_client, session_factory):
    c = make_combine(auth_client, "50K")
    _fail_combine(auth_client, session_factory, c["id"])

    res = auth_client.post(f"/api/combines/{c['id']}/reset")
    assert res.status_code == 200, res.text
    with session_factory() as s:
        pay = s.execute(
            select(Payment).where(Payment.status == "reset_paid")
        ).scalars().one()
        assert pay.amount == 69.0  # 50K monthly, activation path, 80/20
    assert _events(auth_client, "reset")[0]["amount"] == 69.0


# ---------------------------------------------------------------------------
# Payments history — the billing ledger, scoped to the signed-in user
# ---------------------------------------------------------------------------


def test_history_returns_own_payments_newest_first(auth_client):
    make_combine(auth_client, "50K")
    make_combine(auth_client, "100K")
    res = auth_client.get("/api/payments/history")
    assert res.status_code == 200, res.text
    payments = res.json()["payments"]
    assert len(payments) == 2
    # Newest first (the 100K purchase came second).
    assert payments[0]["tier"] == "100K"
    assert payments[0]["amount"] == 119.0
    assert payments[1]["tier"] == "50K"
    assert payments[1]["amount"] == 69.0
    assert set(payments[0]) == {
        "id", "combine_id", "tier", "amount", "status", "created_at",
    }
    assert all(p["status"] == "paid" for p in payments)


def test_history_scoped_to_the_signed_in_user(auth_client, second_user_client):
    make_combine(auth_client, "50K")
    make_combine(second_user_client, "150K")
    mine = auth_client.get("/api/payments/history").json()["payments"]
    theirs = second_user_client.get("/api/payments/history").json()["payments"]
    assert [p["tier"] for p in mine] == ["50K"]
    assert [p["tier"] for p in theirs] == ["150K"]


def test_history_requires_auth(api_client):
    assert api_client.get("/api/payments/history").status_code == 401


def test_history_includes_renewals(auth_client, session_factory):
    c = make_combine(auth_client, "50K")
    _set_paid_through(session_factory, c["id"], _now() - timedelta(days=1))
    renew_combines(session_factory=session_factory)
    payments = auth_client.get("/api/payments/history").json()["payments"]
    assert len(payments) == 2
    assert all(p["amount"] == 69.0 and p["status"] == "paid" for p in payments)


# ---------------------------------------------------------------------------
# Additive migrations — legacy DBs pick up the billing columns
# ---------------------------------------------------------------------------


def _legacy_engine():
    return create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )


def test_migration_backfills_paid_through_for_non_archived(monkeypatch):
    import database as db

    engine = _legacy_engine()
    with engine.connect() as conn:
        conn.execute(
            text(
                "CREATE TABLE combines ("
                "id INTEGER PRIMARY KEY, user_id INTEGER, tier VARCHAR(8), "
                "name VARCHAR(64), account_code VARCHAR(32), hwm FLOAT, "
                "status VARCHAR(16), created_at DATETIME, updated_at DATETIME)"
            )
        )
        conn.execute(
            text(
                "INSERT INTO combines (id, user_id, tier, name, account_code, "
                "hwm, status) VALUES "
                "(1, 1, '50K', 'A', 'C1', 50000, 'active'), "
                "(2, 1, '50K', 'B', 'C2', 50000, 'archived')"
            )
        )
        conn.commit()

    monkeypatch.setattr(db, "engine", engine)
    db._additive_migrate_combines()
    db._additive_migrate_combines()  # idempotent re-run

    with engine.connect() as conn:
        rows = dict(
            conn.execute(text("SELECT id, paid_through FROM combines")).all()
        )
        flags = dict(
            conn.execute(text("SELECT id, cancel_at_period_end FROM combines")).all()
        )
    engine.dispose()
    assert rows[1] is not None  # active combine got a fresh period
    assert rows[2] is None  # archived rows stay unbilled
    assert flags == {1: 0, 2: 0}


def test_migration_adds_reset_credits_default_zero(monkeypatch):
    import database as db

    engine = _legacy_engine()
    with engine.connect() as conn:
        conn.execute(
            text(
                "CREATE TABLE users ("
                "id INTEGER PRIMARY KEY, email VARCHAR(255), "
                "password_hash VARCHAR(128), created_at DATETIME, "
                "updated_at DATETIME)"
            )
        )
        conn.execute(
            text("INSERT INTO users (id, email, password_hash) VALUES (1, 'a@b.c', 'x')")
        )
        conn.commit()

    monkeypatch.setattr(db, "engine", engine)
    db._additive_migrate_users()

    with engine.connect() as conn:
        credits = conn.execute(
            text("SELECT reset_credits FROM users WHERE id = 1")
        ).scalar_one()
    engine.dispose()
    assert credits == 0


def test_funded_combine_is_not_billed(auth_client, session_factory):
    """A FUNDED (activation-paid) combine stops paying the eval monthly and
    banks no reset credit — the account trades firm capital now. Its
    paid_through is frozen forward so it's never past-due, and renew_combines
    reports it under `funded_frozen`, not `renewed`."""
    c = make_combine(auth_client, "50K")  # 1 paid Payment (the purchase)
    old = _now() - timedelta(days=1)
    with session_factory() as s:
        combine = s.get(Combine, c["id"])
        combine.funded_activated_at = _now() - timedelta(days=10)
        combine.paid_through = old
        s.commit()
    before_credits = _user(session_factory).reset_credits

    summary = renew_combines(session_factory=session_factory)
    assert summary["renewed"] == 0
    assert summary["funded_frozen"] == 1
    # No rebill Payment and no banked reset credit off the funded account.
    assert len(_paid_payments(session_factory, c["id"])) == 1
    assert _user(session_factory).reset_credits == before_credits
    with session_factory() as s:
        assert s.get(Combine, c["id"]).paid_through > _now()  # frozen forward
