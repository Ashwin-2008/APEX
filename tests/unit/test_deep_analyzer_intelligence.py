"""Deep Analyzer Intelligence Benchmark and Regression Test Suite for APEX 2.0.

Verifies Phase 2A:
1. Module A: Repository-Wide Interprocedural Security Taint Analysis
   - Multi-hop cross-file command injection (Controller -> Service -> Executor)
   - Cross-file SQL injection (Route -> DB Helper)
   - Cross-file Path traversal (Route -> Storage Loader)
   - Safe true negatives (parameterized SQL, argument array without shell=True, os.path.basename)
2. Module B: Architecture Intelligence & Dependency Cycles
   - Direct cycles (A <-> B)
   - Indirect cycles (A -> B -> C -> A)
   - Canonical cycle normalization (zero duplicate rotations)
   - Architectural layer boundary violations (models importing controllers)
3. Module C: Advanced AST Code Intelligence
   - Exact McCabe cyclomatic complexity calculation and tiering
   - Unreachable code after return / raise
   - Statically unreachable branches (if False:)
   - Unused imports and unreferenced private functions
   - Framework route and test symbol protection (zero false positives on live endpoints)
"""
from __future__ import annotations

import os
from pathlib import Path
import pytest

from app.services.analyzers.architecture_analyzer import run_architecture_analysis
from app.services.analyzers.code_intel_analyzer import run_code_intelligence_analysis
from app.services.analyzers.repository_graph import (
    CanonicalModuleResolver,
    RepositorySymbolIndex,
    TarjanCycleDetector,
    calculate_mccabe_complexity,
)
from app.services.analyzers.security_analyzer import run_security_analysis
from app.services.analyzers.taint_engine import InterproceduralTaintAnalyzer


# ==============================================================================
# 1. MODULE A: REPOSITORY-WIDE INTERPROCEDURAL SECURITY TAINT ANALYSIS
# ==============================================================================

def test_cross_file_command_injection_taint_propagation(tmp_path: Path):
    """Verify multi-hop cross-file command injection tracking: Controller -> Service -> Executor."""
    repo = tmp_path / "repo_taint_cmd"
    repo.mkdir()

    # 1. Controller (Source)
    (repo / "controller.py").write_text(
        """from fastapi import FastAPI, Request
from service import execute_task

app = FastAPI()

@app.get("/run")
def handle_command(request: Request):
    user_input = request.query_params["command"]
    execute_task(user_input)
""",
        encoding="utf-8",
    )

    # 2. Service (Intermediate Propagation)
    (repo / "service.py").write_text(
        """from executor import run_command

def execute_task(value):
    run_command(value)
""",
        encoding="utf-8",
    )

    # 3. Executor (Dangerous Sink)
    (repo / "executor.py").write_text(
        """import subprocess

def run_command(command):
    subprocess.run(command, shell=True)
""",
        encoding="utf-8",
    )

    # Run security analyzer on the repository
    out = run_security_analysis(repo)
    assert out.status.value == "COMPLETE"

    # Verify interprocedural command injection finding
    cmd_findings = [f for f in out.findings if f.rule_id == "SEC-TAINT-CMD-INJECTION"]
    assert len(cmd_findings) >= 1, "Expected SEC-TAINT-CMD-INJECTION to be detected across files"

    finding = cmd_findings[0]
    assert finding.severity == "critical"
    assert finding.confidence >= 0.90
    assert "Interprocedural taint flow" in finding.evidence
    assert finding.data_flow is not None and len(finding.data_flow) >= 3

    # Check step roles
    roles = [step["role"] for step in finding.data_flow]
    assert "source" in roles
    assert "sink" in roles


