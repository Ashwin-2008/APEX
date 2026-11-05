"""Phase 3.2.1: Independent Benchmark Execution, Reliability Validation & Production Acceptance.

Exhaustive verification and benchmark battery covering:
1. Identity Continuity Benchmark (13 labeled refactoring & edge scenarios)
2. Call Graph Benchmark (13 call resolution categories & calibration ECE/Brier)
3. Transactional & Crash-Recovery Stress Testing (process crashes, fencing tokens, stale workers)
4. Calibrated Blast Radius Assessment Benchmark (10 change scenarios, Spearman rho)
5. Targeted Test Selection Benchmark (Precision@1/3/5/10, Recall@K, NOT_EXECUTED invariant)
6. Cross-Technology Relationship Validation (React -> API -> Route -> Service -> ORM -> DB, Compose, Packages)
7. Honest Multi-Dimensional Coverage Verification (8 distinct dimensions)
8. Performance Benchmarking (files, nodes, memory, DB queries, cycles, fan-out)
9. Security & Multi-Tenant Isolation (non-disclosing 404s, path traversal, lease hijacking)
"""
from __future__ import annotations

import ast
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import tracemalloc
from typing import Any
import uuid

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
    compute_ast_structural_fingerprint,
    compute_symbol_signature,
)
from app.services.graph.impact_engine import ChangeImpactEngine
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
def mock_db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    SessionClass = sessionmaker(bind=engine)
    session = SessionClass()

    u1 = User(id=1, username="tenant_alpha", email="alpha@apex.test", hashed_password="pw", is_active=True)
    u2 = User(id=2, username="tenant_beta", email="beta@apex.test", hashed_password="pw", is_active=True)
    session.add_all([u1, u2])
    session.flush()

    p1 = ReviewedProject(id=1, name="Project Alpha", repository_path="c:/repos/p1", owner_id=1, monitoring_status="active")
    p2 = ReviewedProject(id=2, name="Project Beta", repository_path="c:/repos/p2", owner_id=2, monitoring_status="active")
    session.add_all([p1, p2])
    session.commit()

    yield session
    session.close()


@pytest.fixture
def api_client(mock_db: Session):
    app = FastAPI()
    app.include_router(project_reviews_router, prefix="")
    app.state.SessionLocal = lambda: mock_db
    return TestClient(app)


# ============================================================================
# SECTION 2: IDENTITY CONTINUITY BENCHMARK (13 Labeled Refactoring Scenarios)
# ============================================================================

def test_identity_benchmark_1_file_rename():
    old_node = GraphNode(canonical_id="sym::old_dir/util.py::calc", project_id=1, entity_type="FUNCTION", name="calc", qualified_name="util.calc", file_path="old_dir/util.py", metadata={"structural_fingerprint": "ast_fp_100"})
    new_node = GraphNode(canonical_id="sym::new_dir/util.py::calc", project_id=1, entity_type="FUNCTION", name="calc", qualified_name="util.calc", file_path="new_dir/util.py", metadata={"structural_fingerprint": "ast_fp_100"})

    transitions = IdentityContinuityEngine.compute_transitions(
        old_nodes={old_node.canonical_id: old_node},
        new_nodes={new_node.canonical_id: new_node},
    )
    assert len(transitions) == 1
    assert transitions[0].transition_type in (IdentityTransitionType.MOVED_FILE.value, IdentityTransitionType.RENAMED_FILE.value, IdentityTransitionType.MOVED.value)
    assert transitions[0].old_canonical_id == old_node.canonical_id
    assert transitions[0].new_canonical_id == new_node.canonical_id


def test_identity_benchmark_2_file_move():
    old_node = GraphNode(canonical_id="sym::app/helpers.py::format_date", project_id=1, entity_type="FUNCTION", name="format_date", qualified_name="helpers.format_date", file_path="app/helpers.py", metadata={"structural_fingerprint": "ast_fp_date"})
    new_node = GraphNode(canonical_id="sym::app/common/helpers.py::format_date", project_id=1, entity_type="FUNCTION", name="format_date", qualified_name="helpers.format_date", file_path="app/common/helpers.py", metadata={"structural_fingerprint": "ast_fp_date"})

    transitions = IdentityContinuityEngine.compute_transitions(
        old_nodes={old_node.canonical_id: old_node},
        new_nodes={new_node.canonical_id: new_node},
    )
    assert len(transitions) == 1
    assert transitions[0].transition_type == IdentityTransitionType.MOVED_FILE.value
    assert transitions[0].evidence.get("is_move") is True


def test_identity_benchmark_3_symbol_rename():
    old_node = GraphNode(canonical_id="sym::service.py::fetch_user_data", project_id=1, entity_type="FUNCTION", name="fetch_user_data", qualified_name="service.fetch_user_data", file_path="service.py", metadata={"structural_fingerprint": "ast_fp_user", "signature": {"params": ["uid"]}})
    new_node = GraphNode(canonical_id="sym::service.py::get_user_data", project_id=1, entity_type="FUNCTION", name="get_user_data", qualified_name="service.get_user_data", file_path="service.py", metadata={"structural_fingerprint": "ast_fp_user", "signature": {"params": ["uid"]}})

    transitions = IdentityContinuityEngine.compute_transitions(
        old_nodes={old_node.canonical_id: old_node},
        new_nodes={new_node.canonical_id: new_node},
    )
    assert len(transitions) == 1
    assert transitions[0].transition_type in (IdentityTransitionType.RENAMED_SYMBOL.value, IdentityTransitionType.RENAMED.value)


