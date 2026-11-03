"""Benchmark and Verification Suite for APEX 2.0 Phase 2B:
Type Intelligence, Dynamic Runtime Trace Reconciliation, and Concurrency/Resource Safety.
"""
from __future__ import annotations

import json
from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient

from app.main import create_app
from app.models.entities import Base, ReviewedProject
from app.services.auth_service import create_access_token, register_user
from app.services.analyzers.repository_graph import RepositorySymbolIndex
from app.services.analyzers.taint_engine import InterproceduralTaintAnalyzer
from app.services.analyzers.type_engine import run_type_intelligence_analysis
from app.services.analyzers.resource_concurrency_analyzer import run_resource_concurrency_analysis
from app.services.analyzers.trace_engine import DynamicTraceReconciler
from app.services.analyzers.base import FindingItem


def test_type_informed_taint_suppresses_numeric_injection(tmp_path: Path):
    """Verify that parameters annotated with numeric types (int, float) suppress false-positive injection findings."""
    routes_file = tmp_path / "routes.py"
    routes_file.write_text(
        """from fastapi import FastAPI
import subprocess

app = FastAPI()

@app.get("/items/{item_id}")
def get_item(item_id: int):
    # item_id is strongly typed as int, not vulnerable to shell injection
    subprocess.run(f"echo {item_id}", shell=True)
""",
        encoding="utf-8",
    )

    index = RepositorySymbolIndex(tmp_path)
    analyzer = InterproceduralTaintAnalyzer(index)
    findings = analyzer.analyze()

    cmd_findings = [f for f in findings if f.rule_id == "SEC-TAINT-COMMAND-INJECTION"]
    # Should be 0 because item_id is typed as int
    assert len(cmd_findings) == 0


def test_none_safety_detects_unchecked_optional_dereference(tmp_path: Path):
    """Verify that dereferencing Optional[T] variables without a None-guard is detected as a bug risk."""
    code_file = tmp_path / "user_service.py"
    code_file.write_text(
        """from typing import Optional

class User:
    email: str = "user@test.com"
    def save(self): pass

def process_user(user: Optional[User]):
    # Bug: user can be None, but .save() is called unguarded
    user.save()
""",
        encoding="utf-8",
    )

    findings, metrics, signatures = run_type_intelligence_analysis(tmp_path)
    none_findings = [f for f in findings if f.rule_id == "TYPE-UNCHECKED-OPTIONAL-DEREFERENCE"]

    assert len(none_findings) == 1
    assert "user" in none_findings[0].evidence
    assert none_findings[0].severity == "high"
    assert none_findings[0].line == 9


def test_none_safety_respects_guards_true_negative(tmp_path: Path):
    """Verify that properly guarded Optional dereferences generate zero false positives."""
    code_file = tmp_path / "safe_user_service.py"
    code_file.write_text(
        """from typing import Optional

class User:
    def save(self): pass

def process_user_guard1(user: Optional[User]):
    if user is not None:
        user.save()

def process_user_guard2(user: Optional[User]):
    assert user is not None
    user.save()

def process_user_guard3(user: Optional[User]):
    if not user:
        return
    user.save()
""",
        encoding="utf-8",
    )

    findings, _, _ = run_type_intelligence_analysis(tmp_path)
    none_findings = [f for f in findings if f.rule_id == "TYPE-UNCHECKED-OPTIONAL-DEREFERENCE"]
    assert len(none_findings) == 0


def test_resource_unclosed_file_handle_leak(tmp_path: Path):
    """Verify that file/socket resources allocated without with-statement or close() are flagged as leaks."""
    code_file = tmp_path / "reporter.py"
    code_file.write_text(
        """def generate_report():
    f = open("report.csv", "w")
    f.write("data")
    # Missing f.close() and not using with
    return "ok"
""",
        encoding="utf-8",
    )

    findings, metrics = run_resource_concurrency_analysis(tmp_path)
    leak_findings = [f for f in findings if f.rule_id == "RESOURCE-UNCLOSED-HANDLE"]

    assert len(leak_findings) == 1
    assert "report.csv" in leak_findings[0].evidence or "'f'" in leak_findings[0].evidence
    assert leak_findings[0].line == 2


def test_resource_context_manager_and_closed_handle_true_negative(tmp_path: Path):
    """Verify that context-managed or explicitly closed resources produce zero leak findings."""
    code_file = tmp_path / "safe_reporter.py"
    code_file.write_text(
        """def write_safe1():
    with open("data1.txt", "w") as f:
        f.write("hello")

def write_safe2():
    f = open("data2.txt", "w")
    f.write("hello")
    f.close()
""",
        encoding="utf-8",
    )

    findings, _ = run_resource_concurrency_analysis(tmp_path)
    leak_findings = [f for f in findings if f.rule_id == "RESOURCE-UNCLOSED-HANDLE"]
    assert len(leak_findings) == 0


def test_async_blocking_io_call_detected(tmp_path: Path):
    """Verify that synchronous blocking calls (time.sleep, requests.get) in async coroutines are detected."""
    code_file = tmp_path / "async_service.py"
    code_file.write_text(
        """import time
import requests

async def handle_request():
    # Blocking call inside event loop
    time.sleep(1.0)
    requests.get("https://example.com/api")
    return {"status": "ok"}
""",
        encoding="utf-8",
    )

    findings, metrics = run_resource_concurrency_analysis(tmp_path)
    blocking = [f for f in findings if f.rule_id == "ASYNC-BLOCKING-IO-CALL"]

    assert len(blocking) >= 2
    rule_ids = {f.evidence for f in blocking}
    assert any("time.sleep" in e for e in rule_ids)
    assert any("requests.get" in e for e in rule_ids)


