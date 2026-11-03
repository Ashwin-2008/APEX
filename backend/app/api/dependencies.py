from __future__ import annotations

from typing import Generator
from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.entities import ReviewedProject, User
from app.services.auth_service import decode_access_token


def get_db(request: Request) -> Generator[Session, None, None]:
    """Yield a database session from the application state connection pool."""
    session = request.app.state.SessionLocal()
    try:
        yield session
    finally:
        session.close()


def get_ampa_service(request: Request):
    """Retrieve the trained AMPA service from application state."""
    service = request.app.state.ampa_service
    if service is None or not service.available:
        from app.services.errors import ModelUnavailable
        raise ModelUnavailable("Trained AMPA model unavailable; configure MISTIQ_AMPA_MODEL_PATH")
    return service


def get_current_user(
    request: Request,
    session: Session = Depends(get_db),
) -> User:
    """Extract and validate the authenticated user from the Authorization header or query parameter.

    Accepts 'Authorization: Bearer <token>' or '?token=<token>' (for backward compatibility in dev).
    Enforces strict user identity on all protected routes.
    Rejects long-lived tokens in query parameters in production mode (requires POST /api/auth/sse-ticket).
    Enforces mandatory password change for users with default credentials.
    """
    token: str | None = None
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        token = auth_header[7:].strip()
    elif "token" in request.query_params:
        if settings.environment == "production":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Bearer tokens in URL parameters are forbidden in production. Use POST /api/auth/sse-ticket to obtain a short-lived ticket.",
            )
        token = request.query_params.get("token")

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required. Please sign in to access this workspace.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    payload = decode_access_token(token)
    if not payload or "sub" not in payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired session token. Please sign in again.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id = payload["sub"]
    user = session.get(User, user_id)
    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User account is deactivated or no longer exists.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Enforce mandatory password change if flagged on default credentials
    if getattr(user, "must_change_password", False):
        path = request.url.path
        allowed_paths = {
            "/api/auth/change-password",
            "/api/auth/me",
            "/api/auth/logout",
            "/api/auth/profile",
        }
        if path not in allowed_paths and not path.endswith("/change-password"):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Mandatory password change required. You must change your default password via POST /api/auth/change-password before accessing platform features.",
            )

    return user


def get_optional_current_user(
    request: Request,
    session: Session = Depends(get_db),
) -> User | None:
    """Optionally extract the current user; returns None if unauthenticated."""
    try:
        return get_current_user(request, session)
    except HTTPException:
        return None


def get_authorized_project(
    project_id: int,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> ReviewedProject:
    """Enforce strict tenant isolation: verify that the requested project exists and belongs to the current user.

    If the project belongs to another user, returns a non-disclosing 404 to prevent IDOR and enumeration.
    """
    project = session.get(ReviewedProject, project_id)
    if not project or project.owner_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found or you do not have permission to access it.",
        )
    return project
