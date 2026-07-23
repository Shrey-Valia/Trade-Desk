"""Payout prerequisites — KYC state machine, tax profile, payout methods.

Backs routers/verification.py and the payout gate (workstream C1 calls
`assert_payout_eligible` from POST /api/combines/{id}/payout). See
docs/P0_IMPLEMENTATION_PLAN_2026-07-14.md (workstream B2) for the contract.

Design notes:
  * KYC is a one-row-per-user state machine: unverified (no row) → pending →
    verified | rejected. The provider is the "sim" adapter today: with
    settings.kyc_auto_verify it decides instantly (rejected for OFAC-blocked
    countries, verified otherwise); with it off, submissions park at
    'pending' for `decide_kyc` (the admin router wires it later).
  * Payout-method details are WHITELISTED before storage — only the keys the
    rail actually needs are kept, so a full account number pasted into an
    unexpected field is never persisted. Details are NEVER logged and NEVER
    returned by any API: `masked_method` is the only public shape.
  * Exactly one default method per user whenever any method exists: the
    first added method becomes default, `set_default` clears the others,
    and removing the default promotes the oldest survivor.
"""

from __future__ import annotations

import json
import re
from datetime import date, datetime, timezone

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from config import settings
from models.kyc import KycVerification
from models.payout_method import (
    PAYOUT_METHOD_TYPES,
    TAX_FORM_TYPES,
    PayoutMethod,
    TaxProfile,
)
from models.user import User

# What the sim provider tells an OFAC-blocked applicant. Deliberately vague —
# a sanctions screen never explains itself to the subject.
OFAC_REJECT_REASON = "We cannot verify identities from this jurisdiction."

KYC_DOCUMENT_TYPES = ("passport", "drivers_license", "national_id")

# Crypto rails the simulated disbursement adapter recognizes.
CRYPTO_NETWORKS = ("USDC-ERC20", "USDC-SOL", "BTC")

# Rail-specific detail keys — required on submit AND the only keys retained.
_REQUIRED_DETAIL_KEYS: dict[str, tuple[str, ...]] = {
    "ach": ("routing_number", "account_last4"),
    "wire": ("bank_name", "swift", "account_last4"),
    "crypto": ("network", "address"),
}

_COUNTRY_RE = re.compile(r"^[A-Za-z]{2}$")
_FOUR_DIGITS_RE = re.compile(r"^\d{4}$")
_ROUTING_RE = re.compile(r"^\d{9}$")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _normalize_country(raw: str) -> str:
    """Upper-cased ISO-3166 alpha-2, or 422."""
    country = (raw or "").strip().upper()
    if not _COUNTRY_RE.match(country):
        raise HTTPException(
            422, "invalid_country: country must be a 2-letter ISO code"
        )
    return country


# -- KYC ----------------------------------------------------------------------

def get_kyc(db: Session, user: User) -> KycVerification | None:
    return db.execute(
        select(KycVerification).where(KycVerification.user_id == user.id)
    ).scalar_one_or_none()


def kyc_status(db: Session, user: User) -> tuple[str, str | None]:
    """("unverified" | "pending" | "verified" | "rejected", reject_reason)."""
    row = get_kyc(db, user)
    if row is None:
        return "unverified", None
    return row.status, row.reject_reason


def submit_kyc(
    db: Session,
    user: User,
    legal_name: str,
    dob: date,
    country: str,
    document_type: str,
) -> KycVerification:
    """Create or REPLACE the user's KYC submission and run the sim provider.

    A rejected (or still-pending) user may resubmit — the row is reused so the
    one-row-per-user invariant holds. A verified user has nothing to resubmit:
    409, their identity is already settled.
    """
    country = _normalize_country(country)
    if document_type not in KYC_DOCUMENT_TYPES:
        raise HTTPException(
            422,
            "invalid_document_type: document_type must be one of "
            + ", ".join(KYC_DOCUMENT_TYPES),
        )
    row = get_kyc(db, user)
    if row is not None and row.status == "verified":
        raise HTTPException(409, "already_verified: identity already verified")
    if row is None:
        row = KycVerification(user_id=user.id)
        db.add(row)
    row.provider = "sim"
    row.provider_ref = None
    row.submitted_json = json.dumps(
        {
            "legal_name": legal_name,
            "dob": dob.isoformat(),
            "country": country,
            "document_type": document_type,
        }
    )
    row.submitted_at = _now()
    if settings.kyc_auto_verify:
        blocked = {c.strip().upper() for c in settings.ofac_blocked_countries}
        if country in blocked:
            row.status = "rejected"
            row.reject_reason = OFAC_REJECT_REASON
        else:
            row.status = "verified"
            row.reject_reason = None
        row.decided_at = _now()
    else:
        row.status = "pending"
        row.reject_reason = None
        row.decided_at = None
    db.commit()
    db.refresh(row)
    return row


