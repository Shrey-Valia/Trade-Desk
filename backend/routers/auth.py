"""Auth endpoints — signup / signin / signout / me, plus account recovery.

Email is normalized (lowercase, stripped) and sanity-checked with a
light regex; the full email-validator dependency is overkill for a
dev-stage product. Signin returns the SAME 401 body for unknown email
and wrong password so the endpoint doesn't leak which emails exist —
and /forgot returns 204 whether or not the account exists, for the
same anti-enumeration reason.
"""

from __future__ import annotations

import hashlib
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from config import settings
from database import get_session
from models.password_reset import PasswordResetToken
from models.user import User
from services.auth import (
    SESSION_COOKIE,
    create_session,
    get_current_user,
    hash_password,
    maybe_bootstrap_admin,
    revoke_other_sessions,
    revoke_session,
    set_session_cookie,
    verify_password,
    verify_password_timing_safe,
)
from services.notify import enqueue_email
from services.rate_limit import auth_limiter, enforce

router = APIRouter(prefix="/api/auth", tags=["auth"])

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$|^[^@\s]+@local$")

# Password policy — ONE constraint shared by signup and change-password so
# the two validators can never drift apart.
Password = Annotated[str, Field(min_length=8, max_length=128)]


class SignupIn(BaseModel):
    email: str = Field(..., max_length=255)
    password: Password
    display_name: str | None = Field(default=None, max_length=64)


class SigninIn(BaseModel):
    email: str = Field(..., max_length=255)
    password: str = Field(..., max_length=128)


class ChangePasswordIn(BaseModel):
    # Current password gets the signin treatment (length-capped only — it's
    # being verified, not stored); the new one must pass the signup policy.
    current_password: str = Field(..., max_length=128)
    new_password: Password


class ForgotIn(BaseModel):
    email: str = Field(..., max_length=255)


class ResetIn(BaseModel):
    # token_urlsafe(32) is 43 chars; the cap just bounds garbage input.
    token: str = Field(..., min_length=8, max_length=128)
    new_password: Password


class UserOut(BaseModel):
    id: int
    email: str
    display_name: str | None
    # "trader" | "admin" — the frontend gates the /admin console on this.
    role: str = "trader"


def _normalize_email(raw: str) -> str:
    email = raw.strip().lower()
    if not _EMAIL_RE.match(email):
        raise HTTPException(422, "invalid email address")
    return email