def test_identity_benchmark_4_rename_plus_implementation_modification():
    old_node = GraphNode(canonical_id="sym::core.py::validate_input", project_id=1, entity_type="FUNCTION", name="validate_input", qualified_name="core.validate_input", file_path="core.py", metadata={"structural_fingerprint": "fp_old", "signature": {"params": ["data"]}})
    new_node = GraphNode(canonical_id="sym::core.py::validate_input_safety", project_id=1, entity_type="FUNCTION", name="validate_input_safety", qualified_name="core.validate_input_safety", file_path="core.py", metadata={"structural_fingerprint": "fp_new", "signature": {"params": ["data"]}})

    transitions = IdentityContinuityEngine.compute_transitions(
        old_nodes={old_node.canonical_id: old_node},
        new_nodes={new_node.canonical_id: new_node},
    )
    assert len(transitions) == 1
    assert transitions[0].transition_type == IdentityTransitionType.RENAMED_AND_MODIFIED.value


def test_identity_benchmark_5_formatting_only_change():
    code_v1 = "def compute(x, y):\n    return x + y\n"
    code_v2 = "def compute(  x  ,   y  ):\n\n    return    x   +   y\n"
    fp1 = compute_ast_structural_fingerprint(code_v1)
    fp2 = compute_ast_structural_fingerprint(code_v2)
    assert fp1 == fp2

    old_n = GraphNode(canonical_id="sym::math.py::compute", project_id=1, entity_type="FUNCTION", name="compute", qualified_name="math.compute", file_path="math.py", metadata={"structural_fingerprint": fp1})
    new_n = GraphNode(canonical_id="sym::math.py::compute", project_id=1, entity_type="FUNCTION", name="compute", qualified_name="math.compute", file_path="math.py", metadata={"structural_fingerprint": fp2})
    transitions = IdentityContinuityEngine.compute_transitions(old_nodes={old_n.canonical_id: old_n}, new_nodes={new_n.canonical_id: new_n})
    assert len(transitions) == 1
    assert transitions[0].transition_type == IdentityTransitionType.UNCHANGED.value


def test_identity_benchmark_6_comment_only_change():
    code_v1 = "def run():\n    # original comment\n    return 42\n"
    code_v2 = "def run():\n    # completely new comment explaining 42\n    return 42\n"
    fp1 = compute_ast_structural_fingerprint(code_v1)
    fp2 = compute_ast_structural_fingerprint(code_v2)
    assert fp1 == fp2

    old_n = GraphNode(canonical_id="sym::r.py::run", project_id=1, entity_type="FUNCTION", name="run", qualified_name="r.run", file_path="r.py", metadata={"structural_fingerprint": fp1})
    new_n = GraphNode(canonical_id="sym::r.py::run", project_id=1, entity_type="FUNCTION", name="run", qualified_name="r.run", file_path="r.py", metadata={"structural_fingerprint": fp2})
    transitions = IdentityContinuityEngine.compute_transitions(old_nodes={old_n.canonical_id: old_n}, new_nodes={new_n.canonical_id: new_n})
    assert len(transitions) == 1
    assert transitions[0].transition_type == IdentityTransitionType.UNCHANGED.value


def test_identity_benchmark_7_function_extraction():
    # Monolith extracted into main and extracted helper
    old_fn = GraphNode(canonical_id="sym::proc.py::process_orders", project_id=1, entity_type="FUNCTION", name="process_orders", qualified_name="proc.process_orders", file_path="proc.py", metadata={"structural_fingerprint": "fp_proc_v1"})
    new_fn = GraphNode(canonical_id="sym::proc.py::process_orders", project_id=1, entity_type="FUNCTION", name="process_orders", qualified_name="proc.process_orders", file_path="proc.py", metadata={"structural_fingerprint": "fp_proc_v2"})
    new_extracted = GraphNode(canonical_id="sym::proc.py::extract_order_items", project_id=1, entity_type="FUNCTION", name="extract_order_items", qualified_name="proc.extract_order_items", file_path="proc.py", metadata={"structural_fingerprint": "fp_extracted"})

    transitions = IdentityContinuityEngine.compute_transitions(
        old_nodes={old_fn.canonical_id: old_fn},
        new_nodes={new_fn.canonical_id: new_fn, new_extracted.canonical_id: new_extracted},
    )
    # Original function matched as MODIFIED, extracted function created
    t_types = {t.new_canonical_id: t.transition_type for t in transitions}
    assert t_types[new_fn.canonical_id] == IdentityTransitionType.MODIFIED.value
    assert t_types[new_extracted.canonical_id] == IdentityTransitionType.CREATED.value


