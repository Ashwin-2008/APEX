"""Notification API Endpoints for APEX Multi-Tenant Engineering Intelligence Platform."""
from __future__ import annotations

from typing import Any
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user, get_db
from app.models.entities import Notification, User
from app.services.notification_service import (
    list_user_notifications,
    mark_all_notifications_read,
    mark_notification_read,
)

router = APIRouter(prefix="/notifications")


@router.get("", summary="List notifications for the authenticated user")
def get_notifications(
    project_id: int | None = None,
    seen: bool | None = None,
    limit: int = 50,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
):
    return list_user_notifications(
        session=session,
        user_id=current_user.id,
        project_id=project_id,
        seen=seen,
        limit=limit,
    )


@router.get("/unread-count", summary="Get unread notification count for the application header bell")
def get_unread_count(
    project_id: int | None = None,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
):
    query = select(func.count(Notification.id)).where(
        Notification.user_id == current_user.id,
        Notification.seen == False,
    )
    if project_id is not None:
        query = query.where(Notification.project_id == project_id)
    count = session.scalar(query) or 0
    return {"unread_count": count}


@router.post("/{notification_id}/read", summary="Mark a specific notification as read")
def mark_read(
    notification_id: int,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
):
    success = mark_notification_read(session, current_user.id, notification_id)
    if not success:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Notification not found")
    return {"status": "ok", "notification_id": notification_id, "seen": True}


@router.post("/mark-all-read", summary="Mark all notifications as read")
def mark_all_read(
    project_id: int | None = None,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
):
    count = mark_all_notifications_read(session, current_user.id, project_id)
    return {"status": "ok", "marked_read_count": count}

