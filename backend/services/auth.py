"""Auth primitives: bcrypt passwords, DB-backed sessions, FastAPI deps.

Design choices:
  * bcrypt called directly (passlib is unmaintained and breaks against
    bcrypt 4.x). Cost factor from settings so tests can drop it to 4.
  * Sessions live in the auth_sessions table — revocable on signout,
    no signing-key secret to manage. The cookie carries the raw token;
    the DB stores only its sha256, so a DB leak yields nothing live.
  * Expired session rows are deleted lazily on lookup.
  * Sessions SLIDE: past the halfway point of the TTL, any authenticated
    request renews the row AND the cookie Max-Age to a full TTL, so an
    active user never gets hard-logged-out mid-session.

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
from fastapi import Cookie, Depends, HTTPException, Response
from sqlalchemy import delete, select
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


def set_session_cookie(response: Response, raw_token: str) -> None:
    """Issue (or refresh) the session cookie. Lives here — not in the auth
    router — so the sliding-renewal path in get_current_user can reuse it
    without a routers→services→routers import cycle, and the cookie
    attributes can never drift between issue and refresh."""
    response.set_cookie(
        SESSION_COOKIE,
        raw_token,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
        max_age=int(session_ttl().total_seconds()),
        path="/",
    )


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


# A throwaway bcrypt hash used to burn equivalent work on the "no such user"
# login path, so response latency doesn't reveal whether an email is
# registered. Cached per cost factor (tests drop bcrypt_rounds to 4) so it's
# computed once and always matches a real verify's timing.
_dummy_hash_cache: dict[int, str] = {}


def verify_password_timing_safe(plain: str, hashed: str | None) -> bool:
    """Password check that does equal work whether or not the account exists.

    On the unknown-email path `hashed` is None; we still run a full bcrypt
    verify against a dummy hash (at the current cost factor) and return False,
    so a bad-password-for-a-real-user and a nonexistent-user take the same time
    — closing the account-enumeration timing side-channel."""
    if hashed is None:
        dummy = _dummy_hash_cache.get(settings.bcrypt_rounds)
        if dummy is None:
            dummy = hash_password("timing-equalizer")
            _dummy_hash_cache[settings.bcrypt_rounds] = dummy
        verify_password(plain, dummy)
        return False
    return verify_password(plain, hashed)


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


def revoke_other_sessions(db: Session, user_id: int, current_raw_token: str | None) -> None:
    """Delete every session for `user_id` EXCEPT the one carrying
    `current_raw_token` — password-change semantics: anyone else holding the
    account is kicked, the session that just proved the current password
    survives (same row/token, so sliding renewal keeps working on it).

    Does NOT commit — the caller lands the new password hash and the
    revocation in ONE transaction, so a crash can't leave old sessions
    alive against a new password (or vice versa)."""
    stmt = delete(AuthSession).where(AuthSession.user_id == user_id)
    if current_raw_token:
        stmt = stmt.where(AuthSession.token_hash != _hash_token(current_raw_token))
    db.execute(stmt)


# -- FastAPI dependencies ----------------------------------------------------

def get_current_user(
    response: Response,
    td_session: str | None = Cookie(default=None, alias=SESSION_COOKIE),
    db: Session = Depends(get_session),
) -> User:
    if not td_session:
        raise HTTPException(401, "not authenticated")
    row = db.get(AuthSession, _hash_token(td_session))
    if row is None:
        raise HTTPException(401, "not authenticated")
    now = datetime.now(timezone.utc)
    if row.expires_at <= now:
        db.delete(row)
        db.commit()
        raise HTTPException(401, "session expired")
    # Sliding renewal: once a session is past the HALFWAY point of its TTL,
    # any authenticated request extends it to a full TTL again — an active
    # daily trader is never hard-logged-out mid-session on day 14. The
    # halfway gate keeps this write-free for fresh sessions (no per-request
    # UPDATE churn). Revocation is untouched: signout still deletes the row,
    # and a truly idle session still expires after one full TTL. FastAPI
    # injects `response` into dependencies, so the cookie Max-Age is
    # refreshed on the same response (same raw token, no re-issue).
    ttl = session_ttl()
    if row.expires_at - now < ttl / 2:
        row.expires_at = now + ttl
        db.commit()
        set_session_cookie(response, td_session)
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
