"""Authentication and Authorization Service for APEX Multi-Tenant Platform.

Implements secure password hashing with PBKDF2-HMAC-SHA256 (100,000 iterations)
and cryptographically signed bearer tokens with expiry and constant-time validation.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.entities import User


def hash_password(password: str) -> str:
    """Generate salted PBKDF2-HMAC-SHA256 hash."""
    salt = secrets.token_hex(16)
    key = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 100_000)
    return f"pbkdf2_sha256$100000${salt}${key.hex()}"


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify password against stored hash in constant time."""
    try:
        parts = hashed_password.split("$")
        if len(parts) != 4 or parts[0] != "pbkdf2_sha256":
            return False
        iterations = int(parts[1])
        salt = parts[2]
        expected_hex = parts[3]
        calculated = hashlib.pbkdf2_hmac("sha256", plain_password.encode("utf-8"), salt.encode("utf-8"), iterations)
        return hmac.compare_digest(calculated.hex(), expected_hex)
    except Exception:
        return False


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("utf-8").rstrip("=")


def _b64url_decode(data: str) -> bytes:
    padding = 4 - (len(data) % 4)
    if padding < 4:
        data += "=" * padding
    return base64.urlsafe_b64decode(data.encode("utf-8"))


def create_access_token(user: User, expires_delta_seconds: int | None = None) -> str:
    """Create a signed HMAC-SHA256 bearer token."""
    ttl = expires_delta_seconds or settings.token_expire_seconds
    now = int(time.time())
    header = {"alg": "HS256", "typ": "JWT"}
    payload = {
        "sub": user.id,
        "username": user.username,
        "email": user.email,
        "must_change_password": getattr(user, "must_change_password", False),
        "iat": now,
        "exp": now + ttl,
    }
    encoded_header = _b64url_encode(json.dumps(header, separators=(",", ":")).encode("utf-8"))
    encoded_payload = _b64url_encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    signing_input = f"{encoded_header}.{encoded_payload}".encode("utf-8")
    signature = hmac.new(settings.secret_key.encode("utf-8"), signing_input, hashlib.sha256).digest()
    encoded_signature = _b64url_encode(signature)
    return f"{encoded_header}.{encoded_payload}.{encoded_signature}"


def decode_access_token(token: str) -> dict[str, Any] | None:
    """Validate token signature and expiration, returning the payload or None."""
    try:
        parts = token.strip().split(".")
        if len(parts) != 3:
            return None
        encoded_header, encoded_payload, encoded_sig = parts
        signing_input = f"{encoded_header}.{encoded_payload}".encode("utf-8")
        expected_sig = hmac.new(settings.secret_key.encode("utf-8"), signing_input, hashlib.sha256).digest()
        provided_sig = _b64url_decode(encoded_sig)
        if not hmac.compare_digest(expected_sig, provided_sig):
            return None
        payload = json.loads(_b64url_decode(encoded_payload).decode("utf-8"))
        if payload.get("exp", 0) < int(time.time()):
            return None
        return payload
    except Exception:
        return None


def authenticate_user(session: Session, email_or_username: str, password: str) -> User | None:
    """Authenticate a user by email or username."""
    identifier = email_or_username.strip().lower()
    user = session.scalar(
        select(User).where((User.email.ilike(identifier)) | (User.username.ilike(identifier)))
    )
    if not user or not user.is_active:
        return None
    if not verify_password(password, user.hashed_password):
        return None
    return user


def register_user(
    session: Session,
    email: str,
    username: str,
    password: str,
    full_name: str | None = None,
    preferences: dict[str, Any] | None = None,
) -> User:
    """Register a new user account with strict uniqueness and password validation."""
    clean_email = email.strip().lower()
    clean_username = username.strip().lower()
    if not clean_email or "@" not in clean_email:
        raise ValueError("A valid email address is required.")
    if len(clean_username) < 3:
        raise ValueError("Username must be at least 3 characters long.")
    if len(password) < 8:
        raise ValueError("Password must be at least 8 characters long.")

    existing_email = session.scalar(select(User).where(User.email == clean_email))
    if existing_email:
        raise ValueError("An account with this email address already exists.")
    existing_user = session.scalar(select(User).where(User.username == clean_username))
    if existing_user:
        raise ValueError("This username is already taken.")

    user = User(
        email=clean_email,
        username=clean_username,
        hashed_password=hash_password(password),
        full_name=full_name.strip() if full_name else None,
        preferences=preferences or {"theme": "system", "notifications": {"critical_findings": True}},
        must_change_password=False,
        is_active=True,
    )
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


def get_or_create_default_admin(session: Session) -> User:
    """Ensure a default system administrator exists to own legacy unassigned projects.
    
    If provisioned using the default fallback password in development, marks must_change_password=True.
    In production mode, settings.validate_production_security() ensures strong env credentials.
    Never exposes passwords in logs.
    """
    admin_username = settings.initial_admin_username or "apex_admin"
    admin_email = settings.initial_admin_email or "admin@apex.local"
    admin = session.scalar(select(User).where(User.username == admin_username))

    using_default_fallback = False
    if settings.initial_admin_password:
        initial_pw = settings.initial_admin_password
    else:
        initial_pw = "ApexPassword123!"
        using_default_fallback = True

    if not admin:
        admin = User(
            email=admin_email,
            username=admin_username,
            hashed_password=hash_password(initial_pw),
            full_name="Apex Administrator",
            preferences={"theme": "purple_glass", "notifications": {"all": True}},
            must_change_password=using_default_fallback,
            is_active=True,
        )
        session.add(admin)
        session.commit()
        session.refresh(admin)
    else:
        # Check if the existing admin is still using the known default password
        if verify_password("ApexPassword123!", admin.hashed_password):
            admin.must_change_password = True
            session.commit()
            session.refresh(admin)

    return admin