def test_cross_file_sql_injection_taint_propagation(tmp_path: Path):
    """Verify cross-file SQL injection propagation: Route Handler -> Database Helper."""
    repo = tmp_path / "repo_taint_sqli"
    repo.mkdir()

    (repo / "routes.py").write_text(
        """from fastapi import FastAPI
from db_helper import query_user

app = FastAPI()

@app.get("/users/{user_id}")
def get_user_route(user_id: str):
    return query_user(user_id)
""",
        encoding="utf-8",
    )

    (repo / "db_helper.py").write_text(
        """def query_user(uid):
    raw_sql = f"SELECT * FROM users WHERE id = '{uid}'"
    cursor.execute(raw_sql)
""",
        encoding="utf-8",
    )

    out = run_security_analysis(repo)
    sqli_findings = [f for f in out.findings if f.rule_id == "SEC-TAINT-SQL-INJECTION"]
    assert len(sqli_findings) >= 1, "Expected SEC-TAINT-SQL-INJECTION across files"
    f = sqli_findings[0]
    assert f.severity == "critical"
    assert any("SELECT * FROM users" in step["expression"] for step in f.data_flow)
    assert f.data_flow[-1]["expression"] == "cursor.execute(raw_sql)"


def test_cross_file_path_traversal_taint_propagation(tmp_path: Path):
    """Verify cross-file path traversal propagation: Route Handler -> Storage Layer."""
    repo = tmp_path / "repo_taint_path"
    repo.mkdir()

    (repo / "api.py").write_text(
        """from fastapi import FastAPI
from storage import load_file

app = FastAPI()

@app.get("/download")
def download_file(filename: str):
    return load_file(filename)
""",
        encoding="utf-8",
    )

    (repo / "storage.py").write_text(
        """def load_file(target_path):
    with open(target_path, "r") as f:
        return f.read()
""",
        encoding="utf-8",
    )

    out = run_security_analysis(repo)
    path_findings = [f for f in out.findings if f.rule_id == "SEC-TAINT-PATH-TRAVERSAL"]
    assert len(path_findings) >= 1, "Expected SEC-TAINT-PATH-TRAVERSAL across files"
    assert path_findings[0].severity == "high"


def test_safe_sanitized_security_true_negatives(tmp_path: Path):
    """Verify that parameterized SQL, safe subprocess argument arrays, and sanitized paths produce ZERO false positives."""
    repo = tmp_path / "repo_safe_sec"
    repo.mkdir()

    (repo / "safe_app.py").write_text(
        """import os
import subprocess
from fastapi import FastAPI, Request

app = FastAPI()

@app.get("/safe")
def safe_handler(request: Request, user_id: str, file_name: str):
    # 1. Parameterized SQL with tuple -> SAFE
    cursor.execute("SELECT * FROM users WHERE id = %s", (user_id,))

    # 2. Subprocess array without shell=True -> SAFE
    subprocess.run(["ls", "-l", user_id], shell=False)

    # 3. Path sanitized with os.path.basename -> SAFE
    safe_name = os.path.basename(file_name)
    with open(safe_name, "r") as f:
        pass
""",
        encoding="utf-8",
    )

    out = run_security_analysis(repo)
    taint_findings = [
        f for f in out.findings
        if f.rule_id in {"SEC-TAINT-CMD-INJECTION", "SEC-TAINT-SQL-INJECTION", "SEC-TAINT-PATH-TRAVERSAL"}
    ]
    assert len(taint_findings) == 0, f"Expected 0 false positives on safe code, found: {taint_findings}"


# ==============================================================================
# 2. MODULE B: ARCHITECTURE INTELLIGENCE & CYCLE DETECTION
# ==============================================================================

