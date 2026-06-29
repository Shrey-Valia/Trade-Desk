"""Auth primitives: bcrypt passwords, DB-backed sessions, FastAPI deps.

Design choices:
  * bcrypt called directly (passlib is unmaintained and breaks against
    bcrypt 4.x). Cost factor from settings so tests can drop it to 4.
  * Sessions live in the auth_sessions table — revocable on signout,
    no signing-key secret to manage. The cookie carries the raw token;
    the DB stores only its sha256, so a DB leak yields nothing live.
  * Expired session rows are deleted lazily on lookup.

Cookie: td_session, HttpOnly, SameSite=Lax, lifetime from settings
(session_ttl_days, default 14). localhost:5173 → localhost:8000 is
same-SITE (port is excluded from site comparisons), so Lax flows on the
dev cross-origin XHR — and the Vite proxy makes it plain same-origin
anyway. The Secure flag is settings.cookie_secure (prod-safe by default;
see config.py).
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone

import bcrypt
from fastapi import Cookie, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from config import settings
from database import get_session
from models.auth_session import AuthSession
from models.combine import Combine
from models.user import User

SESSION_COOKIE = "td_session"


def session_ttl() -> timedelta:
    """Session lifetime, read from settings at call time so an override (e.g. a
    test or a per-deployment SESSION_TTL_DAYS) takes effect without a reimport.
    Drives both the auth_sessions row TTL and the cookie Max-Age."""
    return settings.session_ttl


# -- passwords ---------------------------------------------------------------

def hash_password(plain: str) -> str:
    return bcrypt.hashpw(
        plain.encode("utf-8"), bcrypt.gensalt(rounds=settings.bcrypt_rounds)
    ).decode("ascii")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("ascii"))
    except ValueError:
        # Malformed hash in the DB — treat as auth failure, not a 500.
        return False


# -- sessions ----------------------------------------------------------------

def _hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode("ascii")).hexdigest()


def create_session(db: Session, user_id: int) -> str:
    """Create a session row and return the RAW token for the cookie."""
    raw = secrets.token_urlsafe(32)
    db.add(
        AuthSession(
            token_hash=_hash_token(raw),
            user_id=user_id,
            expires_at=datetime.now(timezone.utc) + session_ttl(),
        )
    )
    db.commit()
    return raw


def revoke_session(db: Session, raw_token: str) -> None:
    row = db.get(AuthSession, _hash_token(raw_token))
    if row is not None:
        db.delete(row)
        db.commit()


# -- FastAPI dependencies ----------------------------------------------------

def get_current_user(
    td_session: str | None = Cookie(default=None, alias=SESSION_COOKIE),
    db: Session = Depends(get_session),
) -> User:
    if not td_session:
        raise HTTPException(401, "not authenticated")
    row = db.get(AuthSession, _hash_token(td_session))
    if row is None:
        raise HTTPException(401, "not authenticated")
    if row.expires_at <= datetime.now(timezone.utc):
        db.delete(row)
        db.commit()
        raise HTTPException(401, "session expired")
    user = db.get(User, row.user_id)
    if user is None:
        raise HTTPException(401, "not authenticated")
    return user


def get_active_combine(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_session),
) -> Combine:
    """The user's active combine — 409 when they have none (fresh signup
    or all archived). 409 rather than 404 so the frontend can tell
    "no combine yet, show purchase CTA" apart from a missing resource."""
    if user.active_combine_id is None:
        raise HTTPException(409, "no active combine — purchase one to start trading")
    combine = db.execute(
        select(Combine).where(
            Combine.id == user.active_combine_id,
            Combine.user_id == user.id,
            Combine.status != "archived",
        )
    ).scalar_one_or_none()
    if combine is None:
        raise HTTPException(409, "no active combine — purchase one to start trading")
    return combine
