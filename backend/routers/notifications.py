"""In-app notification center — /api/notifications.

Recent notifications + unread count for the header bell, and mark-read.
Strictly caller-scoped: every query filters on the authenticated user's
id, so ids belonging to someone else are simply unmatched (no 404 oracle
for other users' notification ids).
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from database import get_session
from models.notification import Notification
from models.user import User
from services.auth import get_current_user

router = APIRouter(prefix="/api/notifications", tags=["notifications"])


class NotificationOut(BaseModel):
    id: int
    kind: str
    title: str
    body: str
    read_at: datetime | None
    created_at: datetime


class NotificationsOut(BaseModel):
    items: list[NotificationOut]
    unread: int


class ReadIn(BaseModel):
    # Omitted / null = mark ALL of the caller's unread notifications read.
    ids: list[int] | None = Field(default=None, max_length=500)


@router.get("", response_model=NotificationsOut)
def list_notifications(
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> NotificationsOut:
    """The caller's newest 50 notifications + their TOTAL unread count
    (the badge number — it counts past the 50 shown)."""
    items = (
        session.execute(
            select(Notification)
            .where(Notification.user_id == user.id)
            .order_by(Notification.created_at.desc(), Notification.id.desc())
            .limit(50)
        )
        .scalars()
        .all()
    )
    unread = session.execute(
        select(func.count())
        .select_from(Notification)
        .where(
            Notification.user_id == user.id,
            Notification.read_at.is_(None),
        )
    ).scalar_one()
    return NotificationsOut(
        items=[
            NotificationOut(
                id=n.id,
                kind=n.kind,
                title=n.title,
                body=n.body,
                read_at=n.read_at,
                created_at=n.created_at,
            )
            for n in items
        ],
        unread=int(unread),
    )


@router.post("/read", status_code=204)
def mark_read(
    payload: ReadIn | None = None,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> None:
    """Mark the listed notification ids read — or ALL unread when no ids
    are given. Scoped to the caller: someone else's ids simply don't
    match. Already-read rows keep their original read_at (idempotent)."""
    stmt = (
        update(Notification)
        .where(
            Notification.user_id == user.id,
            Notification.read_at.is_(None),
        )
        .values(read_at=datetime.now(timezone.utc))
        .execution_options(synchronize_session=False)
    )
    if payload is not None and payload.ids is not None:
        stmt = stmt.where(Notification.id.in_(payload.ids))
    session.execute(stmt)
    session.commit()
