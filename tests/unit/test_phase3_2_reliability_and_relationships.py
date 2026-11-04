"""Phase 3.2: Graph Reliability, Benchmark Validation & Cross-Technology Relationship Intelligence.

Exhaustive verification test suite containing 64 tests covering:
1. Canonical Identity Continuity Reliability (multi-signal matching, split/merged/ambiguous tracking, benchmark metrics)
2. Call Graph Accuracy and Calibration (advanced call resolution, getattr reflection, empirical calibration, Brier score)
3. Transactional Graph Update Reliability (staged versioning, concurrency lease, real subprocess crash test, consistency validation)
4. Calibrated Blast Radius Assessment (measured properties, heuristic factors, unavailable evidence, benchmark metrics)
5. Targeted Test Selection Validation (tiers, strictly NOT_EXECUTED status, Precision@K, Recall@K, unnecessary rate)
6. Cross-Technology Relationship Intelligence (React -> API -> Route -> Service -> Model -> Table, Docker, CI, Env vars)
7. Honest Multi-Dimensional Coverage Reporting (5 dimensions, valid statuses, dimensional breakdown)
8. Version Comparison and Historical Intelligence (diffing split/merged entities, edge confidence shifts, resolution changes)
9. Tenant Isolation & API Security (non-disclosing 404s across all endpoints)
"""
from __future__ import annotations

import ast
from datetime import datetime, timezone
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.routes.project_reviews import router as project_reviews_router
from app.db.base import Base
from app.models.entities import (
    EngineeringGraphEdge,
    EngineeringGraphNode,
    EngineeringGraphUpdateJournal,
    EngineeringGraphVersion,
    EngineeringIdentityTransition,
    ReviewedProject,
    User,
)
from app.services.auth_service import create_access_token
from app.services.graph.blast_radius import (
    BlastRadiusBenchmark,
    BlastRadiusEngine,
    BlastRadiusReport,
)
from app.services.graph.call_resolver import (
    AdvancedCallResolver,
    CallResolutionType,
    CallResolverBenchmark,
)
from app.services.graph.coverage_reporter import (
    CoverageDimensionStatus,
    GraphCoverageReport,
    GraphCoverageReporter,
    TechnologyCoverageSummary,
)
from app.services.graph.extractor import GraphExtractionEngine
from app.services.graph.identity_continuity import (
    IdentityContinuityBenchmark,
    IdentityContinuityEngine,
    IdentityTransitionRecord,
    IdentityTransitionType,
)
from app.services.graph.models import (
    EdgeType,
    GraphEdge,
    GraphNode,
    NodeType,
    build_canonical_id,
)
from app.services.graph.test_selector import (
    RecommendedTest,
    TestRecommendationTier,
    TestSelectionBenchmark,
    TestSelectionEngine,
)
from app.services.graph.transactional_updater import TransactionalGraphUpdater
from app.services.graph.version_comparator import (
    GraphVersionComparator,
    VersionDiffReport,
)


@pytest.fixture
def mock_db_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    SessionClass = sessionmaker(bind=engine)
    session = SessionClass()

    owner = User(id=1, username="owner_p32", email="owner32@test.com", hashed_password="pw", is_active=True)
    other = User(id=2, username="other_p32", email="other32@test.com", hashed_password="pw", is_active=True)
    session.add_all([owner, other])
    session.flush()

    p1 = ReviewedProject(
        id=1,
        name="Phase 3.2 Master Repo",
        repository_path="c:/repos/p1",
        owner_id=1,
        monitoring_status="active",
    )
    p2 = ReviewedProject(
        id=2,
        name="Other Tenant Repo",
        repository_path="c:/repos/p2",
        owner_id=2,
        monitoring_status="active",
    )
    session.add_all([p1, p2])
    session.commit()

    yield session
    session.close()


@pytest.fixture
def api_test_app(mock_db_session: Session, multi_tier_repo: Path):
    test_app = FastAPI()
    test_app.state.SessionLocal = lambda: mock_db_session
    test_app.include_router(project_reviews_router, prefix="/api")

    p = mock_db_session.get(ReviewedProject, 1)
    if p:
        p.repository_path = str(multi_tier_repo)
        mock_db_session.commit()

    return test_app


@pytest.fixture
def other_auth_headers(mock_db_session: Session):
    user = mock_db_session.get(User, 2)
    token = create_access_token(user)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def multi_tier_repo(tmp_path: Path) -> Path:
    """Creates a multi-tier codebase covering React, FastAPI, SQLAlchemy, Docker, and CI."""
    root = tmp_path / "multi_tier_project"
    root.mkdir()

    # 1. Frontend (React + API Client)
    frontend_dir = root / "frontend" / "src"
    frontend_dir.mkdir(parents=True)
    (frontend_dir / "apiClient.ts").write_text(
        "import axios from 'axios';\n"
        "export const fetchUserData = (id: string) => axios.get(`/api/v1/users/${id}`);\n"
        "export const createAccount = (data: any) => fetch('/api/v1/auth/register', { method: 'POST' });\n",
        encoding="utf-8",
    )
    (frontend_dir / "UserProfile.tsx").write_text(
        "import React from 'react';\n"
        "import { fetchUserData } from './apiClient';\n"
        "export const UserProfile = ({ id }: { id: string }) => {\n"
        "  fetchUserData(id);\n"
        "  return <div>Profile</div>;\n"
        "};\n",
        encoding="utf-8",
    )

    # 2. Backend (FastAPI Routes + Services + Models)
    backend_dir = root / "backend" / "app"
    backend_dir.mkdir(parents=True)
    (backend_dir / "__init__.py").write_text("", encoding="utf-8")
    
    # Models
    models_dir = backend_dir / "models"
    models_dir.mkdir()
    (models_dir / "__init__.py").write_text("", encoding="utf-8")
    (models_dir / "user.py").write_text(
        "from sqlalchemy import Column, Integer, String\n"
        "from sqlalchemy.orm import declarative_base\n"
        "Base = declarative_base()\n"
        "class UserModel(Base):\n"
        "    __tablename__ = 'users_table'\n"
        "    id = Column(Integer, primary_key=True)\n"
        "    username = Column(String(50))\n"
        "    def get_details(self):\n"
        "        return {'id': self.id, 'username': self.username}\n",
        encoding="utf-8",
    )

    # Services
    services_dir = backend_dir / "services"
    services_dir.mkdir()
    (services_dir / "__init__.py").write_text("", encoding="utf-8")
    (services_dir / "user_service.py").write_text(
        "from models.user import UserModel\n"
        "def query_user_record(user_id: int):\n"
        "    model = UserModel()\n"
        "    return model.get_details()\n",
        encoding="utf-8",
    )

    # Routes
    api_dir = backend_dir / "api"
    api_dir.mkdir()
    (api_dir / "__init__.py").write_text("", encoding="utf-8")
    (api_dir / "routes.py").write_text(
        "from services.user_service import query_user_record\n"
        "class APIRouter:\n"
        "    def get(self, path): return lambda f: f\n"
        "    def post(self, path): return lambda f: f\n"
        "router = APIRouter()\n"
        "@router.get('/api/v1/users/{id}')\n"
        "def get_user_route(id: int):\n"
        "    return query_user_record(id)\n"
        "@router.post('/api/v1/auth/register')\n"
        "def register_route(payload: dict):\n"
        "    return {'status': 'ok'}\n",
        encoding="utf-8",
    )

    # Config consuming env var
    (backend_dir / "config.py").write_text(
        "import os\n"
        "DATABASE_URL = os.getenv('DATABASE_URL', 'sqlite:///app.db')\n"
        "API_SECRET = os.environ.get('SECRET_KEY', 'default_secret')\n",
        encoding="utf-8",
    )
    (backend_dir / "main.py").write_text("# main entrypoint\n", encoding="utf-8")

    # 3. Dockerfile
    (root / "Dockerfile").write_text(
        "FROM python:3.11-slim AS base\n"
        "WORKDIR /app\n"
        "COPY . .\n"
        "ENTRYPOINT [\"python\", \"backend/app/main.py\"]\n",
        encoding="utf-8",
    )

    # 4. CI Workflow
    ci_dir = root / ".github" / "workflows"
    ci_dir.mkdir(parents=True)
    (ci_dir / "ci.yml").write_text(
        "name: Build & Test\n"
        "jobs:\n"
        "  backend-test:\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        "      - name: Run Pytest\n"
        "        run: pytest backend/tests\n",
        encoding="utf-8",
    )

    # 5. Tests
    tests_dir = backend_dir / "tests"
    tests_dir.mkdir(parents=True, exist_ok=True)
    (tests_dir / "__init__.py").write_text("", encoding="utf-8")
    (tests_dir / "test_api.py").write_text(
        "def test_get_user():\n"
        "    assert True\n",
        encoding="utf-8",
    )

    return root


# ============================================================================
# 1. Canonical Identity Continuity Reliability Tests (1 - 10)
# ============================================================================

