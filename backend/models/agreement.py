"""Versioned legal-document acceptances — the consent audit trail.

One append-only row per (user, document, version) acceptance: ToS/privacy/
refund/risk-disclosure checkboxes at signup and purchase, and the typed-name
e-sign of the funded-trader agreement at account activation. The row is the
firm's proof of agreement — payout denials and terminations are enforceable
only against terms the trader demonstrably accepted.

`doc_key` and versions are owned by services/legal.py (LEGAL_DOC_VERSIONS);
bumping a version there makes acceptance stale and the frontend re-prompts.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from database import Base, UTCDateTime


class AgreementAcceptance(Base):
    __tablename__ = "agreement_acceptances"
    __table_args__ = (
        # The gate query: has user X accepted doc Y at version Z?
        Index("ix_agreement_acceptances_user_doc", "user_id", "doc_key"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=False
    )
    # "tos" | "privacy" | "refund" | "risk" | "funded_agreement"
    doc_key: Mapped[str] = mapped_column(String(32), nullable=False)
    doc_version: Mapped[int] = mapped_column(Integer, nullable=False)
    # Typed full name for e-signed docs (funded_agreement); NULL for checkbox
    # acceptances.
    signature_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    # Client IP at acceptance time (dispute evidence). Stored as text — may be
    # IPv6 or a proxy chain head.
    ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    accepted_at: Mapped[datetime] = mapped_column(
        UTCDateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
