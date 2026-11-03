"""Production Security Hardening Test Suite for APEX 2.0.

Verifies:
1. Default Administrator Security & Mandatory Password Change
2. Environment-based Admin Provisioning & Production Startup Validation
3. SSE Authentication Hardening (POST /api/auth/sse-ticket, replay prevention, expiry, cross-user/cross-project rejection)
4. Dynamic Runner Isolation (Docker sandbox parameters, production rejection of host execution)
5. Authentication Rate Limiting (login and registration abuse prevention with HTTP 429 and Retry-After)
6. Multi-Tenant Isolation Preservation
"""
from __future__ import annotations

import os
import time
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import settings
from app.db.base import Base
from app.db.session import migrate_sqlite_schema
from app.main import create_app
from app.models.entities import ReviewedProject, User
from app.services.analyzers.base import AnalyzerStatus
from app.services.analyzers.dynamic_analyzer import (
    build_docker_sandbox_command,
    run_dynamic_analysis,
)
from app.services.auth_service import (
    create_access_token,
    get_or_create_default_admin,
    hash_password,
    register_user,
    verify_password,
)
from app.services.rate_limiter import auth_rate_limiter
from app.services.ticket_service import sse_ticket_store


@pytest.fixture
def security_test_env():
    """Create a pristine in-memory test database and application instance."""
    auth_rate_limiter.reset_all()
    sse_ticket_store.reset_all()

    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    migrate_sqlite_schema(engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    app = create_app(database_engine=engine)
    app.state.SessionLocal = session_factory

    with TestClient(app) as client:
        yield client, session_factory, engine


# ==============================================================================
# 1. DEFAULT ADMINISTRATOR SECURITY & MANDATORY PASSWORD CHANGE
# ==============================================================================

def test_default_admin_mandatory_password_change_flow(security_test_env):
    """Test that default credentials force a password change and restrict actions until changed."""
    client, session_factory, _ = security_test_env

    # 1. Provision default admin with fallback password
    with session_factory() as session:
        admin = get_or_create_default_admin(session)
        assert admin.must_change_password is True

    # 2. Login with default credentials
    login_resp = client.post(
        "/api/auth/login",
        json={"email_or_username": "apex_admin", "password": "ApexPassword123!"},
    )
    assert login_resp.status_code == 200
    login_data = login_resp.json()
    assert login_data["must_change_password"] is True
    admin_token = login_data["token"]
    headers = {"Authorization": f"Bearer {admin_token}"}

    # 3. Attempt to access protected project endpoint before password change -> 403 Forbidden
    proj_resp = client.get("/api/projects", headers=headers)
    assert proj_resp.status_code == 403
    assert "Mandatory password change required" in proj_resp.json()["detail"]

    # 4. User profile / me is allowed so the UI can prompt the user
    me_resp = client.get("/api/auth/me", headers=headers)
    assert me_resp.status_code == 200
    assert me_resp.json()["user"]["must_change_password"] is True

    # 5. Execute password change via POST /api/auth/change-password
    change_resp = client.post(
        "/api/auth/change-password",
        headers=headers,
        json={"current_password": "ApexPassword123!", "new_password": "SecureAdminPassword2026!"},
    )
    assert change_resp.status_code == 200
    assert change_resp.json()["must_change_password"] is False

    # 6. Verify password change took effect in database
    with session_factory() as session:
        refreshed_admin = session.get(User, admin.id)
        assert refreshed_admin.must_change_password is False
        assert verify_password("SecureAdminPassword2026!", refreshed_admin.hashed_password)

    # 7. Login again with new password and verify unrestricted access
    new_login = client.post(
        "/api/auth/login",
        json={"email_or_username": "apex_admin", "password": "SecureAdminPassword2026!"},
    )
    assert new_login.status_code == 200
    assert new_login.json()["must_change_password"] is False
    new_headers = {"Authorization": f"Bearer {new_login.json()['token']}"}

    unblocked_resp = client.get("/api/projects", headers=new_headers)
    assert unblocked_resp.status_code == 200


def test_production_startup_validation():
    """Verify that production startup rejects weak/default configurations."""
    # Test 1: Production with default secret key
    with patch.object(settings, "environment", "production"):
        with patch.object(settings, "secret_key", "apex_secret_key_change_in_production_2026"):
            with patch.object(settings, "initial_admin_password", "SuperSecurePassword123!"):
                with patch.object(settings, "sandbox_mode", "docker"):
                    with pytest.raises(RuntimeError, match="SECRET_KEY must be set to a cryptographically strong string"):
                        settings.validate_production_security()

    # Test 2: Production with missing initial admin password
    with patch.object(settings, "environment", "production"):
        with patch.object(settings, "secret_key", "a_very_secure_random_key_of_at_least_32_characters_length"):
            with patch.object(settings, "initial_admin_password", ""):
                with patch.object(settings, "sandbox_mode", "docker"):
                    with pytest.raises(RuntimeError, match="APEX_INITIAL_ADMIN_PASSWORD must be explicitly provided"):
                        settings.validate_production_security()

    # Test 3: Production with default well-known password
    with patch.object(settings, "environment", "production"):
        with patch.object(settings, "secret_key", "a_very_secure_random_key_of_at_least_32_characters_length"):
            with patch.object(settings, "initial_admin_password", "ApexPassword123!"):
                with patch.object(settings, "sandbox_mode", "docker"):
                    with pytest.raises(RuntimeError, match="cannot be set to a default or weak password"):
                        settings.validate_production_security()

    # Test 4: Production with local_dev sandbox mode
    with patch.object(settings, "environment", "production"):
        with patch.object(settings, "secret_key", "a_very_secure_random_key_of_at_least_32_characters_length"):
            with patch.object(settings, "initial_admin_password", "ValidSecureProdPassword2026!"):
                with patch.object(settings, "sandbox_mode", "local_dev"):
                    with pytest.raises(RuntimeError, match="APEX_SANDBOX_MODE must be set to 'docker' in production"):
                        settings.validate_production_security()


# ==============================================================================
# 2. SSE AUTHENTICATION HARDENING & SINGLE-USE TICKETS
# ==============================================================================

def test_sse_ticket_generation_and_consumption(security_test_env):
    """Test generating, consuming, and preventing replay of single-use SSE tickets."""
    client, session_factory, _ = security_test_env

    with session_factory() as session:
        user = register_user(session, "tenant_a@example.com", "tenant_a", "StrongPassword123!")
        project = ReviewedProject(
            name="Project Alpha",
            repository_path="c:/repos/alpha",
            owner_id=user.id,
            source_type="local",
        )
        session.add(project)
        session.commit()
        session.refresh(project)
        project_id = project.id
        token = create_access_token(user)

    headers = {"Authorization": f"Bearer {token}"}

    # 1. Request SSE Ticket via POST /api/auth/sse-ticket
    ticket_resp = client.post(
        "/api/auth/sse-ticket",
        headers=headers,
        json={"project_id": project_id},
    )
    assert ticket_resp.status_code == 200
    ticket_data = ticket_resp.json()
    assert "ticket" in ticket_data
    assert ticket_data["project_id"] == project_id
    assert ticket_data["expires_in"] == 60
    ticket = ticket_data["ticket"]

    # 2. Consume ticket (single-use validation)
    consumed = sse_ticket_store.validate_and_consume(ticket, expected_project_id=project_id)
    assert consumed is not None
    assert consumed["user_id"] == user.id
    assert consumed["project_id"] == project_id

    # 3. Ticket Replay Prevention: Attempt to connect again with the consumed ticket -> 401 Unauthorized
    replay_resp = client.get(f"/api/project-reviews/{project_id}/events?ticket={ticket}")
    assert replay_resp.status_code == 401
    assert "Invalid, expired, or replayed SSE ticket" in replay_resp.json()["detail"]


def test_sse_ticket_cross_user_and_cross_project_rejection(security_test_env):
    """Verify that tickets cannot be used across projects or by unauthorized tenants."""
    client, session_factory, _ = security_test_env

    with session_factory() as session:
        user_a = register_user(session, "user_a@example.com", "user_a", "StrongPassword123!")
        user_b = register_user(session, "user_b@example.com", "user_b", "StrongPassword123!")

        project_a = ReviewedProject(
            name="Project A",
            repository_path="c:/repos/a",
            owner_id=user_a.id,
            source_type="local",
        )
        project_b = ReviewedProject(
            name="Project B",
            repository_path="c:/repos/b",
            owner_id=user_b.id,
            source_type="local",
        )
        session.add_all([project_a, project_b])
        session.commit()
        session.refresh(project_a)
        session.refresh(project_b)
        id_a, id_b = project_a.id, project_b.id
        token_a = create_access_token(user_a)
        token_b = create_access_token(user_b)

    # 1. User B tries to request a ticket for User A's project -> 404 Not Found (non-disclosing)
    idor_ticket = client.post(
        "/api/auth/sse-ticket",
        headers={"Authorization": f"Bearer {token_b}"},
        json={"project_id": id_a},
    )
    assert idor_ticket.status_code == 404

    # 2. User A gets a valid ticket for Project A
    ticket_a_resp = client.post(
        "/api/auth/sse-ticket",
        headers={"Authorization": f"Bearer {token_a}"},
        json={"project_id": id_a},
    )
    ticket_a = ticket_a_resp.json()["ticket"]

    # 3. Cross-project ticket usage: Ticket A attempted on Project B stream -> 401 Unauthorized
    cross_proj = client.get(f"/api/project-reviews/{id_b}/events?ticket={ticket_a}")
    assert cross_proj.status_code == 401

    # 4. Production query-token rejection
    with patch.object(settings, "environment", "production"):
        prod_token_query = client.get(f"/api/project-reviews/{id_a}/events?token={token_a}")
        assert prod_token_query.status_code == 400
        assert "Bearer tokens in URL parameters are forbidden in production" in prod_token_query.json()["detail"]


def test_sse_ticket_expiration(security_test_env):
    """Verify that expired tickets are rejected."""
    client, session_factory, _ = security_test_env

    with session_factory() as session:
        user = register_user(session, "exp_user@example.com", "exp_user", "StrongPassword123!")
        project = ReviewedProject(name="Exp Project", repository_path="c:/repos/exp", owner_id=user.id)
        session.add(project)
        session.commit()
        session.refresh(project)
        p_id = project.id
        token = create_access_token(user)

    ticket_resp = client.post(
        "/api/auth/sse-ticket",
        headers={"Authorization": f"Bearer {token}"},
        json={"project_id": p_id},
    )
    ticket = ticket_resp.json()["ticket"]

    # Artificially expire the ticket in the store
    sse_ticket_store._tickets[ticket]["expires_at"] = time.time() - 5

    res = client.get(f"/api/project-reviews/{p_id}/events?ticket={ticket}")
    assert res.status_code == 401
    assert "Invalid, expired, or replayed SSE ticket" in res.json()["detail"]


# ==============================================================================
# 3. DYNAMIC RUNNER ISOLATION & RESOURCE RESTRICTIONS
# ==============================================================================

def test_dynamic_runner_docker_command_construction():
    """Verify that the Docker command enforces full non-root, read-only, and resource limits."""
    cmd = build_docker_sandbox_command(
        root=Path("/safe/repo"),
        command=["pytest", "-q"],
        image="python:3.11-slim",
    )
    assert "--rm" in cmd
    assert "--network" in cmd and cmd[cmd.index("--network") + 1] == "none"
    assert "--user" in cmd and cmd[cmd.index("--user") + 1] == "1000:1000"
    assert "--memory" in cmd and cmd[cmd.index("--memory") + 1] == "512m"
    assert "--cpus" in cmd and cmd[cmd.index("--cpus") + 1] == "1.0"
    assert "--pids-limit" in cmd and cmd[cmd.index("--pids-limit") + 1] == "50"
    # Read-only mount check
    ro_mounts = [arg for arg in cmd if ":ro" in arg]
    assert len(ro_mounts) > 0
    # No docker socket exposed
    assert not any("docker.sock" in arg for arg in cmd)


def test_dynamic_runner_production_rejection_of_host_execution(tmp_path):
    """Verify that in production mode, unsafe host execution is rejected and no fallback occurs."""
    with patch.object(settings, "environment", "production"):
        with patch.object(settings, "sandbox_mode", "local_dev"):
            out = run_dynamic_analysis(root_dir=tmp_path, enabled=True)
            assert out.status == AnalyzerStatus.FAILED
            assert "Host execution is forbidden in production environment." in (out.error_message or "")
            assert any(f.rule_id == "DYN-PRODUCTION-POLICY-VIOLATION" for f in out.findings)


def test_dynamic_runner_docker_unavailable_fails_fast_without_host_fallback(tmp_path):
    """Verify that when Docker daemon is down, production mode does not fall back to host."""
    with patch.object(settings, "environment", "production"):
        with patch.object(settings, "sandbox_mode", "docker"):
            with patch("app.services.analyzers.dynamic_analyzer.is_docker_available", return_value=False):
                out = run_dynamic_analysis(root_dir=tmp_path, enabled=True)
                assert out.status == AnalyzerStatus.FAILED
                assert "Silent host fallback is blocked by security policy" in out.findings[0].evidence
                assert out.metrics.get("policy") == "no_silent_host_fallback"


# ==============================================================================
# 4. AUTHENTICATION RATE LIMITING
# ==============================================================================

def test_login_rate_limiting_and_retry_after(security_test_env):
    """Verify that repeated failed login attempts trigger HTTP 429 with Retry-After header."""
    client, session_factory, _ = security_test_env

    with session_factory() as session:
        register_user(session, "rate_target@example.com", "rate_target", "Password123!")

    # Attempt failed logins up to the limit (configured at max 3)
    with patch.object(settings, "rate_limit_login_per_minute", 3):
        for _ in range(3):
            bad_resp = client.post(
                "/api/auth/login",
                json={"email_or_username": "rate_target", "password": "WrongPassword!"},
            )
            assert bad_resp.status_code == 401

        # 4th attempt must be rejected with 429 Too Many Requests
        rate_limited_resp = client.post(
            "/api/auth/login",
            json={"email_or_username": "rate_target", "password": "WrongPassword!"},
        )
        assert rate_limited_resp.status_code == 429
        assert "Retry-After" in rate_limited_resp.headers
        assert int(rate_limited_resp.headers["Retry-After"]) > 0
        assert "Too many failed login attempts" in rate_limited_resp.json()["detail"]


def test_registration_rate_limiting(security_test_env):
    """Verify registration abuse protection per IP triggers HTTP 429."""
    client, _, _ = security_test_env

    with patch.object(settings, "rate_limit_register_per_minute", 2):
        # 1st registration
        r1 = client.post(
            "/api/auth/register",
            json={"email": "u1@test.com", "username": "user_one", "password": "Password123!"},
        )
        assert r1.status_code == 201

        # 2nd registration
        r2 = client.post(
            "/api/auth/register",
            json={"email": "u2@test.com", "username": "user_two", "password": "Password123!"},
        )
        assert r2.status_code == 201

        # 3rd registration from same client IP -> 429
        r3 = client.post(
            "/api/auth/register",
            json={"email": "u3@test.com", "username": "user_three", "password": "Password123!"},
        )
        assert r3.status_code == 429
        assert "Retry-After" in r3.headers
        assert "Too many registration attempts" in r3.json()["detail"]
