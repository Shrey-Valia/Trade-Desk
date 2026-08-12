"""Invite-code domain logic — minting, status derivation, redemption.

The single implementation both callers share: routers/admin.py (mint /
list / revoke) and routers/auth.py (redeem at signup). Keeping `redeem`
here is what makes the race guarantee auditable in one place.

Status is DERIVED, never stored — a stored status column would need a
scheduled sweep to age codes into `expired`, and would drift from the
timestamps the moment that job missed a run.
"""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import update
from sqlalchemy.orm import Session

from models.invite import Invite

# Unambiguous alphabet: no 0/O, no 1/I/L, no 5/S, no 8/B. Codes get read
# aloud, typed off a phone screen, and pasted out of chat messages.
_ALPHABET = "234679ACDEFGHJKMNPQRTUVWXYZ"
_GROUPS = 2
_GROUP_LEN = 4

# Derived states, in the order the admin filter chips present them.
INVITE_STATES = ("active", "redeemed", "revoked", "expired")


def generate_code() -> str:
    """A fresh, transcribable code: TD-XXXX-XXXX.

    8 characters over a 27-symbol alphabet is ~38 bits — far beyond reach
    of the signup rate limiter (10 attempts/minute/IP), and every code is
    single-use and individually revocable on top of that.
    """
    body = "-".join(
        "".join(secrets.choice(_ALPHABET) for _ in range(_GROUP_LEN))
        for _ in range(_GROUPS)
    )
    return f"TD-{body}"


def mint_code(db: Session) -> str:
    """generate_code() with a collision retry against the unique index.

    A collision is astronomically unlikely; the loop exists so that if one
    ever happens it's a retry rather than a 500 on the operator's screen.
    """
    for _ in range(5):
        code = generate_code()
        exists = db.query(Invite.id).filter(Invite.code == code).first()
        if exists is None:
            return code
    raise RuntimeError("could not mint a unique invite code")


def normalize_code(raw: str) -> str:
    """Codes are case- and whitespace-insensitive on the way in. Invitees
    retype them by hand; a lowercase paste must not read as 'wrong code'."""
    return raw.strip().upper()


def invite_status(inv: Invite, now: datetime | None = None) -> str:
    """Derived state. Redeemed and revoked are terminal and outrank
    expiry — 'this was used' is the more useful answer than 'this aged
    out' when an operator is reading the list."""
    if inv.redeemed_at is not None:
        return "redeemed"
    if inv.revoked_at is not None:
        return "revoked"
    now = now or datetime.now(timezone.utc)
    if inv.expires_at is not None and inv.expires_at <= now:
        return "expired"
    return "active"


def expiry_from_days(days: float | None) -> datetime | None:
    """Mint-time TTL → absolute instant. None (or a non-positive value)
    means the code never expires."""
    if days is None or days <= 0:
        return None
    return datetime.now(timezone.utc) + timedelta(days=days)


class InviteError(Exception):
    """A redemption refusal carrying the repo's '<code>: <message>' detail
    convention, so the frontend can route on the code and toast the text."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


def redeem(db: Session, raw_code: str, email: str, user_id: int) -> Invite:
    """Consume `raw_code` for `email`/`user_id`, or raise InviteError.

    Does NOT commit — the caller owns the transaction, so the redemption
    and the user row it belongs to land together or not at all.

    The final claim is a CONDITIONAL UPDATE (`WHERE redeemed_at IS NULL`)
    rather than a read-then-write: two signups posting the same code at the
    same instant both pass the checks above, and exactly one gets a
    rowcount of 1. The loser raises `already_redeemed` and its whole
    transaction — including its half-built user — rolls back.
    """
    code = normalize_code(raw_code)
    inv = db.query(Invite).filter(Invite.code == code).one_or_none()
    if inv is None:
        raise InviteError("invalid_invite", "That invite code isn't valid.")

    status = invite_status(inv)
    if status == "redeemed":
        raise InviteError(
            "already_redeemed", "That invite code has already been used."
        )
    if status == "revoked":
        raise InviteError("revoked_invite", "That invite code was revoked.")
    if status == "expired":
        raise InviteError("expired_invite", "That invite code has expired.")

    if inv.email is not None and inv.email != email:
        # Deliberately does not name the bound address — the signup form is
        # unauthenticated, and echoing it back would turn a leaked code into
        # an email-address disclosure.
        raise InviteError(
            "wrong_email", "That invite code was issued for a different email."
        )

    claimed = db.execute(
        update(Invite)
        .where(Invite.id == inv.id, Invite.redeemed_at.is_(None))
        .values(
            redeemed_at=datetime.now(timezone.utc),
            redeemed_by_id=user_id,
        )
    )
    if claimed.rowcount != 1:
        raise InviteError(
            "already_redeemed", "That invite code has already been used."
        )
    db.refresh(inv)
    return inv