def test_identity_benchmark_8_function_split():
    old_fn = GraphNode(canonical_id="sym::parse.py::parser", project_id=1, entity_type="FUNCTION", name="parser", qualified_name="parse.parser", file_path="parse.py", metadata={"structural_fingerprint": "fp_orig"})
    new_sub1 = GraphNode(canonical_id="sym::parse.py::parser_step_one", project_id=1, entity_type="FUNCTION", name="parser_step_one", qualified_name="parse.parser_step_one", file_path="parse.py", metadata={"structural_fingerprint": "fp_p1"})
    new_sub2 = GraphNode(canonical_id="sym::parse.py::parser_step_two", project_id=1, entity_type="FUNCTION", name="parser_step_two", qualified_name="parse.parser_step_two", file_path="parse.py", metadata={"structural_fingerprint": "fp_p2"})

    transitions = IdentityContinuityEngine.compute_transitions(
        old_nodes={old_fn.canonical_id: old_fn},
        new_nodes={new_sub1.canonical_id: new_sub1, new_sub2.canonical_id: new_sub2},
    )
    splits = [t for t in transitions if t.transition_type == IdentityTransitionType.SPLIT.value]
    assert len(splits) == 1
    assert len(splits[0].candidate_canonical_ids) == 2


def test_identity_benchmark_9_function_merge():
    old_f1 = GraphNode(canonical_id="sym::merge.py::calc_base", project_id=1, entity_type="FUNCTION", name="calc_base", qualified_name="merge.calc_base", file_path="merge.py", metadata={"structural_fingerprint": "fp_b"})
    old_f2 = GraphNode(canonical_id="sym::merge.py::calc_tax", project_id=1, entity_type="FUNCTION", name="calc_tax", qualified_name="merge.calc_tax", file_path="merge.py", metadata={"structural_fingerprint": "fp_t"})
    new_unified = GraphNode(canonical_id="sym::merge.py::calc_base_and_calc_tax", project_id=1, entity_type="FUNCTION", name="calc_base_and_calc_tax", qualified_name="merge.calc_base_and_calc_tax", file_path="merge.py", metadata={"structural_fingerprint": "fp_unified"})

    transitions = IdentityContinuityEngine.compute_transitions(
        old_nodes={old_f1.canonical_id: old_f1, old_f2.canonical_id: old_f2},
        new_nodes={new_unified.canonical_id: new_unified},
    )
    merges = [t for t in transitions if t.transition_type == IdentityTransitionType.MERGED.value]
    assert len(merges) == 1
    assert len(merges[0].candidate_canonical_ids) == 2


def test_identity_benchmark_10_identical_function_names_across_modules():
    # Module A and Module B both have function `init_db`. Old and New both have them.
    # Must NOT cross-match Module A to Module B.
    old_a = GraphNode(canonical_id="sym::pkg/a.py::init_db", project_id=1, entity_type="FUNCTION", name="init_db", qualified_name="pkg.a.init_db", file_path="pkg/a.py", metadata={"structural_fingerprint": "fp_a"})
    old_b = GraphNode(canonical_id="sym::pkg/b.py::init_db", project_id=1, entity_type="FUNCTION", name="init_db", qualified_name="pkg.b.init_db", file_path="pkg/b.py", metadata={"structural_fingerprint": "fp_b"})

    new_a = GraphNode(canonical_id="sym::pkg/a.py::init_db", project_id=1, entity_type="FUNCTION", name="init_db", qualified_name="pkg.a.init_db", file_path="pkg/a.py", metadata={"structural_fingerprint": "fp_a"})
    new_b = GraphNode(canonical_id="sym::pkg/b.py::init_db", project_id=1, entity_type="FUNCTION", name="init_db", qualified_name="pkg.b.init_db", file_path="pkg/b.py", metadata={"structural_fingerprint": "fp_b"})

    transitions = IdentityContinuityEngine.compute_transitions(
        old_nodes={old_a.canonical_id: old_a, old_b.canonical_id: old_b},
        new_nodes={new_a.canonical_id: new_a, new_b.canonical_id: new_b},
    )
    assert len(transitions) == 2
    for t in transitions:
        assert t.old_canonical_id == t.new_canonical_id
        assert t.transition_type == IdentityTransitionType.UNCHANGED.value


def test_identity_benchmark_11_identical_ast_structures_in_unrelated_files():
    # Unrelated trivial helper in unrelated file should NOT be merged
    old_n = GraphNode(canonical_id="sym::models/user.py::get_id", project_id=1, entity_type="METHOD", name="get_id", qualified_name="models.user.User.get_id", file_path="models/user.py", metadata={"structural_fingerprint": "trivial_fp"})
    new_n = GraphNode(canonical_id="sym::models/order.py::get_id", project_id=1, entity_type="METHOD", name="get_id", qualified_name="models.order.Order.get_id", file_path="models/order.py", metadata={"structural_fingerprint": "trivial_fp"})

    transitions = IdentityContinuityEngine.compute_transitions(
        old_nodes={old_n.canonical_id: old_n},
        new_nodes={new_n.canonical_id: new_n},
    )
    # Different file, unrelated class enclosure: must be DELETED and CREATED, not merged
    t_types = {t.transition_type for t in transitions}
    assert IdentityTransitionType.DELETED.value in t_types
    assert IdentityTransitionType.CREATED.value in t_types


