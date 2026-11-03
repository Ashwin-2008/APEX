"""User Notification and Project Activity Event Service for APEX."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import ActivityEvent, Notification, ReviewedProject, User
from app.services.project_monitor import event_bus


def create_notification(
    session: Session,
    user_id: int,
    project_id: int | None,
    notif_type: str,
    title: str,
    message: str,
    data: dict[str, Any] | None = None,
) -> Notification:
    """Persist a notification for a user and emit an authenticated live SSE event."""
    notif = Notification(
        user_id=user_id,
        project_id=project_id,
        type=notif_type,
        title=title,
        message=message,
        data=data or {},
        seen=False,
    )
    session.add(notif)
    session.commit()
    session.refresh(notif)

    # Emit real-time SSE event to the project's event bus if tied to a project
    if project_id:
        event_bus.emit(
            project_id,
            {
                "type": "notification.created",
                "notification_id": notif.id,
                "user_id": user_id,
                "project_id": project_id,
                "notification_type": notif_type,
                "title": title,
                "message": message,
                "data": data or {},
                "created_at": notif.created_at.isoformat() if notif.created_at else None,
            },
        )

    return notif


def list_user_notifications(
    session: Session,
    user_id: int,
    project_id: int | None = None,
    seen: bool | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """List notifications for the authenticated user with optional project or seen filters."""
    query = select(Notification).where(Notification.user_id == user_id)
    if project_id is not None:
        query = query.where(Notification.project_id == project_id)
    if seen is not None:
        query = query.where(Notification.seen == seen)
    query = query.order_by(Notification.created_at.desc()).limit(limit)

    results = session.scalars(query).all()
    return [
        {
            "id": n.id,
            "user_id": n.user_id,
            "project_id": n.project_id,
            "type": n.type,
            "title": n.title,
            "message": n.message,
            "data": n.data or {},
            "seen": n.seen,
            "created_at": n.created_at.isoformat() if n.created_at else None,
        }
        for n in results
    ]


def mark_notification_read(session: Session, user_id: int, notification_id: int) -> bool:
    """Mark a specific notification as seen."""
    notif = session.scalar(
        select(Notification).where(Notification.id == notification_id, Notification.user_id == user_id)
    )
    if not notif:
        return False
    notif.seen = True
    session.commit()
    return True


def mark_all_notifications_read(session: Session, user_id: int, project_id: int | None = None) -> int:
    """Mark all notifications as seen for a user."""
    query = select(Notification).where(Notification.user_id == user_id, Notification.seen == False)
    if project_id is not None:
        query = query.where(Notification.project_id == project_id)
    notifs = session.scalars(query).all()
    count = len(notifs)
    for n in notifs:
        n.seen = True
    session.commit()
    return count


def record_activity_event(
    session: Session,
    project_id: int,
    event_type: str,
    title: str,
    description: str,
    metadata: dict[str, Any] | None = None,
) -> ActivityEvent:
    """Persist an audit/activity event for a project."""
    activity = ActivityEvent(
        project_id=project_id,
        event_type=event_type,
        title=title,
        description=description,
        event_metadata=metadata or {},
    )
    session.add(activity)
    session.commit()
    session.refresh(activity)

    event_bus.emit(
        project_id,
        {
            "type": "activity.logged",
            "project_id": project_id,
            "event_type": event_type,
            "title": title,
            "description": description,
            "created_at": activity.created_at.isoformat() if activity.created_at else None,
        },
    )
    return activity


def list_project_activity(session: Session, project_id: int, limit: int = 50) -> list[dict[str, Any]]:
    """Return chronological activity timeline for a project."""
    query = (
        select(ActivityEvent)
        .where(ActivityEvent.project_id == project_id)
        .order_by(ActivityEvent.created_at.desc())
        .limit(limit)
    )
    events = session.scalars(query).all()
    return [
        {
            "id": e.id,
            "project_id": e.project_id,
            "event_type": e.event_type,
            "title": e.title,
            "description": e.description,
            "metadata": e.event_metadata or {},
            "created_at": e.created_at.isoformat() if e.created_at else None,
        }
        for e in events
    ]