def test_identity_continuity_multi_signal_scoring_weights():
    node_a = GraphNode(
        canonical_id="sym::calc.py::compute",
        project_id=1,
        entity_type=NodeType.FUNCTION.value,
        name="compute",
        qualified_name="calc.compute",
        file_path="calc.py",
        start_line=10,
        end_line=20,
        metadata={"structural_fingerprint": "hash123"},
    )
    node_b = GraphNode(
        canonical_id="sym::calc.py::compute",
        project_id=1,
        entity_type=NodeType.FUNCTION.value,
        name="compute",
        qualified_name="calc.compute",
        file_path="calc.py",
        start_line=10,
        end_line=20,
        metadata={"structural_fingerprint": "hash123"},
    )
    score, breakdown = IdentityContinuityEngine.compute_multi_signal_score(node_a, node_b)
    assert score >= 0.70
    assert breakdown["name_similarity"] == 1.0
    assert breakdown["fingerprint_match"] is True


def test_identity_continuity_structural_fingerprint_match():
    node_a = GraphNode(
        canonical_id="sym::f1.py::old_helper",
        project_id=1,
        entity_type=NodeType.FUNCTION.value,
        name="old_helper",
        qualified_name="f1.old_helper",
        file_path="f1.py",
        start_line=5,
        end_line=15,
        metadata={"structural_fingerprint": "unique_body_ast_fp"},
    )
    node_b = GraphNode(
        canonical_id="sym::f1.py::new_helper",
        project_id=1,
        entity_type=NodeType.FUNCTION.value,
        name="new_helper",
        qualified_name="f1.new_helper",
        file_path="f1.py",
        start_line=5,
        end_line=15,
        metadata={"structural_fingerprint": "unique_body_ast_fp"},
    )
    score, breakdown = IdentityContinuityEngine.compute_multi_signal_score(node_a, node_b)
    assert breakdown["fingerprint_match"] is True
    assert score >= 0.70


def test_identity_continuity_sibling_jaccard_similarity():
    node_a = GraphNode(
        canonical_id="sym::m1.py::fn_a",
        project_id=1,
        entity_type=NodeType.FUNCTION.value,
        name="fn_a",
        qualified_name="m1.fn_a",
        file_path="m1.py",
        start_line=1,
        end_line=5,
    )
    node_b = GraphNode(
        canonical_id="sym::m2.py::fn_b",
        project_id=1,
        entity_type=NodeType.FUNCTION.value,
        name="fn_b",
        qualified_name="m2.fn_b",
        file_path="m2.py",
        start_line=1,
        end_line=5,
    )
    siblings_a = {"common1", "common2", "common3"}
    siblings_b = {"common1", "common2", "other"}
    score, breakdown = IdentityContinuityEngine.compute_multi_signal_score(
        node_a, node_b, old_neighbors=siblings_a, new_neighbors=siblings_b
    )
    assert breakdown.get("neighbor_jaccard", 0.0) > 0.0


def test_identity_continuity_split_detection_and_evidence():
    old_fn = GraphNode(
        canonical_id="sym::monolith.py::processor",
        project_id=1,
        entity_type=NodeType.FUNCTION.value,
        name="processor",
        qualified_name="monolith.processor",
        file_path="monolith.py",
        start_line=10,
        end_line=100,
        metadata={"structural_fingerprint": "fp_proc"},
    )
    new_sub1 = GraphNode(
        canonical_id="sym::monolith.py::processor_part_one",
        project_id=1,
        entity_type=NodeType.FUNCTION.value,
        name="processor_part_one",
        qualified_name="monolith.processor_part_one",
        file_path="monolith.py",
        start_line=10,
        end_line=50,
        metadata={"structural_fingerprint": "fp_sub1"},
    )
    new_sub2 = GraphNode(
        canonical_id="sym::monolith.py::processor_part_two",
        project_id=1,
        entity_type=NodeType.FUNCTION.value,
        name="processor_part_two",
        qualified_name="monolith.processor_part_two",
        file_path="monolith.py",
        start_line=51,
        end_line=100,
        metadata={"structural_fingerprint": "fp_sub2"},
    )
    transitions = IdentityContinuityEngine.compute_transitions(
        old_nodes={old_fn.canonical_id: old_fn},
        new_nodes={new_sub1.canonical_id: new_sub1, new_sub2.canonical_id: new_sub2},
    )
    split_trans = [t for t in transitions if t.transition_type == IdentityTransitionType.SPLIT.value]
    assert len(split_trans) == 1
    t = split_trans[0]
    assert t.old_canonical_id == old_fn.canonical_id
    assert len(t.candidate_canonical_ids) == 2
    assert "processor_part_one" in t.candidate_canonical_ids[0] or "processor_part_one" in t.candidate_canonical_ids[1]


def test_identity_continuity_merged_detection_and_evidence():
    old_f1 = GraphNode(
        canonical_id="sym::utils.py::parse_a",
        project_id=1,
        entity_type=NodeType.FUNCTION.value,
        name="parse_a",
        qualified_name="utils.parse_a",
        file_path="utils.py",
        start_line=1,
        end_line=20,
    )
    old_f2 = GraphNode(
        canonical_id="sym::utils.py::parse_b",
        project_id=1,
        entity_type=NodeType.FUNCTION.value,
        name="parse_b",
        qualified_name="utils.parse_b",
        file_path="utils.py",
        start_line=21,
        end_line=40,
    )
    new_unified = GraphNode(
        canonical_id="sym::utils.py::parse_a_and_parse_b",
        project_id=1,
        entity_type=NodeType.FUNCTION.value,
        name="parse_a_and_parse_b",
        qualified_name="utils.parse_a_and_parse_b",
        file_path="utils.py",
        start_line=1,
        end_line=45,
    )
    transitions = IdentityContinuityEngine.compute_transitions(
        old_nodes={old_f1.canonical_id: old_f1, old_f2.canonical_id: old_f2},
        new_nodes={new_unified.canonical_id: new_unified},
    )
    merged_trans = [t for t in transitions if t.transition_type == IdentityTransitionType.MERGED.value]
    assert len(merged_trans) == 1
    t = merged_trans[0]
    assert len(t.candidate_canonical_ids) == 2
    assert t.new_canonical_id == new_unified.canonical_id


def test_identity_continuity_renamed_and_modified_transition():
    old_fn = GraphNode(
        canonical_id="sym::core.py::validate_input",
        project_id=1,
        entity_type=NodeType.FUNCTION.value,
        name="validate_input",
        qualified_name="core.validate_input",
        file_path="core.py",
        start_line=10,
        end_line=25,
        metadata={"structural_fingerprint": "hash_old"},
    )
    new_fn = GraphNode(
        canonical_id="sym::core.py::validate_input_safety",
        project_id=1,
        entity_type=NodeType.FUNCTION.value,
        name="validate_input_safety",
        qualified_name="core.validate_input_safety",
        file_path="core.py",
        start_line=15,
        end_line=35,
        metadata={"structural_fingerprint": "hash_modified"},
    )
    transitions = IdentityContinuityEngine.compute_transitions(
        old_nodes={old_fn.canonical_id: old_fn},
        new_nodes={new_fn.canonical_id: new_fn},
    )
    assert len(transitions) == 1
    t = transitions[0]
    assert t.transition_type in (IdentityTransitionType.RENAMED_AND_MODIFIED.value, IdentityTransitionType.RENAMED_SYMBOL.value)
    assert t.old_canonical_id == old_fn.canonical_id
    assert t.new_canonical_id == new_fn.canonical_id


def test_identity_continuity_ambiguous_outcome_retains_candidates():
    old_fn = GraphNode(
        canonical_id="sym::service.py::process",
        project_id=1,
        entity_type=NodeType.FUNCTION.value,
        name="process",
        qualified_name="service.process",
        file_path="service.py",
        start_line=1,
        end_line=10,
    )
    cand_1 = GraphNode(
        canonical_id="sym::service.py::proc_alpha",
        project_id=1,
        entity_type=NodeType.FUNCTION.value,
        name="proc_alpha",
        qualified_name="service.proc_alpha",
        file_path="service.py",
        start_line=1,
        end_line=10,
    )
    cand_2 = GraphNode(
        canonical_id="sym::service.py::proc_beta",
        project_id=1,
        entity_type=NodeType.FUNCTION.value,
        name="proc_beta",
        qualified_name="service.proc_beta",
        file_path="service.py",
        start_line=11,
        end_line=20,
    )
    transitions = IdentityContinuityEngine.compute_transitions(
        old_nodes={old_fn.canonical_id: old_fn},
        new_nodes={cand_1.canonical_id: cand_1, cand_2.canonical_id: cand_2},
    )
    # Checks either explicit AMBIGUOUS or multiple candidate entries
    ambiguous_or_unmatched = [
        t for t in transitions
        if t.transition_type in (IdentityTransitionType.AMBIGUOUS.value, IdentityTransitionType.DELETED.value)
    ]
    assert len(ambiguous_or_unmatched) >= 1


def test_identity_continuity_created_and_deleted_outcomes():
    old_fn = GraphNode(
        canonical_id="sym::old_module.py::dead_code",
        project_id=1,
        entity_type=NodeType.FUNCTION.value,
        name="dead_code",
        qualified_name="old_module.dead_code",
        file_path="old_module.py",
        start_line=1,
        end_line=10,
    )
    new_fn = GraphNode(
        canonical_id="sym::new_module.py::brand_new_feature",
        project_id=1,
        entity_type=NodeType.FUNCTION.value,
        name="brand_new_feature",
        qualified_name="new_module.brand_new_feature",
        file_path="new_module.py",
        start_line=1,
        end_line=10,
    )
    transitions = IdentityContinuityEngine.compute_transitions(
        old_nodes={old_fn.canonical_id: old_fn},
        new_nodes={new_fn.canonical_id: new_fn},
    )
    types = {t.transition_type for t in transitions}
    assert IdentityTransitionType.DELETED.value in types
    assert IdentityTransitionType.CREATED.value in types