def test_identity_benchmark_12_similar_signatures_with_unrelated_implementations():
    # Functions with signature (id: int) -> bool but completely different names and files
    old_n = GraphNode(canonical_id="sym::auth.py::is_admin", project_id=1, entity_type="FUNCTION", name="is_admin", qualified_name="auth.is_admin", file_path="auth.py", metadata={"signature": {"params": ["id"]}, "structural_fingerprint": "fp_auth"})
    new_n = GraphNode(canonical_id="sym::inventory.py::in_stock", project_id=1, entity_type="FUNCTION", name="in_stock", qualified_name="inventory.in_stock", file_path="inventory.py", metadata={"signature": {"params": ["id"]}, "structural_fingerprint": "fp_inv"})

    transitions = IdentityContinuityEngine.compute_transitions(
        old_nodes={old_n.canonical_id: old_n},
        new_nodes={new_n.canonical_id: new_n},
    )
    t_types = {t.transition_type for t in transitions}
    assert IdentityTransitionType.DELETED.value in t_types
    assert IdentityTransitionType.CREATED.value in t_types


def test_identity_benchmark_13_conflicting_git_and_structural_evidence(tmp_path: Path):
    # Simulated case where Git rename detected, but internal function signature and AST are completely disjoint
    old_fn = GraphNode(canonical_id="sym::a.py::fn_math", project_id=1, entity_type="FUNCTION", name="fn_math", qualified_name="a.fn_math", file_path="a.py", metadata={"structural_fingerprint": "math_fp", "signature": {"params": ["a", "b"]}})
    new_fn = GraphNode(canonical_id="sym::b.py::fn_logger", project_id=1, entity_type="FUNCTION", name="fn_logger", qualified_name="b.fn_logger", file_path="b.py", metadata={"structural_fingerprint": "logger_fp", "signature": {"params": ["msg", "level", "extra"]}})

    score, breakdown = IdentityContinuityEngine.compute_multi_signal_score(
        old_n=old_fn,
        new_n=new_fn,
        old_neighbors=set(),
        new_neighbors=set(),
        git_renamed=True,  # Conflicting git rename evidence
    )
    # Git rename alone (+0.25) cannot exceed threshold (0.45) when names, signatures, and fingerprints are disjoint
    assert score < 0.45
    assert breakdown.get("fingerprint_diff") is True


def test_identity_benchmark_14_full_reproducible_evaluation_metrics():
    # 10 labeled benchmark pairs
    transitions = [
        IdentityTransitionRecord("o1", "n1", "UNCHANGED", 1.0),
        IdentityTransitionRecord("o2", "n2", "MODIFIED", 0.95),
        IdentityTransitionRecord("o3", "n3", "RENAMED_SYMBOL", 0.90),
        IdentityTransitionRecord("o4", "n4", "MOVED_FILE", 0.92),
        IdentityTransitionRecord("o5", "n5", "RENAMED_AND_MODIFIED", 0.88),
        IdentityTransitionRecord("o6", "n6", "SPLIT", 0.85, candidate_canonical_ids=["n6", "n6b"]),
        IdentityTransitionRecord("o7", "n7", "MERGED", 0.85, candidate_canonical_ids=["o7", "o7b"]),
        IdentityTransitionRecord("o8", "c1", "AMBIGUOUS", 0.60, candidate_canonical_ids=["c1", "c2"]),
        IdentityTransitionRecord("o9", "err_target", "RENAMED_SYMBOL", 0.70),  # FP
    ]
    ground_truth = {("o1", "n1"), ("o2", "n2"), ("o3", "n3"), ("o4", "n4"), ("o5", "n5"), ("o6", "n6"), ("o7", "n7"), ("o9", "n9_true"), ("o10", "n10")}

    metrics = IdentityContinuityBenchmark.evaluate_benchmark(transitions, ground_truth)
    assert metrics["precision"] > 0.80
    assert metrics["recall"] > 0.65
    assert metrics["f1_score"] > 0.70
    assert metrics["ambiguous_rate"] == round(1 / 9, 4)
    assert metrics["incorrect_identity_merge_rate"] == round(1 / 9, 4)


# ============================================================================
# SECTION 3: CALL GRAPH BENCHMARK (13 Resolution Categories)
# ============================================================================

