"""Legal-document consent — /api/legal/*.

Versioned acceptance capture (ToS/privacy/refund/risk) plus the typed-name
e-sign of the funded-trader agreement. Version arithmetic, idempotency, and
the consent/e-sign gates live in services/legal.py; this router captures the
client IP (dispute evidence) and owns the commit. See
docs/P0_IMPLEMENTATION_PLAN_2026-07-14.md (workstream B1) for the contract.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from database import get_session
from models.user import User
from services.auth import get_current_user
from services.legal import acceptance_status, record_acceptance
from services.rate_limit import _client_ip

router = APIRouter(prefix="/api/legal", tags=["legal"])


class DocStatusOut(BaseModel):
    """One document's acceptance state (see services.legal.acceptance_status)."""

    accepted_version: int | None
    current_version: int
    current: bool


class AcceptRequest(BaseModel):
    doc_keys: list[str] = Field(min_length=1)


class SignFundedAgreementRequest(BaseModel):
    """Typed-name e-sign. Whitespace-only names are refused — the typed
    name IS the signature, so it must carry content after stripping."""

    typed_name: str = Field(min_length=1, max_length=120)

    @field_validator("typed_name")
    @classmethod
    def _stripped_non_empty(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("typed_name must not be blank")
        return value


@router.get("/status", response_model=dict[str, DocStatusOut])
def legal_status(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_session),
) -> dict[str, dict]:
    """Per-document acceptance map for the signed-in user."""
    return acceptance_status(db, user)


@router.post("/accept", response_model=dict[str, DocStatusOut])
def accept_documents(
    payload: AcceptRequest,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_session),
) -> dict[str, dict]:
    """Checkbox acceptance of one or more documents at their CURRENT
    versions. Idempotent; unknown doc_key → 422. The client IP is captured
    per the proxy-trust convention (services.rate_limit._client_ip)."""
    record_acceptance(db, user, payload.doc_keys, ip=_client_ip(request))
    db.commit()
    return acceptance_status(db, user)


@router.post("/sign-funded-agreement", response_model=dict[str, DocStatusOut])
def sign_funded_agreement(
    payload: SignFundedAgreementRequest,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_session),
) -> dict[str, dict]:
    """Typed-name e-sign of the funded-trader agreement — the acceptance
    row carries signature_name, which is what the activation gate
    (services.legal.assert_funded_agreement_signed) requires."""
    record_acceptance(
        db,
        user,
        ["funded_agreement"],
        ip=_client_ip(request),
        signature_name=payload.typed_name,
    )
    db.commit()
    return acceptance_status(db, user)
