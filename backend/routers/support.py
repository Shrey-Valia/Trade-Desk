"""Support tickets — /api/support/*.

Trader contact form + own-ticket list; the admin queue lives here too
(require_admin per-endpoint). Ticket creation auto-attaches the user's
active-combine context so the reviewer doesn't hunt for it. Admin updates
are audit-logged (AdminAction) and a set/changed admin_note pushes an
in-app Notification to the ticket's owner. See
docs/P0_IMPLEMENTATION_PLAN_2026-07-14.md (workstream B1) for the contract.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from database import get_session
from models.admin_action import AdminAction
from models.combine import Combine
from models.notification import Notification
from models.support_ticket import TICKET_CATEGORIES, SupportTicket
from models.user import User
from services.auth import get_current_user, require_admin

router = APIRouter(prefix="/api/support", tags=["support"])

# First N characters of an admin note that fit the notification body
# (Notification.body is a String(500); 200 keeps the bell preview short).
_NOTE_PREVIEW_CHARS = 200


# -- schemas -------------------------------------------------------------


class TicketCreate(BaseModel):
    category: str
    subject: str = Field(min_length=1, max_length=160)
    body: str = Field(min_length=1, max_length=5000)

    @field_validator("category")
    @classmethod
    def _known_category(cls, value: str) -> str:
        if value not in TICKET_CATEGORIES:
            raise ValueError(
                f"category must be one of {', '.join(TICKET_CATEGORIES)}"
            )
        return value


class TicketOut(BaseModel):
    id: int
    category: str
    subject: str
    body: str
    # Parsed context_json: {"combine_id", "tier", "status"} or {}.
    context: dict
    status: str
    admin_note: str | None
    created_at: datetime
    updated_at: datetime


class TicketsResponse(BaseModel):
    tickets: list[TicketOut]


class AdminTicketOut(TicketOut):
    user_id: int
    user_email: str


class AdminTicketsResponse(BaseModel):
    tickets: list[AdminTicketOut]
    total: int
    page: int


class AdminTicketUpdate(BaseModel):
    status: Literal["open", "replied", "closed"] | None = None
    admin_note: str | None = Field(default=None, max_length=5000)


# -- helpers -------------------------------------------------------------


def _active_combine_context(db: Session, user: User) -> dict:
    """The user's active combine as reviewer context — {} when they have
    none. Same ownership/archived semantics as services.auth
    .get_active_combine, minus the exception (a combine-less user can
    still file a billing/bug ticket)."""
    if user.active_combine_id is None:
        return {}
    combine = db.execute(
        select(Combine).where(
            Combine.id == user.active_combine_id,
            Combine.user_id == user.id,
            Combine.status != "archived",
        )
    ).scalar_one_or_none()
    if combine is None:
        return {}
    return {"combine_id": combine.id, "tier": combine.tier, "status": combine.status}


def _parse_context(raw: str | None) -> dict:
    try:
        parsed = json.loads(raw or "{}")
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _to_out(ticket: SupportTicket) -> TicketOut:
    return TicketOut(
        id=ticket.id,
        category=ticket.category,
        subject=ticket.subject,
        body=ticket.body,
        context=_parse_context(ticket.context_json),
        status=ticket.status,
        admin_note=ticket.admin_note,
        created_at=ticket.created_at,
        updated_at=ticket.updated_at,
    )


def _to_admin_out(ticket: SupportTicket, user_email: str) -> AdminTicketOut:
    return AdminTicketOut(
        **_to_out(ticket).model_dump(),
        user_id=ticket.user_id,
        user_email=user_email,
    )


# -- trader endpoints ------------------------------------------------------


@router.post("/tickets", response_model=TicketOut, status_code=201)
def create_ticket(
    payload: TicketCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_session),
) -> TicketOut:
    ticket = SupportTicket(
        user_id=user.id,
        category=payload.category,
        subject=payload.subject,
        body=payload.body,
        context_json=json.dumps(_active_combine_context(db, user)),
    )
    db.add(ticket)
    db.commit()
    db.refresh(ticket)
    return _to_out(ticket)


@router.get("/tickets", response_model=TicketsResponse)
def list_own_tickets(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_session),
) -> TicketsResponse:
    rows = (
        db.execute(
            select(SupportTicket)
            .where(SupportTicket.user_id == user.id)
            .order_by(SupportTicket.created_at.desc(), SupportTicket.id.desc())
        )
        .scalars()
        .all()
    )
    return TicketsResponse(tickets=[_to_out(t) for t in rows])


# -- admin queue -----------------------------------------------------------


@router.get("/admin/tickets", response_model=AdminTicketsResponse)
def admin_list_tickets(
    status: Literal["open", "replied", "closed"] | None = None,
    q: str = "",
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    admin: User = Depends(require_admin),
    db: Session = Depends(get_session),
) -> AdminTicketsResponse:
    """Support queue, newest first, PAGINATED (mirrors /admin/users) so the
    payload stays bounded as tickets accumulate. Optional status filter plus a
    case-insensitive search over the ticket subject and the owner's email."""
    stmt = select(SupportTicket, User.email).join(
        User, User.id == SupportTicket.user_id
    )
    if status is not None:
        stmt = stmt.where(SupportTicket.status == status)
    needle = q.strip()
    if needle:
        like = f"%{needle}%"
        stmt = stmt.where(
            or_(User.email.ilike(like), SupportTicket.subject.ilike(like))
        )
    total = db.execute(
        select(func.count()).select_from(stmt.subquery())
    ).scalar_one()
    rows = db.execute(
        stmt.order_by(SupportTicket.created_at.desc(), SupportTicket.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return AdminTicketsResponse(
        tickets=[_to_admin_out(t, email) for t, email in rows],
        total=int(total),
        page=page,
    )


@router.patch("/admin/tickets/{ticket_id}", response_model=AdminTicketOut)
def admin_update_ticket(
    ticket_id: int,
    payload: AdminTicketUpdate,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_session),
) -> AdminTicketOut:
    """Work a ticket: set status and/or the admin reply note.

    Every ACTUAL change writes an append-only AdminAction row (before/after
    of just the changed fields); a set/changed non-empty admin_note also
    pushes a "support_reply" Notification to the ticket's owner. A no-op
    PATCH (same values) changes nothing and audits nothing."""
    if payload.status is None and payload.admin_note is None:
        raise HTTPException(400, "nothing to update — provide status or admin_note")
    ticket = db.get(SupportTicket, ticket_id)
    if ticket is None:
        raise HTTPException(404, f"ticket {ticket_id} not found")

    before: dict = {}
    after: dict = {}
    if payload.status is not None and payload.status != ticket.status:
        before["status"] = ticket.status
        after["status"] = payload.status
        ticket.status = payload.status
    note_changed = (
        payload.admin_note is not None and payload.admin_note != ticket.admin_note
    )
    if note_changed:
        before["admin_note"] = ticket.admin_note
        after["admin_note"] = payload.admin_note
        ticket.admin_note = payload.admin_note

    if after:
        db.add(
            AdminAction(
                actor_id=admin.id,
                action="support.update",
                target_type="support_ticket",
                target_id=ticket.id,
                before_json=json.dumps(before),
                after_json=json.dumps(after),
            )
        )
    if note_changed and payload.admin_note:
        db.add(
            Notification(
                user_id=ticket.user_id,
                kind="support_reply",
                title="Support replied to your ticket",
                body=payload.admin_note[:_NOTE_PREVIEW_CHARS],
            )
        )
    db.commit()
    db.refresh(ticket)
    owner = db.get(User, ticket.user_id)
    return _to_admin_out(ticket, owner.email if owner else "")