def test_unsynchronized_shared_mutable_in_async_scope(tmp_path: Path):
    """Verify that mutating shared module-level state inside async routines without locks is flagged."""
    code_file = tmp_path / "state_manager.py"
    code_file.write_text(
        """CACHE = {}

async def update_cache(key, val):
    # Unsynchronized mutation of module-level dict
    CACHE.update({key: val})
    CACHE.pop(key, None)
""",
        encoding="utf-8",
    )

    findings, metrics = run_resource_concurrency_analysis(tmp_path)
    concurrency_risks = [f for f in findings if f.rule_id == "CONCURRENCY-UNSYNCHRONIZED-SHARED-STATE"]

    assert len(concurrency_risks) >= 1
    assert "CACHE" in concurrency_risks[0].evidence


def test_dynamic_trace_reconciliation_confirms_dead_code(tmp_path: Path):
    """Verify that unreferenced private symbols with 0 dynamic executions are upgraded to confirmed dead code."""
    cov_file = tmp_path / "coverage.json"
    cov_file.write_text(
        json.dumps(
            {
                "files": {
                    str(tmp_path / "utils.py"): {
                        "executed_lines": [1, 2, 8, 9],
                        "missing_lines": [4, 5],
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    test_finding = FindingItem(
        category="code_quality",
        severity="low",
        confidence=0.70,
        evidence="Unreferenced private symbol '_unused_internal_calc'",
        analyzer_source="code_intelligence",
        rule_id="AST-UNREFERENCED-PRIVATE-SYMBOL",
        title="Unreferenced Private Symbol",
        file="utils.py",
        line=4,
    )

    reconciler = DynamicTraceReconciler(tmp_path)
    reconciled = reconciler.reconcile_findings([test_finding])

    assert len(reconciled) == 1
    assert reconciled[0].rule_id == "CONFIRMED-DEAD-CODE"
    assert reconciled[0].confidence == 1.0
    assert "[Dynamic Trace]: Confirmed dead code" in reconciled[0].evidence


def test_test_failure_trace_correlation(tmp_path: Path):
    """Verify that JUnit XML failure traces correlate directly to static findings at matching stack frames."""
    junit_file = tmp_path / "junit.xml"
    junit_file.write_text(
        f"""<?xml version="1.0" encoding="utf-8"?>
<testsuites>
  <testsuite name="unit" errors="0" failures="1" tests="1">
    <testcase classname="tests.test_auth" name="test_login_flow" time="0.042">
      <failure message="KeyError: 'token'">
Traceback (most recent call last):
  File "{str(tmp_path / 'services' / 'auth.py')}", line 34, in login
    return resp["token"]
KeyError: 'token'
      </failure>
    </testcase>
  </testsuite>
</testsuites>
""",
        encoding="utf-8",
    )

    static_finding = FindingItem(
        category="bug_risk",
        severity="medium",
        confidence=0.75,
        evidence="Potential KeyError accessing dict token without verification",
        analyzer_source="code_intelligence",
        rule_id="BUG-DICT-KEY",
        title="Unverified Dictionary Key Access",
        file="services/auth.py",
        line=34,
    )

    reconciler = DynamicTraceReconciler(tmp_path)
    reconciled = reconciler.reconcile_findings([static_finding])

    assert len(reconciled) == 1
    assert "[Correlated Test Failure]" in reconciled[0].evidence
    assert "test_login_flow" in reconciled[0].evidence
    assert reconciled[0].confidence >= 0.90


def test_code_intelligence_api_endpoint_and_isolation(tmp_path: Path):
    """Verify GET /api/project-reviews/{project_id}/code-intelligence endpoint returns full metrics and enforces tenant RBAC."""
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    app = create_app(database_engine=engine)
    app.state.SessionLocal = session_factory

    repo_dir = tmp_path / "repo_ci"
    repo_dir.mkdir()
    (repo_dir / "service.py").write_text(
        """from typing import Optional
class Item: pass
def get_item(i: Optional[Item]):
    i.save()
""",
        encoding="utf-8",
    )

    with session_factory() as session:
        user_a = register_user(session, "user_ci_a@test.com", "user_ci_a", "Password123!")
        user_b = register_user(session, "user_ci_b@test.com", "user_ci_b", "Password123!")

        project = ReviewedProject(
            name="CI Project",
            repository_path=str(repo_dir),
            owner_id=user_a.id,
            source_type="local",
        )
        session.add(project)
        session.commit()
        session.refresh(project)
        proj_id = project.id

        token_a = create_access_token(user_a)
        token_b = create_access_token(user_b)

    with TestClient(app) as client:
        # 1. Owner retrieves code intelligence -> 200 OK
        resp = client.get(
            f"/api/project-reviews/{proj_id}/code-intelligence",
            headers={"Authorization": f"Bearer {token_a}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "type_intelligence" in data
        assert "resource_concurrency" in data
        assert "dynamic_traces" in data
        assert data["type_intelligence"]["metrics"]["total_functions"] >= 1

        # 2. Cross-tenant request -> 404 Not Found (non-disclosing isolation)
        resp_idor = client.get(
            f"/api/project-reviews/{proj_id}/code-intelligence",
            headers={"Authorization": f"Bearer {token_b}"},
        )
        assert resp_idor.status_code == 404

        # 3. Invalid token -> 401 Unauthorized
        resp_invalid = client.get(
            f"/api/project-reviews/{proj_id}/code-intelligence",
            headers={"Authorization": "Bearer invalid_token"},
        )
        assert resp_invalid.status_code == 401
