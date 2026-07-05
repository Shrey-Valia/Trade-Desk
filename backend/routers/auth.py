"""Auth endpoints — signup / signin / signout / me.

Email is normalized (lowercase, stripped) and sanity-checked with a
light regex; the full email-validator dependency is overkill for a
dev-stage product. Signin returns the SAME 401 body for unknown email
and wrong password so the endpoint doesn't leak which emails exist.
"""

from __future__ import annotations

import re
from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from database import get_session
from models.user import User
from services.auth import (
    SESSION_COOKIE,
    create_session,
    get_current_user,
    hash_password,
    revoke_other_sessions,
    revoke_session,
    set_session_cookie,
    verify_password,
)
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


class UserOut(BaseModel):
    id: int
    email: str
    display_name: str | None


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
    return UserOut(id=user.id, email=user.email, display_name=user.display_name)


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
    # Identical message for unknown email and bad password.
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(401, "invalid email or password")
    set_session_cookie(response, create_session(session, user.id))
    return UserOut(id=user.id, email=user.email, display_name=user.display_name)


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
def me(user: User = Depends(get_current_user)) -> UserOut:
    return UserOut(id=user.id, email=user.email, display_name=user.display_name)
