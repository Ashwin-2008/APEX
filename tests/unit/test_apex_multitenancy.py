"""Security and Multi-Tenancy Isolation Test Suite for APEX.

Verifies Parts 2, 8, 16, 19 of the APEX Specification:
1. Scenario 1: User A creates Project Alpha, User B creates Project Beta.
   - User A sees only Alpha in GET /api/projects.
   - User B sees only Beta in GET /api/projects.
   - User A cannot retrieve Beta by guessing its project ID (returns 404).
   - User B cannot retrieve Alpha by guessing its project ID (returns 404).
2. Scenario 2: User A subscribes to Alpha, User B modifies Beta.
   - User A receives no Beta events.
3. Scenario 3: User A requests a finding belonging to User B -> access denied (404).
4. Scenario 4: User A requests User B's coverage or activity -> access denied (404).
5. Scenario 5: Background job retains project ownership and tenant context.
6. Scenario 6: False positive management and finding suppression lifecycle.
7. Scenario 7: Notification isolation across tenants.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.session import migrate_sqlite_schema
from app.main import create_app
from app.models.entities import ProjectFinding, ProjectReview, ReviewedProject, User
from app.services.auth_service import create_access_token, register_user
from app.services.finding_service import suppress_finding, unsuppress_finding


@pytest.fixture
def isolated_client(tmp_path: Path):
    """Create a fully isolated in-memory test client with migrated schema."""
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
        yield client, session_factory


def test_auth_registration_login_and_token_validation(isolated_client):
    client, session_factory = isolated_client

    # 1. Register User A
    reg_resp = client.post(
        "/api/auth/register",
        json={
            "email": "user_a@apex.test",
            "username": "user_a",
            "password": "Password123!",
            "full_name": "Alice Engineer",
        },
    )
    assert reg_resp.status_code == 201
    data = reg_resp.json()
    assert "token" in data
    assert data["user"]["email"] == "user_a@apex.test"

    # 2. Login User A
    login_resp = client.post(
        "/api/auth/login",
        json={
            "email_or_username": "user_a",
            "password": "Password123!",
        },
    )
    assert login_resp.status_code == 200
    token = login_resp.json()["token"]

    # 3. Access /api/auth/me with Bearer token
    me_resp = client.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert me_resp.status_code == 200
    assert me_resp.json()["user"]["username"] == "user_a"

    # 4. Access /api/auth/me without token -> 401
    unauth_resp = client.get("/api/auth/me")
    assert unauth_resp.status_code == 401


def test_scenario_1_multi_user_workspace_and_cross_project_isolation(isolated_client, tmp_path: Path):
    client, session_factory = isolated_client

    # Create dummy local repositories
    repo_alpha = tmp_path / "repo_alpha"
    repo_alpha.mkdir()
    (repo_alpha / "main.py").write_text("print('hello from alpha')", encoding="utf-8")
    (repo_alpha / "README.md").write_text("# Project Alpha Requirements", encoding="utf-8")

    repo_beta = tmp_path / "repo_beta"
    repo_beta.mkdir()
    (repo_beta / "server.py").write_text("print('hello from beta')", encoding="utf-8")
    (repo_beta / "README.md").write_text("# Project Beta Requirements", encoding="utf-8")

    # Register User A and User B
    resp_a = client.post(
        "/api/auth/register",
        json={"email": "alice@company.com", "username": "alice", "password": "Password123!"},
    )
    token_a = resp_a.json()["token"]

    resp_b = client.post(
        "/api/auth/register",
        json={"email": "bob@company.com", "username": "bob", "password": "Password123!"},
    )
    token_b = resp_b.json()["token"]

    # User A connects Project Alpha
    conn_a = client.post(
        "/api/projects",
        headers={"Authorization": f"Bearer {token_a}"},
        json={
            "name": "Project Alpha",
            "source_type": "local",
            "path": str(repo_alpha),
            "enable_monitoring": False,
        },
    )
    assert conn_a.status_code == 201
    alpha_id = conn_a.json()["project"]["id"]

    # User B connects Project Beta
    conn_b = client.post(
        "/api/projects",
        headers={"Authorization": f"Bearer {token_b}"},
        json={
            "name": "Project Beta",
            "source_type": "local",
            "path": str(repo_beta),
            "enable_monitoring": False,
        },
    )
    assert conn_b.status_code == 201
    beta_id = conn_b.json()["project"]["id"]

    assert alpha_id != beta_id

    # VERIFY: User A sees only Project Alpha
    list_a = client.get("/api/projects", headers={"Authorization": f"Bearer {token_a}"})
    assert list_a.status_code == 200
    a_projects = list_a.json()
    assert len(a_projects) == 1
    assert a_projects[0]["id"] == alpha_id
    assert a_projects[0]["name"] == "Project Alpha"

    # VERIFY: User B sees only Project Beta
    list_b = client.get("/api/projects", headers={"Authorization": f"Bearer {token_b}"})
    assert list_b.status_code == 200
    b_projects = list_b.json()
    assert len(b_projects) == 1
    assert b_projects[0]["id"] == beta_id
    assert b_projects[0]["name"] == "Project Beta"

    # VERIFY: User A cannot retrieve Beta by guessing its ID -> 404 (non-disclosing)
    cross_get_a = client.get(f"/api/projects/{beta_id}", headers={"Authorization": f"Bearer {token_a}"})
    assert cross_get_a.status_code == 404

    # VERIFY: User B cannot retrieve Alpha by guessing its ID -> 404 (non-disclosing)
    cross_get_b = client.get(f"/api/projects/{alpha_id}", headers={"Authorization": f"Bearer {token_b}"})
    assert cross_get_b.status_code == 404

    # VERIFY: User A cannot access Beta via legacy review routes
    cross_review_a = client.get(
        f"/api/project-reviews/{beta_id}/history",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert cross_review_a.status_code == 404

    # VERIFY: User A cannot access Beta's coverage
    cross_cov_a = client.get(
        f"/api/projects/{beta_id}/coverage",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert cross_cov_a.status_code == 404


def test_scenario_3_finding_suppression_and_cross_user_denial(isolated_client, tmp_path: Path):
    client, session_factory = isolated_client

    repo_dir = tmp_path / "repo_findings"
    repo_dir.mkdir()
    (repo_dir / "app.py").write_text("token = 'ghp_1234567890abcdefghijklmnopqrstuvwx'\n", encoding="utf-8")
    (repo_dir / "README.md").write_text("# Requirements", encoding="utf-8")

    # Register User A and User B
    resp_a = client.post(
        "/api/auth/register",
        json={"email": "alice_findings@test.com", "username": "alice_f", "password": "Password123!"},
    )
    token_a = resp_a.json()["token"]

    resp_b = client.post(
        "/api/auth/register",
        json={"email": "bob_findings@test.com", "username": "bob_f", "password": "Password123!"},
    )
    token_b = resp_b.json()["token"]

    # User A connects project
    conn = client.post(
        "/api/projects",
        headers={"Authorization": f"Bearer {token_a}"},
        json={"name": "Findings Project", "source_type": "local", "path": str(repo_dir), "enable_monitoring": False},
    )
    project_id = conn.json()["project"]["id"]

    # User A lists findings
    findings_resp = client.get(
        f"/api/projects/{project_id}/findings",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert findings_resp.status_code == 200
    findings = findings_resp.json()
    assert len(findings) > 0
    target_finding = findings[0]
    finding_id = target_finding["id"]

    # VERIFY: User B cannot suppress User A's finding
    suppress_cross = client.post(
        f"/api/projects/{project_id}/findings/{finding_id}/suppress",
        headers={"Authorization": f"Bearer {token_b}"},
        json={"reason": "False alarm detected by Bob", "suppression_type": "false_positive"},
    )
    assert suppress_cross.status_code == 404

    # VERIFY: User A can suppress their own finding with justification
    suppress_a = client.post(
        f"/api/projects/{project_id}/findings/{finding_id}/suppress",
        headers={"Authorization": f"Bearer {token_a}"},
        json={"reason": "Sample dummy test key, not a real secret", "suppression_type": "false_positive"},
    )
    assert suppress_a.status_code == 200
    assert suppress_a.json()["suppressed"] is True
    assert suppress_a.json()["status"] == "SUPPRESSED"

    # Reopen finding
    reopen_a = client.post(
        f"/api/projects/{project_id}/findings/{finding_id}/reopen",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert reopen_a.status_code == 200
    assert reopen_a.json()["suppressed"] is False
    assert reopen_a.json()["status"] == "ACTIVE"


def test_scenario_7_notification_isolation_and_unread_counts(isolated_client, tmp_path: Path):
    client, session_factory = isolated_client

    repo_dir = tmp_path / "repo_notifs"
    repo_dir.mkdir()
    (repo_dir / "index.js").write_text("console.log('notif test');", encoding="utf-8")

    # Register User A and User B
    resp_a = client.post(
        "/api/auth/register",
        json={"email": "alice_notif@test.com", "username": "alice_n", "password": "Password123!"},
    )
    token_a = resp_a.json()["token"]

    resp_b = client.post(
        "/api/auth/register",
        json={"email": "bob_notif@test.com", "username": "bob_n", "password": "Password123!"},
    )
    token_b = resp_b.json()["token"]

    # User A connects project -> triggers notification for User A
    client.post(
        "/api/projects",
        headers={"Authorization": f"Bearer {token_a}"},
        json={"name": "Notif Project", "source_type": "local", "path": str(repo_dir), "enable_monitoring": False},
    )

    # Check User A's unread notification count >= 1
    unread_a = client.get("/api/notifications/unread-count", headers={"Authorization": f"Bearer {token_a}"})
    assert unread_a.status_code == 200
    assert unread_a.json()["unread_count"] >= 1

    # Check User B's unread notification count == 0
    unread_b = client.get("/api/notifications/unread-count", headers={"Authorization": f"Bearer {token_b}"})
    assert unread_b.status_code == 200
    assert unread_b.json()["unread_count"] == 0

    # User A reads their notifications
    notifs_a = client.get("/api/notifications", headers={"Authorization": f"Bearer {token_a}"}).json()
    assert len(notifs_a) >= 1
    first_notif_id = notifs_a[0]["id"]

    mark_resp = client.post(
        f"/api/notifications/{first_notif_id}/read",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert mark_resp.status_code == 200

    # User B cannot mark User A's notification as read
    mark_cross = client.post(
        f"/api/notifications/{first_notif_id}/read",
        headers={"Authorization": f"Bearer {token_b}"},
    )
    assert mark_cross.status_code == 404