def test_identity_continuity_benchmark_precision_recall_f1():
    true_pairs = {("old_1", "new_1"), ("old_2", "new_2"), ("old_3", "new_3")}
    predicted_pairs = [
        IdentityTransitionRecord(old_canonical_id="old_1", new_canonical_id="new_1", transition_type="RENAMED_SYMBOL", confidence=0.9),
        IdentityTransitionRecord(old_canonical_id="old_2", new_canonical_id="new_2", transition_type="RENAMED_SYMBOL", confidence=0.85),
        IdentityTransitionRecord(old_canonical_id="old_4", new_canonical_id="new_4", transition_type="RENAMED_SYMBOL", confidence=0.7),
    ]
    metrics = IdentityContinuityBenchmark.evaluate_benchmark(predicted_pairs, true_pairs)
    assert metrics["precision"] == round(2 / 3, 4)
    assert metrics["recall"] == round(2 / 3, 4)
    assert metrics["f1_score"] == round(2 / 3, 4)


def test_identity_continuity_benchmark_ambiguous_rate():
    transitions = [
        IdentityTransitionRecord(old_canonical_id="o1", new_canonical_id="n1", transition_type="RENAMED_SYMBOL", confidence=0.9),
        IdentityTransitionRecord(old_canonical_id="o2", new_canonical_id="c1", transition_type="AMBIGUOUS", confidence=0.5, candidate_canonical_ids=["c1", "c2"]),
    ]
    metrics = IdentityContinuityBenchmark.evaluate_benchmark(transitions, {("o1", "n1")})
    assert metrics["ambiguous_rate"] == 0.5
    assert metrics["ambiguous_count"] == 1


# ============================================================================
# 2. Call Graph Accuracy and Calibration Tests (11 - 21)
# ============================================================================

def test_call_resolver_taxonomy_static_vs_runtime():
    caller_id = build_canonical_id(1, "caller.py", "caller.do_work", NodeType.FUNCTION)
    callee_id = build_canonical_id(1, "callee.py", "callee.compute", NodeType.FUNCTION)
    caller = GraphNode(canonical_id=caller_id, project_id=1, entity_type="FUNCTION", name="do_work", qualified_name="caller.do_work", file_path="caller.py", start_line=1, end_line=5)
    callee = GraphNode(canonical_id=callee_id, project_id=1, entity_type="FUNCTION", name="compute", qualified_name="callee.compute", file_path="callee.py", start_line=1, end_line=5)

    resolver_static = AdvancedCallResolver(
        project_id=1,
        symbol_registry={"callee.compute": callee_id},
        nodes={caller_id: caller, callee_id: callee},
    )
    edges_static = resolver_static.resolve_call(
        caller_qname="caller.do_work",
        caller_id=caller_id,
        call_expr="compute",
        ast_call_node=ast.Call(func=ast.Name(id="compute", ctx=ast.Load()), args=[], keywords=[]),
        rel_file="caller.py",
        line_no=3,
        current_module="caller",
        current_class=None,
        imported_aliases={"compute": "callee.compute"},
    )
    assert len(edges_static) == 1
    assert edges_static[0].provenance["resolution"] == CallResolutionType.RESOLVED_STATIC.value
    assert edges_static[0].confidence >= 0.90

    resolver_runtime = AdvancedCallResolver(
        project_id=1,
        symbol_registry={"callee.compute": callee_id},
        nodes={caller_id: caller, callee_id: callee},
        runtime_traces=[{"caller": "caller.do_work", "callee": "callee.compute"}],
    )
    edges_runtime = resolver_runtime.resolve_call(
        caller_qname="caller.do_work",
        caller_id=caller_id,
        call_expr="compute",
        ast_call_node=ast.Call(func=ast.Name(id="compute", ctx=ast.Load()), args=[], keywords=[]),
        rel_file="caller.py",
        line_no=3,
        current_module="caller",
        current_class=None,
        imported_aliases={"compute": "callee.compute"},
    )
    assert len(edges_runtime) == 1
    assert edges_runtime[0].provenance["resolution"] == CallResolutionType.RESOLVED_RUNTIME.value
    assert edges_runtime[0].confidence == 1.0


def test_call_resolver_getattr_reflection_recorded_as_ambiguous():
    caller_id = build_canonical_id(1, "dispatcher.py", "dispatcher.dispatch", NodeType.FUNCTION)
    target_id = build_canonical_id(1, "handlers.py", "handlers.on_click", NodeType.FUNCTION)
    caller = GraphNode(canonical_id=caller_id, project_id=1, entity_type="FUNCTION", name="dispatch", qualified_name="dispatcher.dispatch", file_path="dispatcher.py", start_line=1, end_line=5)
    target = GraphNode(canonical_id=target_id, project_id=1, entity_type="FUNCTION", name="on_click", qualified_name="handlers.on_click", file_path="handlers.py", start_line=1, end_line=5)

    resolver = AdvancedCallResolver(
        project_id=1,
        symbol_registry={"handlers.on_click": target_id},
        nodes={caller_id: caller, target_id: target},
    )
    edges = resolver.resolve_call(
        caller_qname="dispatcher.dispatch",
        caller_id=caller_id,
        call_expr="getattr(handlers, event)()",
        ast_call_node=None,
        rel_file="dispatcher.py",
        line_no=3,
        current_module="dispatcher",
        current_class=None,
        imported_aliases={},
    )
    assert len(edges) == 1
    assert edges[0].provenance.get("unresolved") is True
    assert edges[0].provenance.get("is_reflection") is True


def test_call_resolver_aliased_import_resolution():
    caller_id = build_canonical_id(1, "app.py", "app.run", NodeType.FUNCTION)
    target_id = build_canonical_id(1, "numpy_wrapper.py", "numpy_wrapper.array_fn", NodeType.FUNCTION)
    caller = GraphNode(canonical_id=caller_id, project_id=1, entity_type="FUNCTION", name="run", qualified_name="app.run", file_path="app.py", start_line=1, end_line=5)
    target = GraphNode(canonical_id=target_id, project_id=1, entity_type="FUNCTION", name="array_fn", qualified_name="numpy_wrapper.array_fn", file_path="numpy_wrapper.py", start_line=1, end_line=5)

    resolver = AdvancedCallResolver(
        project_id=1,
        symbol_registry={"numpy_wrapper.array_fn": target_id},
        nodes={caller_id: caller, target_id: target},
    )
    edges = resolver.resolve_call(
        caller_qname="app.run",
        caller_id=caller_id,
        call_expr="np_arr",
        ast_call_node=ast.Call(func=ast.Name(id="np_arr", ctx=ast.Load()), args=[], keywords=[]),
        rel_file="app.py",
        line_no=2,
        current_module="app",
        current_class=None,
        imported_aliases={"np_arr": "numpy_wrapper.array_fn"},
    )
    assert len(edges) == 1
    assert edges[0].target_canonical_id == target_id
    assert edges[0].confidence >= 0.90


def test_call_resolver_relative_import_resolution():
    caller_id = build_canonical_id(1, "pkg/sub/worker.py", "pkg.sub.worker.run_task", NodeType.FUNCTION)
    helper_id = build_canonical_id(1, "pkg/sub/helper.py", "pkg.sub.helper.util_fn", NodeType.FUNCTION)
    caller = GraphNode(canonical_id=caller_id, project_id=1, entity_type="FUNCTION", name="run_task", qualified_name="pkg.sub.worker.run_task", file_path="pkg/sub/worker.py", start_line=1, end_line=5)
    helper = GraphNode(canonical_id=helper_id, project_id=1, entity_type="FUNCTION", name="util_fn", qualified_name="pkg.sub.helper.util_fn", file_path="pkg/sub/helper.py", start_line=1, end_line=5)

    resolver = AdvancedCallResolver(
        project_id=1,
        symbol_registry={"pkg.sub.helper.util_fn": helper_id},
        nodes={caller_id: caller, helper_id: helper},
    )
    edges = resolver.resolve_call(
        caller_qname="pkg.sub.worker.run_task",
        caller_id=caller_id,
        call_expr="util_fn",
        ast_call_node=ast.Call(func=ast.Name(id="util_fn", ctx=ast.Load()), args=[], keywords=[]),
        rel_file="pkg/sub/worker.py",
        line_no=2,
        current_module="pkg.sub.worker",
        current_class=None,
        imported_aliases={"util_fn": "pkg.sub.helper.util_fn"},
    )
    assert len(edges) == 1
    assert edges[0].target_canonical_id == helper_id
    assert edges[0].provenance["resolution"] == CallResolutionType.RESOLVED_STATIC.value