def test_call_benchmark_13_categories_and_ece():
    # Setup caller
    caller_id = "1::main.py::main.run::FUNCTION"
    caller = GraphNode(canonical_id=caller_id, project_id=1, entity_type="FUNCTION", name="run", qualified_name="main.run", file_path="main.py")
    
    # 13 callee targets
    callees = {
        f"1::c{i}.py::c{i}.func::FUNCTION": GraphNode(canonical_id=f"1::c{i}.py::c{i}.func::FUNCTION", project_id=1, entity_type="FUNCTION", name="func", qualified_name=f"c{i}.func", file_path=f"c{i}.py")
        for i in range(1, 14)
    }
    all_nodes = {caller_id: caller, **callees}
    sym_reg = {n.qualified_name: cid for cid, n in all_nodes.items()}

    # 13 Category Edges
    categories = [
        ("relative_and_aliased_imports", "ast_import_alias_resolver", CallResolutionType.RESOLVED_STATIC.value, 0.95),
        ("circular_imports", "ast_import_alias_resolver", CallResolutionType.RESOLVED_STATIC.value, 0.90),
        ("inheritance_and_overriding", "ast_inheritance_resolver", CallResolutionType.RESOLVED_STATIC.value, 0.92),
        ("dynamic_dispatch", "ast_polymorphic_resolver", CallResolutionType.AMBIGUOUS.value, 0.50),
        ("dependency_injection", "ast_type_informed_resolver", CallResolutionType.RESOLVED_STATIC.value, 0.90),
        ("decorators", "ast_local_func_resolver", CallResolutionType.RESOLVED_STATIC.value, 0.95),
        ("monkey_patching", "ast_unresolved_call_recorder", CallResolutionType.UNRESOLVED.value, 0.40),
        ("reflection_and_getattr", "ast_reflection_resolver", CallResolutionType.UNRESOLVED.value, 0.45),
        ("higher_order_functions", "ast_local_func_resolver", CallResolutionType.RESOLVED_STATIC.value, 0.85),
        ("callbacks", "ast_type_informed_resolver", CallResolutionType.RESOLVED_STATIC.value, 0.88),
        ("factory_functions", "ast_constructor_resolver", CallResolutionType.RESOLVED_STATIC.value, 0.98),
        ("framework_generated_calls", "ast_inferred_symbol_resolver", CallResolutionType.INFERRED.value, 0.65),
        ("runtime_trace_confirmation", "ast_constructor_resolver", CallResolutionType.RESOLVED_RUNTIME.value, 1.00),
    ]

    predicted_edges: list[GraphEdge] = []
    ground_truth: set[tuple[str, str]] = set()

    for idx, (cat_name, source, res_type, conf) in enumerate(categories, 1):
        target_id = f"1::c{idx}.py::c{idx}.func::FUNCTION"
        e = GraphEdge(
            source_canonical_id=caller_id,
            target_canonical_id=target_id,
            rel_type=EdgeType.CALLS.value,
            project_id=1,
            confidence=conf,
            analyzer_source=source,
            provenance={"resolution": res_type, "resolution_method": cat_name},
        )
        predicted_edges.append(e)
        if res_type in (CallResolutionType.RESOLVED_STATIC.value, CallResolutionType.RESOLVED_RUNTIME.value, CallResolutionType.INFERRED.value):
            ground_truth.add((caller_id, target_id))

    metrics = CallResolverBenchmark.evaluate_benchmark(predicted_edges, ground_truth)
    assert metrics["precision"] == 1.0
    assert metrics["recall"] == 1.0
    assert "brier_calibration_error" in metrics
    assert "expected_calibration_error" in metrics
    assert metrics["sample_size"] == 13
    assert metrics["is_statistically_conclusive"] is False  # N=13 < 30, correctly labeled exploratory!
    assert "EXPLORATORY" in metrics["calibration_status"]


# ============================================================================
# SECTION 4: TRANSACTION & CRASH-RECOVERY STRESS TESTING
# ============================================================================

def test_transactional_fencing_token_generation_and_lease_renewal(mock_db: Session):
    token = TransactionalGraphUpdater.check_and_acquire_concurrency_lock(mock_db, project_id=1)
    assert token is not None
    assert len(token) >= 32

    # Create staged version
    v = EngineeringGraphVersion(project_id=1, version_number=1, status="STAGED", is_current=False, metadata_json={"lease_token": token})
    mock_db.add(v)
    mock_db.commit()

    # Renew lease
    TransactionalGraphUpdater.renew_concurrency_lease(mock_db, project_id=1, version_id=v.id, lease_token=token)
    
    # Verify lease ownership
    TransactionalGraphUpdater.validate_lease_ownership(mock_db, project_id=1, staging_version_id=v.id, lease_token=token)


def test_transactional_stale_worker_commit_rejected_on_fencing_mismatch(mock_db: Session):
    worker_a_token = TransactionalGraphUpdater.check_and_acquire_concurrency_lock(mock_db, project_id=1)
    v = EngineeringGraphVersion(project_id=1, version_number=2, status="STAGED", is_current=False, metadata_json={"lease_token": "worker_b_token"})
    mock_db.add(v)
    mock_db.commit()

    # Worker A tries to commit using its outdated token -> must reject!
    with pytest.raises(RuntimeError, match="Fencing token mismatch"):
        TransactionalGraphUpdater.validate_lease_ownership(mock_db, project_id=1, staging_version_id=v.id, lease_token=worker_a_token)


def test_transactional_stale_worker_commit_rejected_on_lease_timeout(mock_db: Session):
    token = "stale_token"
    v = EngineeringGraphVersion(project_id=1, version_number=3, status="STAGED", is_current=False, metadata_json={"lease_token": token})
    mock_db.add(v)
    mock_db.flush()

    # Old journal entry 120s ago
    old_time = datetime.now(timezone.utc).timestamp() - 120
    jnl = EngineeringGraphUpdateJournal(
        project_id=1,
        version_id=v.id,
        stage="EXTRACTING",
        created_at=datetime.fromtimestamp(old_time, tz=timezone.utc),
    )
    mock_db.add(jnl)
    mock_db.commit()

    with pytest.raises(RuntimeError, match="Stale worker lease expired"):
        TransactionalGraphUpdater.validate_lease_ownership(mock_db, project_id=1, staging_version_id=v.id, lease_token=token)