@router.post("/signup", response_model=UserOut, status_code=201)
def signup(
    payload: SignupIn,
    request: Request,
    response: Response,
    session: Session = Depends(get_session),
) -> UserOut:
    enforce(auth_limiter, request, "signup")
    email = _normalize_email(payload.email)
    existing = session.execute(
        select(User.id).where(User.email == email)
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(409, "an account with this email already exists")
    user = User(
        email=email,
        password_hash=hash_password(payload.password),
        display_name=(payload.display_name or "").strip() or None,
    )
    session.add(user)
    session.commit()
    session.refresh(user)
    set_session_cookie(response, create_session(session, user.id))
    return UserOut(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        role=user.role,
    )


@router.post("/signin", response_model=UserOut)
def signin(
    payload: SigninIn,
    request: Request,
    response: Response,
    session: Session = Depends(get_session),
) -> UserOut:
    enforce(auth_limiter, request, "signin")
    email = payload.email.strip().lower()
    user = session.execute(
        select(User).where(User.email == email)
    ).scalar_one_or_none()
    # Identical message AND identical timing for unknown email vs bad password
    # (the timing-safe verify burns equal bcrypt work on the user-is-None path).
    ok = verify_password_timing_safe(
        payload.password, user.password_hash if user else None
    )
    if user is None or not ok:
        raise HTTPException(401, "invalid email or password")
    set_session_cookie(response, create_session(session, user.id))
    return UserOut(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        role=user.role,
    )


@router.post("/change-password", status_code=204)
def change_password(
    payload: ChangePasswordIn,
    request: Request,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
    td_session: str | None = Cookie(default=None, alias=SESSION_COOKIE),
) -> None:
    enforce(auth_limiter, request, "change-password")
    # 403, not 401 — the caller IS authenticated (valid cookie); they failed
    # the re-prove step. A 401 here would look like a dead session to clients.
    if not verify_password(payload.current_password, user.password_hash):
        raise HTTPException(403, "current password is incorrect")
    user.password_hash = hash_password(payload.new_password)
    # A password change is the "kick out anyone else holding this account"
    # action: revoke every OTHER session; the one that just proved the current
    # password keeps its row (sliding renewal untouched). One commit lands the
    # new hash + the revocation atomically.
    revoke_other_sessions(session, user.id, td_session)
    session.commit()


@router.post("/forgot", status_code=204)
def forgot_password(
    payload: ForgotIn,
    request: Request,
    session: Session = Depends(get_session),
) -> None:
    """Start account recovery. ALWAYS 204 — the response is identical for
    known and unknown emails so this endpoint can't be used to enumerate
    accounts. When the account exists: prior UNUSED tokens are invalidated
    (exactly one live link at a time), a fresh single-use token is minted
    (raw in the email, sha256 in the DB — same custody as sessions), and
    the reset email is queued through the outbox."""
    enforce(auth_limiter, request, "forgot")
    email = payload.email.strip().lower()
    user = session.execute(
        select(User).where(User.email == email)
    ).scalar_one_or_none()
    if user is None:
        return
    session.execute(
        delete(PasswordResetToken).where(
            PasswordResetToken.user_id == user.id,
            PasswordResetToken.used_at.is_(None),
        )
    )
    raw = secrets.token_urlsafe(32)
    session.add(
        PasswordResetToken(
            token_hash=hashlib.sha256(raw.encode("ascii")).hexdigest(),
            user_id=user.id,
            expires_at=datetime.now(timezone.utc)
            + timedelta(hours=settings.password_reset_ttl_h),
        )
    )
    link = f"{settings.frontend_base_url}/reset-password?token={raw}"
    enqueue_email(
        session,
        to_email=user.email,
        template="password_reset",
        subject="Reset your Trade Desk password",
        body=(
            "Someone requested a password reset for this account.\n\n"
            f"Reset your password: {link}\n\n"
            f"The link expires in {settings.password_reset_ttl_h:g} hours "
            "and can be used once. If this wasn't you, ignore this email — "
            "your password is unchanged."
        ),
        user_id=user.id,
    )
    session.commit()


@router.post("/reset", status_code=204)
def reset_password(
    payload: ResetIn,
    request: Request,
    session: Session = Depends(get_session),
) -> None:
    """Complete account recovery with an emailed token. Expired rows are
    deleted lazily on the way through; a used/expired/unknown token gets
    one generic 400 (no oracle for which check failed). Success lands the
    new hash, marks the token used, and revokes EVERY session — whoever
    triggered the reset holds the only path in — in one commit."""
    enforce(auth_limiter, request, "reset")
    now = datetime.now(timezone.utc)
    # Lazy cleanup — committed only on the success path; rejected requests
    # roll back and the rows are swept by the next successful reset.
    session.execute(
        delete(PasswordResetToken).where(PasswordResetToken.expires_at <= now)
    )
    row = session.get(
        PasswordResetToken,
        hashlib.sha256(payload.token.encode("utf-8")).hexdigest(),
    )
    if row is None or row.used_at is not None or row.expires_at <= now:
        raise HTTPException(
            400, "invalid_token: this reset link is invalid or expired"
        )
    user = session.get(User, row.user_id)
    if user is None:
        raise HTTPException(
            400, "invalid_token: this reset link is invalid or expired"
        )
    user.password_hash = hash_password(payload.new_password)
    row.used_at = now
    # current_raw_token=None → revoke ALL sessions for the account.
    revoke_other_sessions(session, user.id, None)
    session.commit()


@router.post("/signout", status_code=204)
def signout(
    response: Response,
    session: Session = Depends(get_session),
    td_session: str | None = Cookie(default=None, alias=SESSION_COOKIE),
) -> None:
    # Cookie read directly (not via get_current_user) so signout is
    # idempotent — an expired/garbage cookie still clears cleanly.
    if td_session:
        revoke_session(session, td_session)
    response.delete_cookie(SESSION_COOKIE, path="/")


@router.get("/me", response_model=UserOut)
def me(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_session),
) -> UserOut:
    # Apply the admin allowlist bootstrap here too: the frontend gates the
    # /admin route on this endpoint's `role`, and would redirect a not-yet-
    # promoted allow-listed operator away before any /api/admin/* call could
    # trigger promotion. Idempotent — no write once already admin.
    maybe_bootstrap_admin(user, db)
    return UserOut(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        role=user.role,
    )