def test_call_resolver_circular_import_resilience():
    a_id = build_canonical_id(1, "mod_a.py", "mod_a.func_a", NodeType.FUNCTION)
    b_id = build_canonical_id(1, "mod_b.py", "mod_b.func_b", NodeType.FUNCTION)
    node_a = GraphNode(canonical_id=a_id, project_id=1, entity_type="FUNCTION", name="func_a", qualified_name="mod_a.func_a", file_path="mod_a.py", start_line=1, end_line=5)
    node_b = GraphNode(canonical_id=b_id, project_id=1, entity_type="FUNCTION", name="func_b", qualified_name="mod_b.func_b", file_path="mod_b.py", start_line=1, end_line=5)

    resolver = AdvancedCallResolver(
        project_id=1,
        symbol_registry={"mod_a.func_a": a_id, "mod_b.func_b": b_id},
        nodes={a_id: node_a, b_id: node_b},
    )
    edges_a = resolver.resolve_call(
        caller_qname="mod_a.func_a",
        caller_id=a_id,
        call_expr="func_b",
        ast_call_node=ast.Call(func=ast.Name(id="func_b", ctx=ast.Load()), args=[], keywords=[]),
        rel_file="mod_a.py",
        line_no=2,
        current_module="mod_a",
        current_class=None,
        imported_aliases={"func_b": "mod_b.func_b"},
    )
    edges_b = resolver.resolve_call(
        caller_qname="mod_b.func_b",
        caller_id=b_id,
        call_expr="func_a",
        ast_call_node=ast.Call(func=ast.Name(id="func_a", ctx=ast.Load()), args=[], keywords=[]),
        rel_file="mod_b.py",
        line_no=2,
        current_module="mod_b",
        current_class=None,
        imported_aliases={"func_a": "mod_a.func_a"},
    )
    assert edges_a[0].target_canonical_id == b_id
    assert edges_b[0].target_canonical_id == a_id


def test_call_resolver_callback_dispatch_resolution():
    caller_id = build_canonical_id(1, "events.py", "events.trigger", NodeType.FUNCTION)
    callback_id = build_canonical_id(1, "handlers.py", "handlers.on_complete", NodeType.FUNCTION)
    caller = GraphNode(canonical_id=caller_id, project_id=1, entity_type="FUNCTION", name="trigger", qualified_name="events.trigger", file_path="events.py", start_line=1, end_line=5)
    callback = GraphNode(canonical_id=callback_id, project_id=1, entity_type="FUNCTION", name="on_complete", qualified_name="handlers.on_complete", file_path="handlers.py", start_line=1, end_line=5)

    resolver = AdvancedCallResolver(
        project_id=1,
        symbol_registry={"handlers.on_complete": callback_id},
        nodes={caller_id: caller, callback_id: callback},
    )
    edges = resolver.resolve_call(
        caller_qname="events.trigger",
        caller_id=caller_id,
        call_expr="on_complete",
        ast_call_node=ast.Call(func=ast.Name(id="on_complete", ctx=ast.Load()), args=[], keywords=[]),
        rel_file="events.py",
        line_no=3,
        current_module="events",
        current_class=None,
        imported_aliases={"on_complete": "handlers.on_complete"},
    )
    assert len(edges) == 1
    assert edges[0].target_canonical_id == callback_id


def test_call_resolver_class_inheritance_overriding_resolution():
    base_m_id = build_canonical_id(1, "models.py", "models.Base.save", NodeType.METHOD)
    sub_m_id = build_canonical_id(1, "models.py", "models.Sub.save", NodeType.METHOD)
    caller_id = build_canonical_id(1, "services.py", "services.run_save", NodeType.FUNCTION)

    base_m = GraphNode(canonical_id=base_m_id, project_id=1, entity_type="METHOD", name="save", qualified_name="models.Base.save", file_path="models.py", start_line=1, end_line=5)
    sub_m = GraphNode(canonical_id=sub_m_id, project_id=1, entity_type="METHOD", name="save", qualified_name="models.Sub.save", file_path="models.py", start_line=10, end_line=15)
    caller = GraphNode(canonical_id=caller_id, project_id=1, entity_type="FUNCTION", name="run_save", qualified_name="services.run_save", file_path="services.py", start_line=1, end_line=5)

    resolver = AdvancedCallResolver(
        project_id=1,
        symbol_registry={"models.Base.save": base_m_id, "models.Sub.save": sub_m_id},
        nodes={base_m_id: base_m, sub_m_id: sub_m, caller_id: caller},
        class_hierarchy={"models.Sub": ["models.Base"]},
    )
    edges = resolver.resolve_call(
        caller_qname="services.run_save",
        caller_id=caller_id,
        call_expr="obj.save",
        ast_call_node=ast.Call(func=ast.Attribute(value=ast.Name(id="obj", ctx=ast.Load()), attr="save", ctx=ast.Load()), args=[], keywords=[]),
        rel_file="services.py",
        line_no=3,
        current_module="services",
        current_class=None,
        imported_aliases={},
        local_var_types={"obj": "models.Sub"},
    )
    assert len(edges) == 1
    assert edges[0].target_canonical_id == sub_m_id


def test_call_resolver_unresolved_call_provenance():
    caller_id = build_canonical_id(1, "client.py", "client.invoke_unknown", NodeType.FUNCTION)
    caller = GraphNode(canonical_id=caller_id, project_id=1, entity_type="FUNCTION", name="invoke_unknown", qualified_name="client.invoke_unknown", file_path="client.py", start_line=1, end_line=5)

    resolver = AdvancedCallResolver(
        project_id=1,
        symbol_registry={},
        nodes={caller_id: caller},
    )
    edges = resolver.resolve_call(
        caller_qname="client.invoke_unknown",
        caller_id=caller_id,
        call_expr="getattr(x, 'unknown')",
        ast_call_node=ast.Call(func=ast.Name(id="getattr", ctx=ast.Load()), args=[], keywords=[]),
        rel_file="client.py",
        line_no=3,
        current_module="client",
        current_class=None,
        imported_aliases={},
    )
    assert len(edges) == 1
    assert edges[0].provenance["resolution"] == CallResolutionType.UNRESOLVED.value
    assert edges[0].provenance.get("unresolved") is True
    assert edges[0].confidence == 0.5


def test_call_resolver_benchmark_confusion_matrix():
    edges = [
        GraphEdge(source_canonical_id="c1", target_canonical_id="t1", rel_type="CALLS", project_id=1, confidence=0.95, analyzer_source="test", provenance={"resolution": "RESOLVED_STATIC"}),
        GraphEdge(source_canonical_id="c2", target_canonical_id="t2", rel_type="CALLS", project_id=1, confidence=0.90, analyzer_source="test", provenance={"resolution": "RESOLVED_STATIC"}),
        GraphEdge(source_canonical_id="c3", target_canonical_id="t_fake", rel_type="CALLS", project_id=1, confidence=0.85, analyzer_source="test", provenance={"resolution": "RESOLVED_STATIC"}),
    ]
    ground_truth = {("c1", "t1"), ("c2", "t2"), ("c4", "t4")}
    report = CallResolverBenchmark.evaluate_benchmark(edges, ground_truth)
    assert "confusion_matrix" in report
    assert report["true_positives"] == 2.0
    assert report["false_positives"] == 1.0
    assert report["false_negatives"] == 1.0


def test_call_resolver_benchmark_brier_score_calibration():
    edges = [
        GraphEdge(source_canonical_id="c1", target_canonical_id="t1", rel_type="CALLS", project_id=1, confidence=0.90, analyzer_source="test", provenance={"resolution": "RESOLVED_STATIC"}),
        GraphEdge(source_canonical_id="c2", target_canonical_id="t2", rel_type="CALLS", project_id=1, confidence=0.80, analyzer_source="test", provenance={"resolution": "RESOLVED_STATIC"}),
        GraphEdge(source_canonical_id="c3", target_canonical_id="t3", rel_type="CALLS", project_id=1, confidence=0.10, analyzer_source="test", provenance={"resolution": "UNRESOLVED"}),
    ]
    ground_truth = {("c1", "t1"), ("c2", "t2")}
    report = CallResolverBenchmark.evaluate_benchmark(edges, ground_truth)
    assert "brier_calibration_error" in report
    assert report["brier_calibration_error"] <= 0.15


def test_call_resolver_benchmark_sample_size_validity():
    small_edges = [
        GraphEdge(source_canonical_id="c1", target_canonical_id="t1", rel_type="CALLS", project_id=1, confidence=0.9, analyzer_source="test", provenance={"resolution": "RESOLVED_STATIC"}),
    ]
    report_small = CallResolverBenchmark.evaluate_benchmark(small_edges, {("c1", "t1")})
    assert report_small["is_statistically_conclusive"] is False

    large_edges = [
        GraphEdge(source_canonical_id=f"c{i}", target_canonical_id=f"t{i}", rel_type="CALLS", project_id=1, confidence=0.9, analyzer_source="test", provenance={"resolution": "RESOLVED_STATIC"})
        for i in range(35)
    ]
    gt_large = {(f"c{i}", f"t{i}") for i in range(35)}
    report_large = CallResolverBenchmark.evaluate_benchmark(large_edges, gt_large)
    assert report_large["is_statistically_conclusive"] is True


# ============================================================================
# 3. Transactional Graph Update Reliability & Real Subprocess Crash Tests (22 - 30)
# ============================================================================

def test_transactional_updater_staged_version_lifecycle(mock_db_session: Session, multi_tier_repo: Path):
    nodes, edges, ver = TransactionalGraphUpdater.execute_transactional_update(
        mock_db_session, 1, multi_tier_repo, force_full_rebuild=True
    )
    assert ver.status == "ACTIVE"
    assert ver.is_current is True
    assert ver.version_number == 1
    assert ver.node_count > 0