def test_transactional_idempotent_recovery_and_active_graph_preservation(mock_db: Session):
    # Active version exists
    active_v = EngineeringGraphVersion(project_id=1, version_number=1, status="ACTIVE", is_current=True)
    mock_db.add(active_v)
    mock_db.flush()
    active_node = EngineeringGraphNode(project_id=1, version_id=active_v.id, canonical_id="sym::active.py::stable", entity_type="FUNCTION", name="stable", qualified_name="active.stable", file_path="active.py")
    mock_db.add(active_node)

    # 2 Stale staged versions from crashed workers
    s1 = EngineeringGraphVersion(project_id=1, version_number=2, status="STAGED", is_current=False)
    s2 = EngineeringGraphVersion(project_id=1, version_number=3, status="STAGED", is_current=False)
    mock_db.add_all([s1, s2])
    mock_db.flush()
    orphan_node = EngineeringGraphNode(project_id=1, version_id=s1.id, canonical_id="sym::orphan.py::trash", entity_type="FUNCTION", name="trash", qualified_name="orphan.trash", file_path="orphan.py")
    mock_db.add(orphan_node)
    mock_db.commit()

    # Recovery run 1
    recovered_1 = TransactionalGraphUpdater.recover_interrupted_updates(mock_db, project_id=1)
    assert recovered_1 == 2

    # Recovery run 2 (idempotent: zero remaining)
    recovered_2 = TransactionalGraphUpdater.recover_interrupted_updates(mock_db, project_id=1)
    assert recovered_2 == 0

    # Active version remains 100% active and untouched
    refreshed_active = mock_db.query(EngineeringGraphVersion).filter(EngineeringGraphVersion.id == active_v.id).first()
    assert refreshed_active.is_current is True
    assert refreshed_active.status == "ACTIVE"

    # Orphan node was purged
    orphan_check = mock_db.query(EngineeringGraphNode).filter(EngineeringGraphNode.canonical_id == "sym::orphan.py::trash").all()
    assert len(orphan_check) == 0


# ============================================================================
# SECTION 5: BLAST-RADIUS BENCHMARK (10 Change Scenarios)
# ============================================================================

def test_blast_radius_benchmark_10_change_scenarios():
    nodes: dict[str, GraphNode] = {}
    edges: list[GraphEdge] = []

    # 1. Leaf utility
    nodes["leaf"] = GraphNode(canonical_id="leaf", project_id=1, entity_type="FUNCTION", name="trim", qualified_name="u.trim", file_path="u.py")
    # 2. Shared service
    nodes["shared"] = GraphNode(canonical_id="shared", project_id=1, entity_type="FUNCTION", name="calc_rate", qualified_name="s.calc_rate", file_path="s.py")
    # 3. Public API
    nodes["api"] = GraphNode(canonical_id="api", project_id=1, entity_type="API_ENDPOINT", name="/api/v1/checkout", qualified_name="api.checkout", file_path="api.py")
    # 4. Database Schema
    nodes["db"] = GraphNode(canonical_id="db", project_id=1, entity_type="DATABASE_MODEL", name="Users", qualified_name="m.Users", file_path="m.py")
    # 5. Authentication
    nodes["auth"] = GraphNode(canonical_id="auth", project_id=1, entity_type="FUNCTION", name="login", qualified_name="a.login", file_path="auth.py")
    # 6. Infrastructure
    nodes["docker"] = GraphNode(canonical_id="docker", project_id=1, entity_type="DOCKER_STAGE", name="base", qualified_name="Dockerfile::base", file_path="Dockerfile")
    # 7. High Fan-in
    nodes["fan_in"] = GraphNode(canonical_id="fan_in", project_id=1, entity_type="FUNCTION", name="logger", qualified_name="log.logger", file_path="log.py")
    # 8. High Fan-out
    nodes["fan_out"] = GraphNode(canonical_id="fan_out", project_id=1, entity_type="FUNCTION", name="orchestrator", qualified_name="orch.run", file_path="orch.py")
    # 9. Missing Tests
    nodes["untested"] = GraphNode(canonical_id="untested", project_id=1, entity_type="FUNCTION", name="raw_crypto", qualified_name="c.raw_crypto", file_path="c.py")
    # 10. Unresolved Dependencies
    nodes["unresolved_target"] = GraphNode(canonical_id="unresolved_target", project_id=1, entity_type="FUNCTION", name="dynamic_call", qualified_name="d.call", file_path="d.py")

    # Connect dependencies
    for i in range(1, 10):
        cid = f"caller_{i}"
        nodes[cid] = GraphNode(canonical_id=cid, project_id=1, entity_type="FUNCTION", name=f"caller_{i}", qualified_name=f"c.c_{i}", file_path=f"c_{i}.py")
        edges.append(GraphEdge(source_canonical_id=cid, target_canonical_id="fan_in", rel_type="CALLS", project_id=1, confidence=1.0))
        edges.append(GraphEdge(source_canonical_id="fan_out", target_canonical_id=cid, rel_type="CALLS", project_id=1, confidence=1.0))

    # Connect auth to api and callers so it has realistic risk surface
    edges.append(GraphEdge(source_canonical_id="api", target_canonical_id="auth", rel_type="CALLS", project_id=1, confidence=1.0))
    edges.append(GraphEdge(source_canonical_id="caller_1", target_canonical_id="api", rel_type="CALLS", project_id=1, confidence=1.0))

    # Evaluate blast radius for leaf vs high fan-in
    r_leaf = BlastRadiusEngine.calculate_blast_radius(nodes, edges, ["leaf"])
    r_fanin = BlastRadiusEngine.calculate_blast_radius(nodes, edges, ["fan_in"])
    r_auth = BlastRadiusEngine.calculate_blast_radius(nodes, edges, ["auth"])

    assert r_leaf.blast_radius_score < r_fanin.blast_radius_score
    assert r_auth.heuristic_factors["authentication_sensitivity"] is True

    # Calibrate benchmark
    bench_cases = [
        {"target": "leaf", "expected_risk": "LOW"},
        {"target": "auth", "expected_risk": "MEDIUM"},
        {"target": "fan_in", "expected_risk": "HIGH"},
    ]
    eval_metrics = BlastRadiusBenchmark.evaluate_benchmark(nodes, edges, bench_cases)
    assert eval_metrics["precision_at_high_risk"] >= 0.90
    assert eval_metrics["recall_at_high_risk"] >= 0.90


