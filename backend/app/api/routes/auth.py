"""Authentication Endpoints for APEX Multi-Tenant Engineering Intelligence Platform."""
from __future__ import annotations

from typing import Any
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user, get_db
from app.core.config import settings
from app.models.entities import ReviewedProject, User
from app.services.auth_service import (
    authenticate_user,
    create_access_token,
    hash_password,
    register_user,
    verify_password,
)
from app.services.rate_limiter import auth_rate_limiter, get_client_ip
from app.services.ticket_service import sse_ticket_store

router = APIRouter(prefix="/auth")


class RegisterRequest(BaseModel):
    email: str = Field(..., min_length=5, max_length=255)
    username: str = Field(..., min_length=3, max_length=50)
    password: str = Field(..., min_length=8, max_length=128)
    full_name: str | None = Field(None, max_length=150)
    preferences: dict[str, Any] | None = None


class LoginRequest(BaseModel):
    email_or_username: str = Field(..., min_length=1)
    password: str = Field(..., min_length=1)


class ProfileUpdateRequest(BaseModel):
    full_name: str | None = None
    email: str | None = Field(None, min_length=5, max_length=255)
    preferences: dict[str, Any] | None = None


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str = Field(..., min_length=8)


class SSETicketRequest(BaseModel):
    project_id: int = Field(..., description="Project ID to authorize SSE stream for")


def _serialize_user(user: User) -> dict[str, Any]:
    return {
        "id": user.id,
        "email": user.email,
        "username": user.username,
        "full_name": user.full_name,
        "preferences": user.preferences or {},
        "must_change_password": getattr(user, "must_change_password", False),
        "created_at": user.created_at.isoformat() if user.created_at else None,
    }


@router.post("/register", status_code=status.HTTP_201_CREATED, summary="Register a new user account")
def register(request: Request, body: RegisterRequest, session: Session = Depends(get_db)):
    client_ip = get_client_ip(request)
    reg_key = f"register:ip:{client_ip}"
    allowed_reg, retry_after = auth_rate_limiter.check_rate_limit(
        reg_key, max_requests=settings.rate_limit_register_per_minute, window_seconds=60
    )
    if not allowed_reg:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Too many registration attempts. Please wait {retry_after} seconds before retrying.",
            headers={"Retry-After": str(retry_after)},
        )

    try:
        user = register_user(
            session=session,
            email=body.email,
            username=body.username,
            password=body.password,
            full_name=body.full_name,
            preferences=body.preferences,
        )
        auth_rate_limiter.record_attempt(reg_key)
        token = create_access_token(user)
        return {
            "token": token,
            "token_type": "Bearer",
            "user": _serialize_user(user),
        }
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/login", summary="Sign in to your private workspace")
def login(request: Request, body: LoginRequest, session: Session = Depends(get_db)):
    client_ip = get_client_ip(request)
    ip_key = f"login:ip:{client_ip}"
    allowed_ip, retry_after_ip = auth_rate_limiter.check_rate_limit(
        ip_key, max_requests=settings.rate_limit_ip_per_minute, window_seconds=60
    )
    if not allowed_ip:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Too many login attempts from this network. Please wait {retry_after_ip} seconds before retrying.",
            headers={"Retry-After": str(retry_after_ip)},
        )

    identifier = body.email_or_username.strip().lower()
    user_key = f"login:user:{identifier}"
    allowed_user, retry_after_user = auth_rate_limiter.check_rate_limit(
        user_key, max_requests=settings.rate_limit_login_per_minute, window_seconds=60
    )
    if not allowed_user:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Too many failed login attempts for this account. Please wait {retry_after_user} seconds before retrying.",
            headers={"Retry-After": str(retry_after_user)},
        )

    user = authenticate_user(session, body.email_or_username, body.password)
    if not user:
        auth_rate_limiter.record_attempt(ip_key)
        auth_rate_limiter.record_attempt(user_key)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email/username or password.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Authentication succeeded; clear failed attempt counter for this identifier
    auth_rate_limiter.clear_attempts(user_key)

    token = create_access_token(user)
    return {
        "token": token,
        "token_type": "Bearer",
        "must_change_password": getattr(user, "must_change_password", False),
        "user": _serialize_user(user),
    }


@router.post("/sse-ticket", summary="Generate a single-use short-lived SSE connection ticket")
def create_sse_ticket(
    body: SSETicketRequest,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
):
    """Generate a 60-second single-use ticket for establishing an SSE connection.
    
    Verifies project access and binds the ticket to the current user and project.
    Prevents token exposure in URL query parameters.
    """
    project = session.get(ReviewedProject, body.project_id)
    if not project or (project.owner_id is not None and project.owner_id != current_user.id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found or you do not have permission to access it.",
        )

    ticket = sse_ticket_store.create_ticket(
        user_id=current_user.id,
        project_id=body.project_id,
    )
    return {
        "ticket": ticket,
        "project_id": body.project_id,
        "expires_in": sse_ticket_store.DEFAULT_TTL_SECONDS,
    }


@router.get("/me", summary="Get profile details of the currently authenticated user")
def get_me(current_user: User = Depends(get_current_user)):
    return {
        "user": _serialize_user(current_user),
    }


@router.patch("/profile", summary="Update user profile settings and preferences")
def update_profile(
    body: ProfileUpdateRequest,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
):
    if body.full_name is not None:
        current_user.full_name = body.full_name.strip() or None
    if body.email is not None and body.email.lower() != current_user.email:
        clean_email = body.email.lower()
        from sqlalchemy import select
        existing = session.scalar(select(User).where(User.email == clean_email, User.id != current_user.id))
        if existing:
            raise HTTPException(status_code=400, detail="This email address is already in use by another account.")
        current_user.email = clean_email
    if body.preferences is not None:
        merged = dict(current_user.preferences or {})
        merged.update(body.preferences)
        current_user.preferences = merged
    session.commit()
    session.refresh(current_user)
    return {"user": _serialize_user(current_user)}


@router.post("/change-password", summary="Change account password")
def change_password(
    body: ChangePasswordRequest,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
):
    if not verify_password(body.current_password, current_user.hashed_password):
        raise HTTPException(status_code=400, detail="Current password does not match.")
    if len(body.new_password) < 8:
        raise HTTPException(status_code=400, detail="New password must be at least 8 characters long.")
    current_user.hashed_password = hash_password(body.new_password)
    current_user.must_change_password = False
    session.commit()
    return {
        "status": "ok",
        "message": "Password changed successfully.",
        "must_change_password": False,
    }