def decide_kyc(
    db: Session,
    user_id: int,
    approve: bool,
    reason: str | None = None,
    commit: bool = True,
) -> KycVerification:
    """Human decision on a submission — the admin router (C2) calls this.

    Not limited to 'pending': an operator may also overturn a sim decision
    (e.g. reject an auto-verified identity on manual review).

    Pass ``commit=False`` when the caller needs the decision and its audit row
    to land in ONE transaction: committing here first would leave a window where
    a crash lands the KYC decision with no audit trail (the router stages the
    audit row and commits after this returns).
    """
    row = db.execute(
        select(KycVerification).where(KycVerification.user_id == user_id)
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, "kyc_not_found: no KYC submission for this user")
    if approve:
        row.status = "verified"
        row.reject_reason = None
    else:
        row.status = "rejected"
        row.reject_reason = reason or "Identity verification was declined."
    row.decided_at = _now()
    if commit:
        db.commit()
        db.refresh(row)
    else:
        db.flush()
    return row


# -- Tax profile ---------------------------------------------------------------

def get_tax_profile(db: Session, user: User) -> TaxProfile | None:
    return db.execute(
        select(TaxProfile).where(TaxProfile.user_id == user.id)
    ).scalar_one_or_none()


def submit_tax_profile(
    db: Session,
    user: User,
    form_type: str,
    legal_name: str,
    country: str,
    address: dict,
    tin_last4: str | None = None,
) -> TaxProfile:
    """Upsert the user's tax declaration (one row per user).

    W-9 is the US-person form and W-8BEN the non-US one, so each form pins
    the declared country to its side of that line.
    """
    if form_type not in TAX_FORM_TYPES:
        raise HTTPException(422, "invalid_form_type: form_type must be W9 or W8BEN")
    country = _normalize_country(country)
    if form_type == "W9" and country != "US":
        raise HTTPException(
            422, "form_country_mismatch: a W-9 is for US persons — use a W-8BEN"
        )
    if form_type == "W8BEN" and country == "US":
        raise HTTPException(
            422, "form_country_mismatch: a W-8BEN is for non-US persons — use a W-9"
        )
    if tin_last4 is not None and not _FOUR_DIGITS_RE.match(tin_last4):
        raise HTTPException(
            422, "invalid_tin_last4: tin_last4 must be exactly 4 digits"
        )
    row = get_tax_profile(db, user)
    if row is None:
        row = TaxProfile(
            user_id=user.id,
            form_type=form_type,
            legal_name=legal_name,
            country=country,
        )
        db.add(row)
    row.form_type = form_type
    row.legal_name = legal_name
    row.country = country
    row.address_json = json.dumps(address)
    row.tin_last4 = tin_last4
    row.submitted_at = _now()
    db.commit()
    db.refresh(row)
    return row


# -- Payout methods -------------------------------------------------------------

def _validate_details(method_type: str, details: dict) -> dict[str, str]:
    """Validate the rail-specific fields and return ONLY the whitelisted keys.

    Whitelisting is a privacy guard: whatever else the client sends (a full
    account number in a stray key, say) never reaches the database.
    """
    clean: dict[str, str] = {}
    for key in _REQUIRED_DETAIL_KEYS[method_type]:
        value = details.get(key)
        text = str(value).strip() if value is not None else ""
        if not text:
            raise HTTPException(
                422, f"missing_detail: {method_type} methods require '{key}'"
            )
        clean[key] = text
    if method_type == "ach" and not _ROUTING_RE.match(clean["routing_number"]):
        raise HTTPException(
            422, "invalid_routing_number: routing_number must be exactly 9 digits"
        )
    if "account_last4" in clean and not _FOUR_DIGITS_RE.match(clean["account_last4"]):
        raise HTTPException(
            422, "invalid_account_last4: account_last4 must be exactly 4 digits"
        )
    if method_type == "crypto" and clean["network"] not in CRYPTO_NETWORKS:
        raise HTTPException(
            422,
            "invalid_network: network must be one of " + ", ".join(CRYPTO_NETWORKS),
        )
    return clean


