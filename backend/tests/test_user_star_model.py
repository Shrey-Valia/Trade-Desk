"""UserStar hygiene — user_id is mandatory (no silent single-tenant default).

The model used to default user_id=1 from the single-tenant era: an insert
path that forgot user_id would silently file the star under user 1 — a
cross-tenant leak. Now there is no default and the column declares a
users.id FK (applies to fresh installs; SQLite won't retrofit it onto an
existing table), so a forgotten user_id fails loudly at flush.
"""

from __future__ import annotations

import pytest
from sqlalchemy.exc import IntegrityError

from models.user_star import UserStar


def test_insert_without_user_id_fails_loudly(session_factory):
    with session_factory() as s:
        s.add(UserStar(symbol="SPY"))
        with pytest.raises(IntegrityError):
            s.flush()


def test_user_id_declares_users_fk_and_no_default():
    col = UserStar.__table__.c.user_id
    assert [fk.target_fullname for fk in col.foreign_keys] == ["users.id"]
    assert col.default is None
    assert col.nullable is False