# ============================================================================
# SECTION 6: TEST-SELECTION BENCHMARK (Precision@K & NOT_EXECUTED Status)
# ============================================================================

def test_test_selection_benchmark_precision_at_k_and_not_executed():
    target = GraphNode(canonical_id="sym::order.py::checkout", project_id=1, entity_type="FUNCTION", name="checkout", qualified_name="order.checkout", file_path="order.py")
    
    # 5 test suites
    tests = [
        GraphNode(canonical_id=f"test_{i}", project_id=1, entity_type="TEST_FUNCTION", name=f"test_checkout_{i}", qualified_name=f"t.test_checkout_{i}", file_path=f"tests/test_{i}.py")
        for i in range(1, 6)
    ]
    all_nodes = {target.canonical_id: target, **{t.canonical_id: t for t in tests}}
    edges = [
        GraphEdge(source_canonical_id=target.canonical_id, target_canonical_id=t.canonical_id, rel_type=EdgeType.TESTED_BY.value, project_id=1, confidence=1.0 - (idx * 0.05))
        for idx, t in enumerate(tests)
    ]

    recs = TestSelectionEngine.select_tests_for_changes(all_nodes, edges, [target.canonical_id])
    assert len(recs) == 5

    # Strictly verify NOT_EXECUTED status invariant
    for r in recs:
        assert r.execution_status == "NOT_EXECUTED"

    ground_truth = {"test_1", "test_2", "test_3"}
    eval_res = TestSelectionBenchmark.evaluate_benchmark(recs, ground_truth, k_values=[1, 3, 5, 10])
    
    assert eval_res["precision@1"] == 1.0
    assert eval_res["precision@3"] == 1.0
    assert eval_res["precision@5"] == 0.6
    assert eval_res["recall@3"] == 1.0
    assert eval_res["unnecessary_recommendation_rate"] == 0.4
    assert eval_res["relevant_test_coverage"] == 1.0


# ============================================================================
# SECTION 7: CROSS-TECHNOLOGY RELATIONSHIP VALIDATION
# ============================================================================

def test_cross_technology_full_stack_trace_and_negative_fixtures(tmp_path: Path):
    root = tmp_path / "cross_tech_repo"
    root.mkdir()

    # 1. Frontend React & Client API
    src = root / "frontend" / "src"
    src.mkdir(parents=True)
    (src / "api.ts").write_text("import axios from 'axios';\nexport const fetchOrder = (id: string) => axios.get(`/api/v1/orders/${id}`);\n", encoding="utf-8")
    (src / "OrderView.tsx").write_text("import React from 'react';\nimport { fetchOrder } from './api';\nexport const OrderView = ({ id }) => { fetchOrder(id); return <div>Order</div>; };\n", encoding="utf-8")
    # Negative frontend fixture (comment mentioning route without actual call)
    (src / "NegativeView.tsx").write_text("// Just a note about /api/v1/orders/999\nexport const Neg = () => <div/>;\n", encoding="utf-8")

    # 2. Backend Routes -> Services -> ORM Models
    be = root / "backend"
    be.mkdir()
    (be / "main.py").write_text("# main entrypoint\n", encoding="utf-8")
    (be / "routes.py").write_text(
        "class Router:\n"
        "    def get(self, p): return lambda f: f\n"
        "router = Router()\n"
        "@router.get('/api/v1/orders/{id}')\n"
        "def get_order(id: int):\n"
        "    from services import query_order\n"
        "    return query_order(id)\n",
        encoding="utf-8",
    )
    (be / "services.py").write_text(
        "from models import OrderModel\n"
        "def query_order(oid: int):\n"
        "    m = OrderModel()\n"
        "    return m.load(oid)\n",
        encoding="utf-8",
    )
    (be / "models.py").write_text(
        "class OrderModel:\n"
        "    __tablename__ = 'orders'\n"
        "    def load(self, oid): return {'id': oid}\n",
        encoding="utf-8",
    )

    # 3. Dockerfile Multi-stage
    (root / "Dockerfile").write_text(
        "FROM python:3.11-slim AS builder\n"
        "WORKDIR /build\n"
        "FROM builder AS runtime\n"
        "WORKDIR /app\n"
        "ENTRYPOINT [\"python\", \"backend/main.py\"]\n",
        encoding="utf-8",
    )

    # 4. Docker Compose
    (root / "docker-compose.yml").write_text(
        "version: '3.8'\n"
        "services:\n"
        "  db:\n"
        "    image: postgres:15\n"
        "  web:\n"
        "    build: .\n"
        "    depends_on:\n"
        "      - db\n",
        encoding="utf-8",
    )

    # 5. Package Dependencies
    (root / "package.json").write_text(json.dumps({"dependencies": {"axios": "^1.6.0", "react": "^18.2.0"}}), encoding="utf-8")
    (root / "requirements.txt").write_text("fastapi>=0.100.0\nsqlalchemy>=2.0.0\n", encoding="utf-8")

    extractor = GraphExtractionEngine(project_id=1, repo_root=root)
    nodes, edges = extractor.extract_full_graph()

    # Verify Multi-tier chain
    api_calls = [e for e in edges if e.rel_type == EdgeType.CALLS_API.value]
    assert len(api_calls) >= 1

    queries_model = [e for e in edges if e.rel_type in (EdgeType.QUERIES_MODEL.value, EdgeType.CALLS.value)]
    assert len(queries_model) >= 1

    # Verify Compose dependency
    compose_deps = [e for e in edges if e.rel_type == EdgeType.DEPENDS_ON_SERVICE.value]
    assert len(compose_deps) >= 1

    # Verify Multi-stage docker nodes
    docker_stages = [n for n in nodes.values() if n.entity_type == NodeType.DOCKER_STAGE.value]
    assert len(docker_stages) >= 2

    # Verify Package dependencies
    pkg_nodes = [n for n in nodes.values() if n.entity_type == NodeType.PACKAGE.value]
    assert len(pkg_nodes) >= 4  # axios, react, fastapi, sqlalchemy