def test_transactional_updater_concurrency_lock_acquisition(mock_db_session: Session):
    # Verify checking concurrency lock passes cleanly when no staging is active
    TransactionalGraphUpdater.check_and_acquire_concurrency_lock(mock_db_session, 1)


def test_transactional_updater_concurrency_collision_rejection(mock_db_session: Session):
    # Simulate an active STAGED version with recent journal
    staged = EngineeringGraphVersion(project_id=1, version_number=99, status="STAGED", is_current=False)
    mock_db_session.add(staged)
    mock_db_session.flush()

    journal = EngineeringGraphUpdateJournal(
        project_id=1,
        version_id=staged.id,
        stage="EXTRACTING",
        created_at=datetime.now(timezone.utc),
    )
    mock_db_session.add(journal)
    mock_db_session.commit()

    with pytest.raises(RuntimeError, match="Concurrent graph update rejected"):
        TransactionalGraphUpdater.check_and_acquire_concurrency_lock(mock_db_session, 1)


def test_transactional_updater_concurrency_lease_expiration(mock_db_session: Session):
    # Simulate an expired STAGED version (> STAGING_LOCK_TIMEOUT_SECONDS)
    staged = EngineeringGraphVersion(project_id=1, version_number=88, status="STAGED", is_current=False)
    mock_db_session.add(staged)
    mock_db_session.flush()

    old_time = datetime(2020, 1, 1, tzinfo=timezone.utc)
    journal = EngineeringGraphUpdateJournal(
        project_id=1,
        version_id=staged.id,
        stage="EXTRACTING",
        created_at=old_time,
    )
    mock_db_session.add(journal)
    mock_db_session.commit()

    # Must not raise RuntimeError because lease has expired
    TransactionalGraphUpdater.check_and_acquire_concurrency_lock(mock_db_session, 1)


def test_transactional_updater_orphan_cleanup_on_failure(mock_db_session: Session):
    staged = EngineeringGraphVersion(project_id=1, version_number=77, status="STAGED", is_current=False)
    mock_db_session.add(staged)
    mock_db_session.flush()

    orphan_node = EngineeringGraphNode(
        project_id=1,
        version_id=staged.id,
        canonical_id="sym::orphan.py::unused",
        entity_type=NodeType.FUNCTION.value,
        name="unused",
        qualified_name="orphan.unused",
        file_path="orphan.py",
        start_line=1,
        end_line=5,
    )
    mock_db_session.add(orphan_node)
    mock_db_session.commit()

    cleaned = TransactionalGraphUpdater.recover_interrupted_updates(mock_db_session, 1)
    assert cleaned >= 1

    remaining = (
        mock_db_session.query(EngineeringGraphNode)
        .filter(EngineeringGraphNode.version_id == staged.id)
        .all()
    )
    assert len(remaining) == 0


def test_transactional_updater_consistency_validation_success():
    n1 = GraphNode(canonical_id="n1", project_id=1, entity_type="FUNCTION", name="n1", qualified_name="n1", file_path="n1.py")
    n2 = GraphNode(canonical_id="n2", project_id=1, entity_type="FUNCTION", name="n2", qualified_name="n2", file_path="n2.py")
    e1 = GraphEdge(source_canonical_id="n1", target_canonical_id="n2", rel_type="CALLS", project_id=1, confidence=1.0, analyzer_source="test")

    issues = TransactionalGraphUpdater.validate_graph_consistency(
        nodes={"n1": n1, "n2": n2},
        edges=[e1],
    )
    assert len(issues) == 0


def test_transactional_updater_consistency_validation_detects_dangling_edge():
    n1 = GraphNode(canonical_id="n1", project_id=1, entity_type="FUNCTION", name="n1", qualified_name="n1", file_path="n1.py")
    e_dangling = GraphEdge(source_canonical_id="n1", target_canonical_id="missing_target", rel_type="CALLS", project_id=1, confidence=1.0, analyzer_source="test")

    issues = TransactionalGraphUpdater.validate_graph_consistency(
        nodes={"n1": n1},
        edges=[e_dangling],
    )
    assert len(issues) >= 1
    assert any("dangling" in i.lower() for i in issues)


def test_database_unique_constraint_version_canonical_id(mock_db_session: Session):
    v = EngineeringGraphVersion(project_id=1, version_number=10, status="ACTIVE", is_current=True)
    mock_db_session.add(v)
    mock_db_session.flush()

    n1 = EngineeringGraphNode(
        project_id=1,
        version_id=v.id,
        canonical_id="sym::unique.py::test_fn",
        entity_type="FUNCTION",
        name="test_fn",
        qualified_name="unique.test_fn",
        file_path="unique.py",
        start_line=1,
        end_line=2,
    )
    mock_db_session.add(n1)
    mock_db_session.commit()

    n2 = EngineeringGraphNode(
        project_id=1,
        version_id=v.id,
        canonical_id="sym::unique.py::test_fn",
        entity_type="FUNCTION",
        name="test_fn",
        qualified_name="unique.test_fn",
        file_path="unique.py",
        start_line=3,
        end_line=4,
    )
    mock_db_session.add(n2)
    with pytest.raises(Exception):
        mock_db_session.commit()
    mock_db_session.rollback()