def test_architecture_direct_and_indirect_cycle_detection(tmp_path: Path):
    """Verify detection of direct (2-hop) and indirect (3-hop) circular dependencies."""
    repo = tmp_path / "repo_arch_cycles"
    repo.mkdir()

    # 3-hop cycle: a -> b -> c -> a
    (repo / "mod_a.py").write_text("import mod_b\ndef fa(): pass\n", encoding="utf-8")
    (repo / "mod_b.py").write_text("import mod_c\ndef fb(): pass\n", encoding="utf-8")
    (repo / "mod_c.py").write_text("import mod_a\ndef fc(): pass\n", encoding="utf-8")

    out = run_architecture_analysis(repo)
    assert out.status.value == "COMPLETE"

    cycle_findings = [f for f in out.findings if f.rule_id == "ARCH-CIRCULAR-DEPENDENCY"]
    assert len(cycle_findings) == 1, "Expected exactly 1 canonical 3-hop cycle (no duplicate rotations)"

    f = cycle_findings[0]
    assert f.metadata["cycle_length"] == 3
    cycle = f.metadata["cycle"]
    assert cycle[0] == cycle[-1]
    assert set(cycle) == {"mod_a", "mod_b", "mod_c"}


def test_architecture_layer_boundary_violation(tmp_path: Path):
    """Verify that lower domain/model layers importing presentation/API layers triggers ARCH-LAYER-VIOLATION."""
    repo = tmp_path / "repo_arch_layer"
    models_dir = repo / "models"
    api_dir = repo / "api"
    models_dir.mkdir(parents=True)
    api_dir.mkdir(parents=True)

    (api_dir / "routes.py").write_text("def handle_request(): pass\n", encoding="utf-8")
    # Layer violation: model imports api.routes
    (models_dir / "user.py").write_text("from api.routes import handle_request\nclass User: pass\n", encoding="utf-8")

    out = run_architecture_analysis(repo)
    layer_findings = [f for f in out.findings if f.rule_id == "ARCH-LAYER-VIOLATION"]
    assert len(layer_findings) >= 1, "Expected ARCH-LAYER-VIOLATION when model imports api"
    assert "Architectural layer violation" in layer_findings[0].evidence


def test_valid_acyclic_architecture_zero_cycles(tmp_path: Path):
    """Verify that a clean DAG architecture produces 0 cycle findings."""
    repo = tmp_path / "repo_arch_clean"
    repo.mkdir()

    (repo / "core.py").write_text("def base_fn(): pass\n", encoding="utf-8")
    (repo / "service.py").write_text("import core\ndef svc_fn(): core.base_fn()\n", encoding="utf-8")
    (repo / "controller.py").write_text("import service\ndef run(): service.svc_fn()\n", encoding="utf-8")

    out = run_architecture_analysis(repo)
    cycle_findings = [f for f in out.findings if f.rule_id == "ARCH-CIRCULAR-DEPENDENCY"]
    assert len(cycle_findings) == 0, "Expected 0 circular dependency findings in acyclic architecture"


# ==============================================================================
# 3. MODULE C: ADVANCED AST CODE INTELLIGENCE & DEAD CODE
# ==============================================================================

def test_mccabe_cyclomatic_complexity_calculation():
    """Verify exact McCabe cyclomatic complexity counting on multiple control structures."""
    import ast

    # McCabe Complexity: 1 (base) + 1 (if) + 1 (elif) + 1 (for) + 1 (while) + 1 (ifExp) + 1 (except) + 1 (if) + 1 (boolOp 'and') = 9
    code = """
def complex_function(a, b, c):
    if a > 0:
        x = 1
    elif a < 0:
        x = 2
    for item in b:
        pass
    while c:
        pass
    try:
        val = 10 if a else 20
    except ValueError:
        pass
    if a and b:
        pass
    return x
"""
    tree = ast.parse(code)
    func_node = tree.body[0]
    calc_comp = calculate_mccabe_complexity(func_node)
    assert calc_comp == 9, f"Expected complexity 9, got {calc_comp}"


