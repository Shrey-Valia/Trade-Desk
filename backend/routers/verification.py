"""Payout prerequisites — /api/verification/*.

KYC state machine (simulated provider), tax-profile (W-9/W-8BEN) collection,
and payout-method CRUD. See docs/P0_IMPLEMENTATION_PLAN_2026-07-14.md
(workstream B2) for the contract.

Every endpoint is authed. Payout-method responses are MASKED — the
rail-specific details never leave the server (see services.verification).
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from config import settings
from database import get_session
from models.user import User
from services import verification
from services.auth import get_current_user

router = APIRouter(prefix="/api/verification", tags=["verification"])


# -- Schemas -------------------------------------------------------------------

class KycSubmitIn(BaseModel):
    legal_name: str = Field(..., min_length=1, max_length=120)
    # "YYYY-MM-DD"; pydantic rejects impossible dates (e.g. Feb 30).
    dob: date
    country: str = Field(..., min_length=2, max_length=2)
    document_type: Literal["passport", "drivers_license", "national_id"]

    @field_validator("legal_name")
    @classmethod
    def _name_not_blank(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("legal_name must not be blank")
        return v

    @field_validator("dob")
    @classmethod
    def _adult(cls, v: date) -> date:
        today = datetime.now(timezone.utc).date()
        age = today.year - v.year - ((today.month, today.day) < (v.month, v.day))
        if age < 18:
            raise ValueError("you must be at least 18 to verify your identity")
        return v


class KycOut(BaseModel):
    # "unverified" | "pending" | "verified" | "rejected"
    status: str
    reject_reason: str | None = None


class AddressIn(BaseModel):
    line1: str = Field(..., min_length=1, max_length=120)
    line2: str | None = Field(default=None, max_length=120)
    city: str = Field(..., min_length=1, max_length=80)
    region: str = Field(..., min_length=1, max_length=80)
    postal: str = Field(..., min_length=1, max_length=20)
    country: str = Field(..., min_length=2, max_length=2)


class TaxSubmitIn(BaseModel):
    form_type: Literal["W9", "W8BEN"]
    legal_name: str = Field(..., min_length=1, max_length=120)
    country: str = Field(..., min_length=2, max_length=2)
    address: AddressIn
    # Last 4 of SSN/EIN (W-9) or foreign TIN (W-8BEN); format enforced in the
    # service (exactly 4 digits when present).
    tin_last4: str | None = Field(default=None, max_length=4)


class TaxOut(BaseModel):
    submitted: bool
    form_type: str | None = None


class MethodIn(BaseModel):
    type: Literal["ach", "wire", "crypto"]
    label: str = Field(..., min_length=1, max_length=64)
    # Rail-specific fields — required keys per type are validated (and
    # whitelisted) in the service layer.
    details: dict = Field(default_factory=dict)


class PayoutMethodOut(BaseModel):
    """Masked shape only — never carries the stored details."""

    id: int
    type: str
    label: str
    is_default: bool
    created_at: datetime


class RequirementsOut(BaseModel):
    # Which prerequisites this deployment enforces (mirrors settings), so the
    # frontend only walks the user through gates that actually apply.
    kyc: bool
    tax: bool
    method: bool


class VerificationStatusOut(BaseModel):
    kyc: KycOut
    tax: TaxOut
    payout_methods: list[PayoutMethodOut]
    requirements: RequirementsOut


# -- Endpoints -----------------------------------------------------------------

@router.get("/status", response_model=VerificationStatusOut)
def verification_status(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_session),
) -> VerificationStatusOut:
    status, reject_reason = verification.kyc_status(db, user)
    tax = verification.get_tax_profile(db, user)
    return VerificationStatusOut(
        kyc=KycOut(status=status, reject_reason=reject_reason),
        tax=TaxOut(
            submitted=tax is not None,
            form_type=tax.form_type if tax is not None else None,
        ),
        payout_methods=[
            PayoutMethodOut(**m) for m in verification.list_methods(db, user)
        ],
        requirements=RequirementsOut(
            kyc=settings.payout_require_kyc,
            tax=settings.payout_require_tax_profile,
            method=settings.payout_require_method,
        ),
    )


@router.post("/kyc/submit", response_model=KycOut)
def submit_kyc(
    payload: KycSubmitIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_session),
) -> KycOut:
    row = verification.submit_kyc(
        db,
        user,
        legal_name=payload.legal_name,
        dob=payload.dob,
        country=payload.country,
        document_type=payload.document_type,
    )
    return KycOut(status=row.status, reject_reason=row.reject_reason)


@router.post("/tax/submit", response_model=TaxOut)
def submit_tax_profile(
    payload: TaxSubmitIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_session),
) -> TaxOut:
    row = verification.submit_tax_profile(
        db,
        user,
        form_type=payload.form_type,
        legal_name=payload.legal_name.strip(),
        country=payload.country,
        address=payload.address.model_dump(exclude_none=True),
        tin_last4=payload.tin_last4,
    )
    return TaxOut(submitted=True, form_type=row.form_type)


@router.post("/methods", response_model=PayoutMethodOut, status_code=201)
def add_payout_method(
    payload: MethodIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_session),
) -> PayoutMethodOut:
    row = verification.add_method(db, user, payload.type, payload.label, payload.details)
    return PayoutMethodOut(**verification.masked_method(row))


@router.delete("/methods/{method_id}", status_code=204)
def remove_payout_method(
    method_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_session),
) -> None:
    verification.remove_method(db, user, method_id)


@router.post("/methods/{method_id}/default", response_model=list[PayoutMethodOut])
def set_default_payout_method(
    method_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_session),
) -> list[PayoutMethodOut]:
    """Returns the full masked list so the frontend refreshes in one call."""
    verification.set_default(db, user, method_id)
    return [PayoutMethodOut(**m) for m in verification.list_methods(db, user)]
