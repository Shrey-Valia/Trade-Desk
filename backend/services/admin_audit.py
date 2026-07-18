"""Append-only AdminAction writer — the single audit chokepoint for the
/api/admin back office (workstream C2).

Every admin MUTATION calls `audit(...)` on the same session as the change it
describes; the CALLER owns the commit, so the audit row and the mutation land
atomically (or not at all). Rows are never updated or deleted —
models/admin_action.AdminAction is the append-only log the
GET /api/admin/actions endpoint reads when a dispute needs answering.
"""

from __future__ import annotations

import json

from sqlalchemy.orm import Session

from models.admin_action import AdminAction
from models.user import User


def audit(
    db: Session,
    actor: User,
    action: str,
    target_type: str,
    target_id: int | None,
    before: dict | None = None,
    after: dict | None = None,
    reason: str | None = None,
) -> AdminAction:
    """Stage one audit row on the caller's session. Does NOT commit.

    `before`/`after` are snapshots of just the fields the action changed;
    they are JSON-dumped here (default=str so datetimes serialize as ISO-ish
    strings instead of raising)."""
    row = AdminAction(
        actor_id=actor.id,
        action=action,
        target_type=target_type,
        target_id=target_id,
        before_json=json.dumps(before or {}, default=str),
        after_json=json.dumps(after or {}, default=str),
        reason=reason,
    )
    db.add(row)
    return row