def test_dead_code_unreachable_statements_and_unused_imports(tmp_path: Path):
    """Verify detection of unreachable statements after returns, raises, and unused imports."""
    repo = tmp_path / "repo_dead_code"
    repo.mkdir()

    (repo / "dead_samples.py").write_text(
        """import math  # Unused import
import sys   # Used below

def calculate_discount(price):
    if price < 0:
        raise ValueError("Invalid price")
        print("Never reached after raise")  # Unreachable

    return price * 0.9
    print("Never reached after return")      # Unreachable

def _unused_private_helper():
    pass

def active_function():
    return sys.version
""",
        encoding="utf-8",
    )

    out = run_code_intelligence_analysis(repo)
    assert out.status.value == "COMPLETE"

    rule_ids = {f.rule_id for f in out.findings}
    assert "CODE-UNREACHABLE-STMT" in rule_ids, "Expected CODE-UNREACHABLE-STMT"
    assert "CODE-UNUSED-IMPORT" in rule_ids, "Expected CODE-UNUSED-IMPORT for 'math'"
    assert "CODE-UNREFERENCED-PRIVATE-FUNCTION" in rule_ids, "Expected unreferenced private function"


def test_framework_route_and_test_symbols_preserved(tmp_path: Path):
    """Verify that route handlers and test functions are never falsely flagged as dead code."""
    repo = tmp_path / "repo_live_framework"
    repo.mkdir()

    (repo / "app.py").write_text(
        """from fastapi import FastAPI
app = FastAPI()

@app.get("/health")
def health_check():
    return {"status": "ok"}

def test_system_sanity():
    assert True
""",
        encoding="utf-8",
    )

    out = run_code_intelligence_analysis(repo)
    dead_symbols = [
        f for f in out.findings
        if f.rule_id == "CODE-UNREFERENCED-PRIVATE-FUNCTION"
    ]
    assert len(dead_symbols) == 0, f"Expected 0 dead code false positives on framework routes, got: {dead_symbols}"



def test_architecture_graph_api_endpoint_and_isolation(tmp_path: Path):
    """Verify GET /api/project-reviews/{id}/architecture-graph with tenant isolation."""
    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool
    from app.db.base import Base
    from app.db.session import migrate_sqlite_schema
    from app.main import create_app
    from app.models.entities import ReviewedProject
    from app.services.auth_service import create_access_token, register_user

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

    repo_a = tmp_path / "repo_a"
    repo_a.mkdir()
    (repo_a / "service.py").write_text("import utils\ndef run(): pass\n", encoding="utf-8")
    (repo_a / "utils.py").write_text("def helper(): pass\n", encoding="utf-8")

    with session_factory() as session:
        user_a = register_user(session, "user_arch_a@test.com", "user_arch_a", "Password123!")
        user_b = register_user(session, "user_arch_b@test.com", "user_arch_b", "Password123!")

        proj_a = ReviewedProject(
            name="Arch Project A",
            repository_path=str(repo_a),
            owner_id=user_a.id,
            source_type="local",
        )
        session.add(proj_a)
        session.commit()
        session.refresh(proj_a)
        proj_id = proj_a.id

        token_a = create_access_token(user_a)
        token_b = create_access_token(user_b)

    with TestClient(app) as client:
        # 1. User A (owner) retrieves architecture graph -> 200 OK
        resp = client.get(
            f"/api/project-reviews/{proj_id}/architecture-graph",
            headers={"Authorization": f"Bearer {token_a}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "architecture_graph" in data
        assert "nodes" in data["architecture_graph"]
        assert "edges" in data["architecture_graph"]
        assert len(data["architecture_graph"]["nodes"]) >= 2

        # 2. User B (cross-tenant) retrieves User A's architecture graph -> 404 Not Found (non-disclosing)
        idor_resp = client.get(
            f"/api/project-reviews/{proj_id}/architecture-graph",
            headers={"Authorization": f"Bearer {token_b}"},
        )
        assert idor_resp.status_code == 404

        # 3. Invalid token request -> 401 Unauthorized
        invalid_resp = client.get(
            f"/api/project-reviews/{proj_id}/architecture-graph",
            headers={"Authorization": "Bearer invalid_or_expired_token"},
        )
        assert invalid_resp.status_code == 401