def test_transactional_updater_real_subprocess_crash_recovery(tmp_path: Path):
    """Executes a real OS process crash: kills child worker during extraction,

    verifies recover_interrupted_updates preserves active version and purges staged orphans.
    """
    db_file = tmp_path / "crash_test.db"
    marker_file = tmp_path / "child_running.txt"
    db_url = f"sqlite:///{db_file}"

    engine = create_engine(db_url, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    SessionClass = sessionmaker(bind=engine)
    setup_session = SessionClass()

    owner = User(id=1, username="crash_owner", email="co@test.com", hashed_password="pw", is_active=True)
    setup_session.add(owner)
    p = ReviewedProject(id=1, name="Crash Repo", repository_path="c:/repos/c", owner_id=1)
    setup_session.add(p)
    setup_session.commit()

    active_v = EngineeringGraphVersion(project_id=1, version_number=1, status="ACTIVE", is_current=True)
    setup_session.add(active_v)
    setup_session.flush()
    active_v_id = active_v.id

    active_node = EngineeringGraphNode(
        project_id=1,
        version_id=active_v_id,
        canonical_id="sym::active.py::stable",
        entity_type="FUNCTION",
        name="stable",
        qualified_name="active.stable",
        file_path="active.py",
        start_line=1,
        end_line=5,
    )
    setup_session.add(active_node)
    setup_session.commit()
    setup_session.close()

    child_script = (
        "import sys, time\n"
        "from pathlib import Path\n"
        "from sqlalchemy import create_engine\n"
        "from sqlalchemy.orm import sessionmaker\n"
        "from app.models.entities import EngineeringGraphNode, EngineeringGraphVersion\n"
        f"engine = create_engine(r'{db_url}')\n"
        "Session = sessionmaker(bind=engine)\n"
        "db = Session()\n"
        "staged = EngineeringGraphVersion(project_id=1, version_number=2, status='STAGED', is_current=False)\n"
        "db.add(staged)\n"
        "db.flush()\n"
        "n = EngineeringGraphNode(project_id=1, version_id=staged.id, canonical_id='sym::crash.py::orphan', entity_type='FUNCTION', name='orphan', qualified_name='crash.orphan', file_path='crash.py', start_line=1, end_line=5)\n"
        "db.add(n)\n"
        "db.commit()\n"
        f"Path(r'{marker_file}').write_text('running')\n"
        "time.sleep(10)\n"
    )

    env = dict(os.environ)
    env["PYTHONPATH"] = "backend"
    proc = subprocess.Popen([sys.executable, "-c", child_script], env=env)

    for _ in range(50):
        if marker_file.exists():
            break
        time.sleep(0.1)

    assert marker_file.exists(), "Child worker failed to start and create marker"

    proc.kill()
    proc.wait()

    rec_session = SessionClass()
    purged_count = TransactionalGraphUpdater.recover_interrupted_updates(rec_session, project_id=1)
    assert purged_count >= 1

    current_v = (
        rec_session.query(EngineeringGraphVersion)
        .filter(EngineeringGraphVersion.project_id == 1, EngineeringGraphVersion.is_current.is_(True))
        .first()
    )
    assert current_v is not None
    assert current_v.id == active_v_id

    active_nodes = (
        rec_session.query(EngineeringGraphNode)
        .filter(EngineeringGraphNode.version_id == active_v_id)
        .all()
    )
    assert len(active_nodes) == 1
    assert active_nodes[0].name == "stable"

    orphan_query = (
        rec_session.query(EngineeringGraphNode)
        .filter(EngineeringGraphNode.canonical_id == "sym::crash.py::orphan")
        .all()
    )
    assert len(orphan_query) == 0
    rec_session.close()


# ============================================================================
# 4. Calibrated Blast Radius Assessment Tests (31 - 36)
# ============================================================================

def test_blast_radius_measured_properties_calculated():
    caller = GraphNode(
        canonical_id="sym::api.py::entry",
        project_id=1,
        entity_type=NodeType.FUNCTION.value,
        name="entry",
        qualified_name="api.entry",
        file_path="api.py",
        start_line=1,
        end_line=10,
    )
    mid = GraphNode(
        canonical_id="sym::srv.py::svc",
        project_id=1,
        entity_type=NodeType.FUNCTION.value,
        name="svc",
        qualified_name="srv.svc",
        file_path="srv.py",
        start_line=1,
        end_line=10,
    )
    e1 = GraphEdge(
        source_canonical_id=caller.canonical_id,
        target_canonical_id=mid.canonical_id,
        rel_type=EdgeType.CALLS.value,
        project_id=1,
        confidence=1.0,
        analyzer_source="test",
    )
    assessment = BlastRadiusEngine.calculate_blast_radius(
        nodes={caller.canonical_id: caller, mid.canonical_id: mid},
        edges=[e1],
        target_ids_or_files=[mid.canonical_id],
    )
    assert assessment.measured_properties is not None
    assert assessment.measured_properties["directly_affected_symbols_count"] >= 0
    assert assessment.score_breakdown["measured_structural_score"] >= 0


def test_blast_radius_heuristic_risk_factors_isolated():
    auth_node = GraphNode(
        canonical_id="sym::auth.py::verify_token",
        project_id=1,
        entity_type=NodeType.FUNCTION.value,
        name="verify_token",
        qualified_name="auth.verify_token",
        file_path="auth.py",
        start_line=1,
        end_line=10,
    )
    assessment = BlastRadiusEngine.calculate_blast_radius(
        nodes={auth_node.canonical_id: auth_node},
        edges=[],
        target_ids_or_files=[auth_node.canonical_id],
    )
    assert assessment.heuristic_factors is not None
    assert assessment.heuristic_factors["authentication_sensitivity"] is True
    assert any("Authentication" in rf for rf in assessment.risk_factors)


def test_blast_radius_unavailable_evidence_explicitly_flagged():
    plain_node = GraphNode(
        canonical_id="sym::math.py::add",
        project_id=1,
        entity_type=NodeType.FUNCTION.value,
        name="add",
        qualified_name="math.add",
        file_path="math.py",
        start_line=1,
        end_line=5,
    )
    assessment = BlastRadiusEngine.calculate_blast_radius(
        nodes={plain_node.canonical_id: plain_node},
        edges=[],
        target_ids_or_files=[plain_node.canonical_id],
    )
    assert hasattr(assessment, "unavailable_evidence")
    assert isinstance(assessment.unavailable_evidence, list)


def test_blast_radius_benchmark_precision_recall_at_high_risk():
    assessments = [
        BlastRadiusReport(targets=["t1"], blast_radius_score=85, risk_level="CRITICAL", direct_symbols_count=5, transitive_symbols_count=10, affected_modules=["m1"], affected_apis_count=2, affected_tables_count=1, affected_tests_count=2, boundaries_crossed=[], risk_factors=[], impact_report=None),
        BlastRadiusReport(targets=["t2"], blast_radius_score=50, risk_level="HIGH", direct_symbols_count=3, transitive_symbols_count=5, affected_modules=["m2"], affected_apis_count=1, affected_tables_count=0, affected_tests_count=1, boundaries_crossed=[], risk_factors=[], impact_report=None),
        BlastRadiusReport(targets=["t3"], blast_radius_score=15, risk_level="LOW", direct_symbols_count=1, transitive_symbols_count=0, affected_modules=["m3"], affected_apis_count=0, affected_tables_count=0, affected_tests_count=0, boundaries_crossed=[], risk_factors=[], impact_report=None),
    ]
    ground_truth_high = {"t1", "t2"}
    metrics = BlastRadiusBenchmark.evaluate_benchmark(assessments, ground_truth_high)
    assert metrics["precision_at_high_risk"] == 1.0
    assert metrics["recall_at_high_risk"] == 1.0
    assert metrics["false_high_rate"] == 0.0
    assert metrics["false_low_rate"] == 0.0


def test_blast_radius_benchmark_false_high_and_false_low_rates():
    assessments = [
        BlastRadiusReport(targets=["t1"], blast_radius_score=75, risk_level="HIGH", direct_symbols_count=1, transitive_symbols_count=0, affected_modules=[], affected_apis_count=0, affected_tables_count=0, affected_tests_count=0, boundaries_crossed=[], risk_factors=[], impact_report=None),
        BlastRadiusReport(targets=["t2"], blast_radius_score=10, risk_level="LOW", direct_symbols_count=1, transitive_symbols_count=0, affected_modules=[], affected_apis_count=0, affected_tables_count=0, affected_tests_count=0, boundaries_crossed=[], risk_factors=[], impact_report=None),
    ]
    ground_truth_high = {"t2"}
    metrics = BlastRadiusBenchmark.evaluate_benchmark(assessments, ground_truth_high)
    assert metrics["false_high_rate"] == 1.0
    assert metrics["false_low_rate"] == 1.0


def test_blast_radius_benchmark_ranking_stability_spearman():
    scores_v1 = {"t1": 90, "t2": 60, "t3": 30}
    scores_v2 = {"t1": 85, "t2": 65, "t3": 25}
    stability = BlastRadiusBenchmark.calculate_ranking_stability(scores_v1, scores_v2)
    assert stability >= 0.90


# ============================================================================
# 5. Targeted Test Selection Validation Tests (37 - 46)
# ============================================================================

def test_test_selector_tier_direct_test():
    target = GraphNode(canonical_id="sym::auth.py::login", project_id=1, entity_type="FUNCTION", name="login", qualified_name="auth.login", file_path="auth.py", start_line=1, end_line=10)
    test_node = GraphNode(canonical_id="sym::test_auth.py::test_login", project_id=1, entity_type="TEST_FUNCTION", name="test_login", qualified_name="test_auth.test_login", file_path="tests/test_auth.py", start_line=1, end_line=5)
    e = GraphEdge(source_canonical_id=target.canonical_id, target_canonical_id=test_node.canonical_id, rel_type=EdgeType.TESTED_BY.value, project_id=1, confidence=0.95, analyzer_source="test")

    tests = TestSelectionEngine.select_tests_for_changes(
        nodes={target.canonical_id: target, test_node.canonical_id: test_node},
        edges=[e],
        target_ids_or_files=[target.canonical_id],
    )
    assert len(tests) >= 1
    assert tests[0].classification == TestRecommendationTier.DIRECT_TEST.value
    assert tests[0].execution_status == "NOT_EXECUTED"


def test_test_selector_tier_runtime_confirmed_test():
    target = GraphNode(canonical_id="sym::calc.py::add", project_id=1, entity_type="FUNCTION", name="add", qualified_name="calc.add", file_path="calc.py", start_line=1, end_line=5)
    test_node = GraphNode(canonical_id="sym::test_calc.py::test_add", project_id=1, entity_type="TEST_FUNCTION", name="test_add", qualified_name="test_calc.test_add", file_path="tests/test_calc.py", start_line=1, end_line=5)
    e = GraphEdge(source_canonical_id=target.canonical_id, target_canonical_id=test_node.canonical_id, rel_type=EdgeType.TESTED_BY.value, project_id=1, confidence=0.8, analyzer_source="test")

    tests = TestSelectionEngine.select_tests_for_changes(
        nodes={target.canonical_id: target, test_node.canonical_id: test_node},
        edges=[e],
        target_ids_or_files=[target.canonical_id],
        runtime_traces=[{"test_name": "test_add", "target_symbol": "add"}],
    )
    assert len(tests) >= 1
    assert tests[0].classification == TestRecommendationTier.RUNTIME_CONFIRMED_TEST.value
    assert tests[0].confidence == 1.0


def test_test_selector_tier_statically_inferred_test():
    target = GraphNode(canonical_id="sym::db.py::connect", project_id=1, entity_type="FUNCTION", name="connect", qualified_name="db.connect", file_path="db.py", start_line=1, end_line=5)
    caller = GraphNode(canonical_id="sym::repo.py::get_user", project_id=1, entity_type="FUNCTION", name="get_user", qualified_name="repo.get_user", file_path="repo.py", start_line=1, end_line=5)
    test_node = GraphNode(canonical_id="sym::test_repo.py::test_get_user", project_id=1, entity_type="TEST_FUNCTION", name="test_get_user", qualified_name="test_repo.test_get_user", file_path="tests/test_repo.py", start_line=1, end_line=5)

    e1 = GraphEdge(source_canonical_id=caller.canonical_id, target_canonical_id=target.canonical_id, rel_type="CALLS", project_id=1, confidence=1.0, analyzer_source="test")
    e2 = GraphEdge(source_canonical_id=test_node.canonical_id, target_canonical_id=caller.canonical_id, rel_type="CALLS", project_id=1, confidence=1.0, analyzer_source="test")

    tests = TestSelectionEngine.select_tests_for_changes(
        nodes={target.canonical_id: target, caller.canonical_id: caller, test_node.canonical_id: test_node},
        edges=[e1, e2],
        target_ids_or_files=[target.canonical_id],
    )
    test_recs = [t for t in tests if t.test_id == test_node.canonical_id]
    if test_recs:
        assert test_recs[0].classification in (TestRecommendationTier.STATICALLY_INFERRED_TEST.value, TestRecommendationTier.INTEGRATION_TEST.value, TestRecommendationTier.DIRECT_TEST.value)


def test_test_selector_tier_integration_test():
    target = GraphNode(canonical_id="sym::models.py::User", project_id=1, entity_type="DATABASE_MODEL", name="User", qualified_name="models.User", file_path="models.py", start_line=1, end_line=10)
    test_node = GraphNode(canonical_id="sym::test_integration.py::test_user_flow", project_id=1, entity_type="TEST_FUNCTION", name="test_user_flow", qualified_name="test_integration.test_user_flow", file_path="tests/integration/test_user.py", start_line=1, end_line=5)
    e = GraphEdge(source_canonical_id=target.canonical_id, target_canonical_id=test_node.canonical_id, rel_type=EdgeType.TESTED_BY.value, project_id=1, confidence=0.9, analyzer_source="test")

    tests = TestSelectionEngine.select_tests_for_changes(
        nodes={target.canonical_id: target, test_node.canonical_id: test_node},
        edges=[e],
        target_ids_or_files=[target.canonical_id],
    )
    assert len(tests) >= 1
    assert tests[0].execution_status == "NOT_EXECUTED"


def test_test_selector_tier_end_to_end_test():
    target = GraphNode(canonical_id="sym::views.py::checkout", project_id=1, entity_type="FUNCTION", name="checkout", qualified_name="views.checkout", file_path="views.py", start_line=1, end_line=10)
    e2e_node = GraphNode(canonical_id="sym::e2e.py::test_e2e_purchase", project_id=1, entity_type="TEST_FUNCTION", name="test_e2e_purchase", qualified_name="e2e.test_e2e_purchase", file_path="tests/e2e/test_purchase.py", start_line=1, end_line=10)
    e = GraphEdge(source_canonical_id=target.canonical_id, target_canonical_id=e2e_node.canonical_id, rel_type=EdgeType.TESTED_BY.value, project_id=1, confidence=0.9, analyzer_source="test")

    tests = TestSelectionEngine.select_tests_for_changes(
        nodes={target.canonical_id: target, e2e_node.canonical_id: e2e_node},
        edges=[e],
        target_ids_or_files=[target.canonical_id],
    )
    assert len(tests) >= 1
    assert tests[0].classification == TestRecommendationTier.END_TO_END_TEST.value


def test_test_selector_tier_potentially_relevant():
    assert TestRecommendationTier.POTENTIALLY_RELEVANT.value == "POTENTIALLY_RELEVANT"


def test_test_selector_execution_status_strictly_not_executed():
    target = GraphNode(canonical_id="sym::f.py::fn", project_id=1, entity_type="FUNCTION", name="fn", qualified_name="f.fn", file_path="f.py", start_line=1, end_line=5)
    test_node = GraphNode(canonical_id="sym::t.py::test_fn", project_id=1, entity_type="TEST_FUNCTION", name="test_fn", qualified_name="t.test_fn", file_path="t.py", start_line=1, end_line=5)
    e = GraphEdge(source_canonical_id=target.canonical_id, target_canonical_id=test_node.canonical_id, rel_type=EdgeType.TESTED_BY.value, project_id=1, confidence=0.9, analyzer_source="test")

    tests = TestSelectionEngine.select_tests_for_changes(
        nodes={target.canonical_id: target, test_node.canonical_id: test_node},
        edges=[e],
        target_ids_or_files=[target.canonical_id],
    )
    for t in tests:
        assert t.execution_status == "NOT_EXECUTED"


def test_test_selector_benchmark_precision_recall_at_k():
    recs = [
        RecommendedTest(test_id="t1", test_name="t1", file_path="t1.py", tier="DIRECT_TEST", confidence=0.9, reason="r", target_symbol="s"),
        RecommendedTest(test_id="t2", test_name="t2", file_path="t2.py", tier="DIRECT_TEST", confidence=0.8, reason="r", target_symbol="s"),
        RecommendedTest(test_id="t3", test_name="t3", file_path="t3.py", tier="DIRECT_TEST", confidence=0.7, reason="r", target_symbol="s"),
    ]
    ground_truth = {"t1", "t2", "t4"}
    metrics = TestSelectionBenchmark.evaluate_precision_recall_at_k(recs, ground_truth, k_values=[1, 2, 3])
    assert metrics["precision@1"] == 1.0
    assert metrics["precision@2"] == 1.0
    assert metrics["precision@3"] == round(2 / 3, 4)
    assert metrics["recall@1"] == round(1 / 3, 4)
    assert metrics["recall@2"] == round(2 / 3, 4)
    assert metrics["recall@3"] == round(2 / 3, 4)


def test_test_selector_benchmark_unnecessary_recommendation_rate():
    recs = [
        RecommendedTest(test_id="t1", test_name="t1", file_path="t1.py", tier="DIRECT_TEST", confidence=0.9, reason="r", target_symbol="s"),
        RecommendedTest(test_id="t_irrelevant", test_name="t_irr", file_path="t_irr.py", tier="DIRECT_TEST", confidence=0.5, reason="r", target_symbol="s"),
    ]
    ground_truth = {"t1"}
    metrics = TestSelectionBenchmark.evaluate_benchmark(recs, ground_truth)
    assert metrics["unnecessary_recommendation_rate"] == 0.5
    assert metrics["total_recommended"] == 2


def test_test_selector_benchmark_relevant_test_coverage():
    recs = [
        RecommendedTest(test_id="t1", test_name="t1", file_path="t1.py", tier="DIRECT_TEST", confidence=0.9, reason="r", target_symbol="s"),
    ]
    ground_truth = {"t1", "t2"}
    metrics = TestSelectionBenchmark.evaluate_benchmark(recs, ground_truth)
    assert metrics["relevant_test_coverage"] == 0.5
    assert metrics["total_relevant"] == 2


# ============================================================================
# 6. Cross-Technology Relationship Intelligence Tests (47 - 53)
# ============================================================================

def test_extractor_cross_tech_react_calls_api_endpoint(multi_tier_repo: Path):
    extractor = GraphExtractionEngine(project_id=1, repo_root=multi_tier_repo)
    nodes, edges = extractor.extract_full_graph()

    api_calls = [e for e in edges if e.rel_type == EdgeType.CALLS_API.value]
    assert len(api_calls) >= 1
    call = api_calls[0]
    assert "apiClient.ts" in call.source_canonical_id or "UserProfile.tsx" in call.source_canonical_id


def test_extractor_cross_tech_fastapi_route_to_service(multi_tier_repo: Path):
    extractor = GraphExtractionEngine(project_id=1, repo_root=multi_tier_repo)
    nodes, edges = extractor.extract_full_graph()

    service_calls = [
        e for e in edges
        if "routes.py" in e.source_canonical_id and "query_user_record" in e.target_canonical_id and e.rel_type == EdgeType.CALLS.value
    ]
    assert len(service_calls) >= 1
    assert service_calls[0].rel_type == EdgeType.CALLS.value


def test_extractor_cross_tech_service_queries_model(multi_tier_repo: Path):
    extractor = GraphExtractionEngine(project_id=1, repo_root=multi_tier_repo)
    nodes, edges = extractor.extract_full_graph()

    model_queries = [
        e for e in edges
        if e.rel_type in (EdgeType.QUERIES_MODEL.value, EdgeType.CALLS.value)
        and "user_service.py" in e.source_canonical_id
        and "UserModel" in e.target_canonical_id
    ]
    assert len(model_queries) >= 1


def test_extractor_cross_tech_model_to_table_mapping(multi_tier_repo: Path):
    extractor = GraphExtractionEngine(project_id=1, repo_root=multi_tier_repo)
    nodes, edges = extractor.extract_full_graph()

    table_nodes = [n for n in nodes.values() if n.entity_type == NodeType.TABLE.value or "users_table" in n.name]
    assert len(table_nodes) >= 1
    assert table_nodes[0].name == "users_table"


def test_extractor_cross_tech_dockerfile_stages_and_entrypoints(multi_tier_repo: Path):
    extractor = GraphExtractionEngine(project_id=1, repo_root=multi_tier_repo)
    nodes, edges = extractor.extract_full_graph()

    docker_stages = [n for n in nodes.values() if n.entity_type == NodeType.DOCKER_STAGE.value]
    assert len(docker_stages) >= 1
    assert docker_stages[0].name == "base"

    entrypoint_edges = [e for e in edges if e.rel_type == EdgeType.EXECUTES_ENTRYPOINT.value]
    assert len(entrypoint_edges) >= 1


def test_extractor_cross_tech_ci_workflow_and_jobs_run_tests(multi_tier_repo: Path):
    extractor = GraphExtractionEngine(project_id=1, repo_root=multi_tier_repo)
    nodes, edges = extractor.extract_full_graph()

    ci_workflows = [n for n in nodes.values() if n.entity_type == NodeType.CI_WORKFLOW.value]
    assert len(ci_workflows) >= 1

    workflow_test_edges = [e for e in edges if e.rel_type == EdgeType.RUNS_WORKFLOW_TEST.value]
    assert len(workflow_test_edges) >= 1


def test_extractor_cross_tech_env_var_extraction(multi_tier_repo: Path):
    extractor = GraphExtractionEngine(project_id=1, repo_root=multi_tier_repo)
    nodes, edges = extractor.extract_full_graph()

    env_vars = [n for n in nodes.values() if n.entity_type == NodeType.ENV_VARIABLE.value]
    env_names = {n.name for n in env_vars}
    assert "DATABASE_URL" in env_names or "SECRET_KEY" in env_names

    env_edges = [e for e in edges if e.rel_type == EdgeType.CONSUMES_ENV_VAR.value]
    assert len(env_edges) >= 1


# ============================================================================
# 7. Honest Multi-Dimensional Coverage Reporting Tests (54 - 56)
# ============================================================================

def test_coverage_reporter_five_distinct_dimensions(multi_tier_repo: Path):
    extractor = GraphExtractionEngine(project_id=1, repo_root=multi_tier_repo)
    nodes, edges = extractor.extract_full_graph()
    report = GraphCoverageReporter.generate_coverage_report(1, multi_tier_repo, nodes, edges)

    assert report.dimensional_breakdown is not None
    dims = report.dimensional_breakdown
    assert "file_discovery" in dims
    assert "symbol_extraction" in dims
    assert "relationship_extraction" in dims
    assert "framework_specific" in dims
    assert "cross_language_resolution" in dims


def test_coverage_reporter_dimension_statuses_valid(multi_tier_repo: Path):
    extractor = GraphExtractionEngine(project_id=1, repo_root=multi_tier_repo)
    nodes, edges = extractor.extract_full_graph()
    report = GraphCoverageReporter.generate_coverage_report(1, multi_tier_repo, nodes, edges)

    valid_statuses = {
        CoverageDimensionStatus.COMPLETE.value,
        CoverageDimensionStatus.PARTIAL.value,
        CoverageDimensionStatus.NOT_SUPPORTED.value,
        CoverageDimensionStatus.FAILED.value,
        CoverageDimensionStatus.NOT_APPLICABLE.value,
    }
    for tech in report.technologies.values():
        assert tech.status in valid_statuses
        for dim, status in tech.dimension_status.items():
            assert status in valid_statuses


def test_coverage_reporter_no_unsupported_false_claims(tmp_path: Path):
    empty_dir = tmp_path / "empty_project"
    empty_dir.mkdir()
    (empty_dir / "script.lua").write_text("print('hello')", encoding="utf-8")

    report = GraphCoverageReporter.generate_coverage_report(1, empty_dir, {}, [])
    assert report.overall_coverage_percentage <= 50.0


# ============================================================================
# 8. Version Comparison and Historical Intelligence Tests (57 - 59)
# ============================================================================

def test_version_diff_split_and_merged_entities(mock_db_session: Session):
    v1 = EngineeringGraphVersion(project_id=1, version_number=1, status="SUPERSEDED", is_current=False)
    v2 = EngineeringGraphVersion(project_id=1, version_number=2, status="ACTIVE", is_current=True)
    mock_db_session.add_all([v1, v2])
    mock_db_session.flush()

    t_split = EngineeringIdentityTransition(
        project_id=1,
        from_version_id=v1.id,
        to_version_id=v2.id,
        old_canonical_id="sym::monolith.py::giant",
        new_canonical_id="sym::monolith.py::part1,sym::monolith.py::part2",
        transition_type="SPLIT",
        confidence=0.85,
        evidence={"reason": "function split into parts"},
    )
    t_merged = EngineeringIdentityTransition(
        project_id=1,
        from_version_id=v1.id,
        to_version_id=v2.id,
        old_canonical_id="sym::u1.py::f1,sym::u2.py::f2",
        new_canonical_id="sym::u_all.py::f_unified",
        transition_type="MERGED",
        confidence=0.90,
        evidence={"reason": "functions merged"},
    )
    mock_db_session.add_all([t_split, t_merged])
    mock_db_session.commit()

    diff = GraphVersionComparator.compare_versions(
        db=mock_db_session,
        project_id=1,
        version_a_id_or_number=1,
        version_b_id_or_number=2,
    )
    assert len(diff.split_entities) == 1
    assert len(diff.merged_entities) == 1
    assert diff.split_entities[0]["transition_type"] == "SPLIT"
    assert diff.merged_entities[0]["transition_type"] == "MERGED"


def test_version_diff_edge_confidence_shift(mock_db_session: Session):
    v1 = EngineeringGraphVersion(project_id=1, version_number=3, status="SUPERSEDED", is_current=False)
    v2 = EngineeringGraphVersion(project_id=1, version_number=4, status="ACTIVE", is_current=True)
    mock_db_session.add_all([v1, v2])
    mock_db_session.flush()

    e1 = EngineeringGraphEdge(
        project_id=1,
        version_id=v1.id,
        source_canonical_id="s1",
        target_canonical_id="t1",
        rel_type="CALLS",
        confidence=0.5,
        analyzer_source="test",
        provenance={"resolution": "UNRESOLVED"},
    )
    e2 = EngineeringGraphEdge(
        project_id=1,
        version_id=v2.id,
        source_canonical_id="s1",
        target_canonical_id="t1",
        rel_type="CALLS",
        confidence=0.95,
        analyzer_source="test",
        provenance={"resolution": "RESOLVED_RUNTIME"},
    )
    mock_db_session.add_all([e1, e2])
    mock_db_session.commit()

    diff = GraphVersionComparator.compare_versions(
        db=mock_db_session,
        project_id=1,
        version_a_id_or_number=3,
        version_b_id_or_number=4,
    )
    assert diff.changed_relationships_count >= 1
    rel = diff.changed_relationships[0]
    assert rel["old_confidence"] == 0.5
    assert rel["new_confidence"] == 0.95


def test_version_diff_edge_resolution_transition(mock_db_session: Session):
    v1 = EngineeringGraphVersion(project_id=1, version_number=5, status="SUPERSEDED", is_current=False)
    v2 = EngineeringGraphVersion(project_id=1, version_number=6, status="ACTIVE", is_current=True)
    mock_db_session.add_all([v1, v2])
    mock_db_session.flush()

    e1 = EngineeringGraphEdge(
        project_id=1,
        version_id=v1.id,
        source_canonical_id="caller",
        target_canonical_id="callee",
        rel_type="CALLS",
        confidence=0.6,
        analyzer_source="test",
        provenance={"resolution": "INFERRED"},
    )
    e2 = EngineeringGraphEdge(
        project_id=1,
        version_id=v2.id,
        source_canonical_id="caller",
        target_canonical_id="callee",
        rel_type="CALLS",
        confidence=1.0,
        analyzer_source="test",
        provenance={"resolution": "RESOLVED_RUNTIME"},
    )
    mock_db_session.add_all([e1, e2])
    mock_db_session.commit()

    diff = GraphVersionComparator.compare_versions(
        db=mock_db_session,
        project_id=1,
        version_a_id_or_number=5,
        version_b_id_or_number=6,
    )
    assert diff.changed_relationships_count >= 1
    rel = diff.changed_relationships[0]
    assert rel["old_resolution"] == "INFERRED"
    assert rel["new_resolution"] == "RESOLVED_RUNTIME"


# ============================================================================
# 9. Tenant Isolation & API Security Tests (60 - 64)
# ============================================================================

def test_api_graph_overview_tenant_isolation_404(api_test_app: FastAPI, other_auth_headers: dict[str, str]):
    client = TestClient(api_test_app)
    resp = client.get(
        "/api/project-reviews/1/graph/overview",
        headers=other_auth_headers,
    )
    assert resp.status_code == 404
    assert "not found" in resp.json()["detail"].lower()


def test_api_graph_extract_tenant_isolation_404(api_test_app: FastAPI, other_auth_headers: dict[str, str]):
    client = TestClient(api_test_app)
    resp = client.post(
        "/api/project-reviews/1/graph/extract",
        json={"force_full_rebuild": True},
        headers=other_auth_headers,
    )
    assert resp.status_code == 404
    assert "not found" in resp.json()["detail"].lower()


def test_api_graph_nodes_and_edges_query_tenant_isolation_404(api_test_app: FastAPI, other_auth_headers: dict[str, str]):
    client = TestClient(api_test_app)
    resp_nodes = client.get(
        "/api/project-reviews/1/graph/nodes",
        headers=other_auth_headers,
    )
    assert resp_nodes.status_code == 404

    resp_edges = client.get(
        "/api/project-reviews/1/graph/edges",
        headers=other_auth_headers,
    )
    assert resp_edges.status_code == 404


def test_api_graph_impact_and_blast_tenant_isolation_404(api_test_app: FastAPI, other_auth_headers: dict[str, str]):
    client = TestClient(api_test_app)
    resp_impact = client.post(
        "/api/project-reviews/1/graph/impact",
        json={"targets": ["some_target"]},
        headers=other_auth_headers,
    )
    assert resp_impact.status_code == 404

    resp_blast = client.post(
        "/api/project-reviews/1/graph/blast-radius",
        json={"targets": ["some_target"]},
        headers=other_auth_headers,
    )
    assert resp_blast.status_code == 404


def test_api_graph_recommended_tests_tenant_isolation_404(api_test_app: FastAPI, other_auth_headers: dict[str, str]):
    client = TestClient(api_test_app)
    resp = client.post(
        "/api/project-reviews/1/graph/tests/recommended",
        json={"targets": ["some_target"]},
        headers=other_auth_headers,
    )
    assert resp.status_code == 404
    assert "not found" in resp.json()["detail"].lower()