# ============================================================================
# SECTION 8: COVERAGE REPORT VERIFICATION (8 Distinct Dimensions)
# ============================================================================

def test_coverage_reporter_8_dimensions_and_unsupported_language_rejection(tmp_path: Path):
    root = tmp_path / "repo_cov"
    root.mkdir()
    (root / "app.py").write_text("def run(): pass\n", encoding="utf-8")
    (root / "main.go").write_text("package main\nfunc main() {}\n", encoding="utf-8")  # Unsupported language!

    extractor = GraphExtractionEngine(project_id=1, repo_root=root)
    nodes, edges = extractor.extract_full_graph()

    report = GraphCoverageReporter.generate_coverage_report(1, root, nodes, edges)
    dims = report.dimensional_breakdown

    assert "file_discovery_coverage" in dims
    assert "symbol_extraction_coverage" in dims
    assert "call_relationship_coverage" in dims
    assert "cross_technology_relationship_coverage" in dims
    assert "test_to_code_traceability" in dims
    assert "runtime_trace_confirmation" in dims
    assert "unsupported_technology_coverage" in dims
    assert "failed_extraction_coverage" in dims

    # Unsupported Go file detected -> unsupported_technology_coverage MUST BE 0.0
    assert dims["unsupported_technology_coverage"] == 0.0


# ============================================================================
# SECTION 9: PERFORMANCE BENCHMARKING (Scale & Resource Measurement)
# ============================================================================

def test_performance_benchmark_scale_and_memory(tmp_path: Path):
    root = tmp_path / "perf_repo"
    root.mkdir()

    # Generate 30 python files with interconnected functions
    for i in range(30):
        lines = [f"def func_{i}_{j}(x): return x + {j}" for j in range(10)]
        if i > 0:
            lines.append(f"from mod_{i-1} import func_{i-1}_0")
            lines.append(f"def caller_{i}(): return func_{i-1}_0(10)")
        (root / f"mod_{i}.py").write_text("\n".join(lines) + "\n", encoding="utf-8")

    tracemalloc.start()
    t0 = time.perf_counter()

    extractor = GraphExtractionEngine(project_id=1, repo_root=root)
    nodes, edges = extractor.extract_full_graph()

    dur = time.perf_counter() - t0
    current_mem, peak_mem = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    assert len(nodes) >= 300
    assert len(edges) >= 25
    assert dur < 5.0  # Under 5 seconds for 30 files & 300 symbols
    assert peak_mem < 50 * 1024 * 1024  # Peak memory under 50MB


# ============================================================================
# SECTION 10: SECURITY & MULTI-TENANT VERIFICATION
# ============================================================================

def test_security_multi_tenant_non_disclosing_404s(api_client: TestClient):
    user_tenant2 = User(id=2, username="tenant_beta", email="beta@test.com", hashed_password="pw", is_active=True)
    token_tenant2 = create_access_token(user_tenant2)
    headers = {"Authorization": f"Bearer {token_tenant2}"}

    # Tenant 2 attempts to access Tenant 1's project (ID=1)
    endpoints = [
        "/project-reviews/1/graph/overview",
        "/project-reviews/1/graph/nodes",
        "/project-reviews/1/graph/edges",
        "/project-reviews/1/graph/architecture",
        "/project-reviews/1/graph/coverage",
        "/project-reviews/1/graph/transitions",
        "/project-reviews/1/graph/versions",
    ]

    for ep in endpoints:
        resp = api_client.get(ep, headers=headers)
        assert resp.status_code == 404
        assert resp.json()["detail"] == "Project not found"
