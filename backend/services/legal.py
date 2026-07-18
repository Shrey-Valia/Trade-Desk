"""Legal-document consent: versions, acceptance capture, and the gates.

`LEGAL_DOC_VERSIONS` is the single source of truth for what "current"
means. Bumping a version here makes every prior acceptance STALE — the
frontend re-prompts and the purchase/activation gates start failing —
with no schema change: acceptances are append-only AgreementAcceptance
rows keyed (user, doc_key, doc_version).

Idempotency: re-accepting a doc at a version already on file is a no-op
(one row per consent event, no duplicates). The funded-trader agreement
is the one nuance — a checkbox acceptance (no signature) does NOT satisfy
the e-sign gate, so a signed acceptance still appends even when an
unsigned row exists at the same version; a second SIGN at the same
version is the no-op (the first signature is the binding record).

Transactions: none of these functions commit — the caller (router) owns
the transaction, matching the combine_state.record_event convention.

Gate errors follow the repo's machine-readable convention: plain string
detail of "<snake_case_code>: <human message>" so the frontend can route
on the code prefix.
"""

from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from models.agreement import AgreementAcceptance
from models.user import User

# doc_key → current version. Bump a value to force re-acceptance.
LEGAL_DOC_VERSIONS: dict[str, int] = {
    "tos": 1,
    "privacy": 1,
    "refund": 1,
    "risk": 1,
    "funded_agreement": 1,
}


def acceptance_status(db: Session, user: User) -> dict[str, dict]:
    """Per-document acceptance state for `user`:
    {doc_key: {accepted_version, current_version, current}}.

    `accepted_version` is the HIGHEST version the user has ever accepted
    (None if never); `current` is whether that satisfies today's version.
    Versions only move up, so >= and == are equivalent — >= is used so a
    rolled-back version bump can never strand users as "stale"."""
    rows = db.execute(
        select(AgreementAcceptance.doc_key, AgreementAcceptance.doc_version).where(
            AgreementAcceptance.user_id == user.id
        )
    ).all()
    accepted: dict[str, int] = {}
    for doc_key, version in rows:
        if doc_key in LEGAL_DOC_VERSIONS:
            accepted[doc_key] = max(accepted.get(doc_key, 0), int(version))
    return {
        key: {
            "accepted_version": accepted.get(key),
            "current_version": current,
            "current": accepted.get(key, 0) >= current,
        }
        for key, current in LEGAL_DOC_VERSIONS.items()
    }


def record_acceptance(
    db: Session,
    user: User,
    doc_keys: list[str],
    ip: str | None,
    signature_name: str | None = None,
) -> None:
    """Append AgreementAcceptance rows for `doc_keys` at their CURRENT
    versions. Idempotent (see module docstring); unknown doc_key → 422.
    Does NOT commit — the caller owns the transaction."""
    unknown = sorted({k for k in doc_keys if k not in LEGAL_DOC_VERSIONS})
    if unknown:
        raise HTTPException(
            422,
            f"unknown_doc_key: {', '.join(unknown)} — valid documents are "
            f"{', '.join(sorted(LEGAL_DOC_VERSIONS))}",
        )
    for key in dict.fromkeys(doc_keys):  # dedupe, preserve request order
        version = LEGAL_DOC_VERSIONS[key]
        existing = (
            db.execute(
                select(AgreementAcceptance).where(
                    AgreementAcceptance.user_id == user.id,
                    AgreementAcceptance.doc_key == key,
                    AgreementAcceptance.doc_version == version,
                )
            )
            .scalars()
            .all()
        )
        # A SIGNED acceptance is only satisfied by an existing signed row;
        # a checkbox acceptance is satisfied by any row at this version.
        if signature_name:
            if any(r.signature_name for r in existing):
                continue
        elif existing:
            continue
        db.add(
            AgreementAcceptance(
                user_id=user.id,
                doc_key=key,
                doc_version=version,
                signature_name=signature_name,
                ip=ip,
            )
        )


def assert_consented(db: Session, user: User) -> None:
    """Purchase gate: BOTH "tos" and "risk" accepted at their current
    versions, else 403 consent_required."""
    status = acceptance_status(db, user)
    if not (status["tos"]["current"] and status["risk"]["current"]):
        raise HTTPException(
            403,
            "consent_required: accept the Terms of Service and Risk "
            "Disclosure to continue",
        )


def assert_funded_agreement_signed(db: Session, user: User) -> None:
    """Funded-account activation gate: "funded_agreement" accepted at its
    current version WITH a typed signature, else 403 agreement_required."""
    signed = db.execute(
        select(AgreementAcceptance.id).where(
            AgreementAcceptance.user_id == user.id,
            AgreementAcceptance.doc_key == "funded_agreement",
            AgreementAcceptance.doc_version >= LEGAL_DOC_VERSIONS["funded_agreement"],
            AgreementAcceptance.signature_name.is_not(None),
            AgreementAcceptance.signature_name != "",
        )
    ).first()
    if signed is None:
        raise HTTPException(
            403,
            "agreement_required: sign the funded-trader agreement to "
            "activate this account",
        )