def masked_method(row: PayoutMethod) -> dict:
    """The ONLY payout-method shape any API response may carry — details_json
    stays server-side."""
    return {
        "id": row.id,
        "type": row.type,
        "label": row.label,
        "is_default": row.is_default,
        "created_at": row.created_at,
    }


def list_methods(db: Session, user: User) -> list[dict]:
    rows = (
        db.execute(
            select(PayoutMethod)
            .where(PayoutMethod.user_id == user.id)
            .order_by(PayoutMethod.created_at.asc(), PayoutMethod.id.asc())
        )
        .scalars()
        .all()
    )
    return [masked_method(row) for row in rows]


def add_method(
    db: Session, user: User, method_type: str, label: str, details: dict
) -> PayoutMethod:
    if method_type not in PAYOUT_METHOD_TYPES:
        raise HTTPException(
            422, "invalid_method_type: type must be one of ach, wire, crypto"
        )
    clean = _validate_details(method_type, details or {})
    has_existing = (
        db.execute(
            select(PayoutMethod.id).where(PayoutMethod.user_id == user.id).limit(1)
        ).scalar_one_or_none()
        is not None
    )
    row = PayoutMethod(
        user_id=user.id,
        type=method_type,
        label=label.strip(),
        details_json=json.dumps(clean),
        is_default=not has_existing,  # first method on file becomes the default
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _get_owned_method(db: Session, user: User, method_id: int) -> PayoutMethod:
    row = db.get(PayoutMethod, method_id)
    # 404 on both missing and not-owned so existence isn't leaked across users.
    if row is None or row.user_id != user.id:
        raise HTTPException(404, "method_not_found: payout method not found")
    return row


def remove_method(db: Session, user: User, method_id: int) -> None:
    row = _get_owned_method(db, user, method_id)
    was_default = row.is_default
    db.delete(row)
    db.flush()
    if was_default:
        # Invariant: whenever any methods exist, exactly one is default —
        # promote the oldest survivor.
        successor = db.execute(
            select(PayoutMethod)
            .where(PayoutMethod.user_id == user.id)
            .order_by(PayoutMethod.created_at.asc(), PayoutMethod.id.asc())
            .limit(1)
        ).scalar_one_or_none()
        if successor is not None:
            successor.is_default = True
    db.commit()


def set_default(db: Session, user: User, method_id: int) -> PayoutMethod:
    row = _get_owned_method(db, user, method_id)
    others = (
        db.execute(select(PayoutMethod).where(PayoutMethod.user_id == user.id))
        .scalars()
        .all()
    )
    for method in others:
        method.is_default = method.id == row.id
    db.commit()
    db.refresh(row)
    return row


# -- Payout gate (consumed by workstream C1) -------------------------------------

def assert_payout_eligible(db: Session, user: User) -> None:
    """Raise 403 unless every ENABLED payout prerequisite is met.

    Each check is individually toggleable via settings so sim demos and tests
    can relax them. Details are stable "code: message" strings the frontend
    routes on: kyc_required | tax_profile_required | payout_method_required.
    """
    if settings.payout_require_kyc:
        status, _reason = kyc_status(db, user)
        if status != "verified":
            raise HTTPException(
                403, "kyc_required: verify your identity before requesting a payout"
            )
    if settings.payout_require_tax_profile:
        if get_tax_profile(db, user) is None:
            raise HTTPException(
                403,
                "tax_profile_required: submit a W-9 or W-8BEN before requesting a payout",
            )
    if settings.payout_require_method:
        has_method = (
            db.execute(
                select(PayoutMethod.id).where(PayoutMethod.user_id == user.id).limit(1)
            ).scalar_one_or_none()
            is not None
        )
        if not has_method:
            raise HTTPException(
                403,
                "payout_method_required: add a payout method before requesting a payout",
            )
