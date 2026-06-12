"""_backfill_multiuser — one-time adoption of a pre-multi-user DB."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select

from config import settings
from database import _backfill_multiuser
from models.account_state import AccountState
from models.combine import Combine
from models.payment import Payment
from models.trade import Trade
from models.user import User


def _legacy_trade(tier: str, **kw) -> Trade:
    return Trade(
        symbol="SPY",
        strategy="long_call",
        legs_json='[{"side":"call","action":"buy","strike":740.0,'
        '"expiry":"2026-06-12","contracts":1,"entry_price":1.5}]',
        entry_date=datetime(2026, 6, 10, 14, 30, tzinfo=timezone.utc),
        entry_underlying_price=740.0,
        net_debit_credit=150.0,
        status="closed",
        exit_date=datetime(2026, 6, 10, 15, 30, tzinfo=timezone.utc),
        realized_pnl=25.0,
        is_paper=True,
        tier=tier,
        combine_id=None,
        **kw,
    )


def test_backfill_adopts_legacy_db(session_factory):
    with session_factory() as s:
        s.add(AccountState(id=1, active_tier="100K", hwm_50k=51_200.0))
        s.add(_legacy_trade("50K"))
        s.add(_legacy_trade("50K"))
        s.add(_legacy_trade("100K"))
        s.commit()

    _backfill_multiuser(session_factory)

    with session_factory() as s:
        dev = s.execute(
            select(User).where(User.email == settings.dev_user_email)
        ).scalar_one()
        combines = s.execute(select(Combine)).scalars().all()
        assert {c.tier for c in combines} == {"50K", "100K"}
        by_tier = {c.tier: c for c in combines}
        # HWM carried from legacy AccountState (51,200 > 50,000 start).
        assert by_tier["50K"].hwm == 51_200.0
        # 100K had no legacy HWM recorded → seeded to starting balance.
        assert by_tier["100K"].hwm == 100_000.0
        # Active combine follows legacy active_tier.
        assert dev.active_combine_id == by_tier["100K"].id
        # Every trade mapped.
        assert (
            s.execute(
                select(Trade).where(Trade.combine_id.is_(None))
            ).scalars().all()
            == []
        )
        # Migration grants recorded.
        payments = s.execute(select(Payment)).scalars().all()
        assert len(payments) == 2
        assert all(p.status == "migration_grant" for p in payments)
        assert all(p.amount is None for p in payments)


def test_backfill_idempotent(session_factory):
    with session_factory() as s:
        s.add(AccountState(id=1))
        s.add(_legacy_trade("50K"))
        s.commit()

    _backfill_multiuser(session_factory)
    _backfill_multiuser(session_factory)

    with session_factory() as s:
        assert len(s.execute(select(Combine)).scalars().all()) == 1
        assert len(s.execute(select(User)).scalars().all()) == 1
        assert len(s.execute(select(Payment)).scalars().all()) == 1


def test_backfill_noop_on_fresh_db(session_factory):
    _backfill_multiuser(session_factory)
    with session_factory() as s:
        # Fresh install: NO dev user, signup-first flow.
        assert s.execute(select(User)).scalars().all() == []
        assert s.execute(select(Combine)).scalars().all() == []
