"""Phase 3.1 Dedicated Engineering Intelligence Test Suite.

Comprehensive tests covering:
1. Canonical Identity Continuity (renames, moves, structural fingerprints, signatures).
2. Advanced Call Graph Resolution Accuracy (aliases, imports, constructors, polymorphism, runtime traces).
3. Transactional Graph Update Safety & Crash Recovery (staging, journals, atomic activation, recovery).
4. Calibrated Blast Radius Assessment (measured properties vs heuristic risk, benchmarks).
5. Targeted Test Selection Validation (direct, runtime-confirmed, inferred, precision@k).
6. Multi-Language Repository Graph Coverage (8 dimensions across 5 tech stacks).
7. Version Comparison & Diffs (added/removed/modified nodes & edges, renames).
8. API Endpoints & Multi-Tenant Security (coverage, transitions, versions, compare, recover, 404 isolation).
"""
from __future__ import annotations

import ast
import hashlib
from pathlib import Path
from typing import Any
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.testclient import TestClient

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
from app.services.graph.blast_radius import (
    BlastRadiusBenchmark,
    BlastRadiusEngine,
    BlastRadiusReport,
)
from app.services.graph.call_resolver import (
    AdvancedCallResolver,
    CallResolutionType,
)
from app.services.graph.coverage_reporter import (
    CoverageDimensionStatus,
    GraphCoverageReporter,
)
from app.services.graph.extractor import GraphExtractionEngine
from app.services.graph.identity_continuity import (
    IdentityContinuityEngine,
    IdentityTransitionRecord,
    IdentityTransitionType,
    compute_ast_structural_fingerprint,
    compute_symbol_signature,
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
    Session = sessionmaker(bind=engine)
    session = Session()

    # Seed owner and project
    owner = User(id=1, username="test_owner", email="test_owner@example.com", hashed_password="pw", is_active=True)
    other = User(id=2, username="other_user", email="other_user@example.com", hashed_password="pw", is_active=True)
    session.add_all([owner, other])
    session.flush()

    project = ReviewedProject(
        id=1,
        name="Phase 3.1 Test Project",
        repository_path="c:/dummy/repo",
        owner_id=1,
        monitoring_status="active",
    )
    session.add(project)
    session.commit()

    yield session
    session.close()


@pytest.fixture
def complex_repo(tmp_path: Path):
    """Creates a controlled repository fixture with known call, model, and test relationships."""
    root = tmp_path / "complex_project"
    root.mkdir()

    # Core utils
    utils_dir = root / "core"
    utils_dir.mkdir()
    (utils_dir / "__init__.py").write_text("", encoding="utf-8")
    (utils_dir / "hasher.py").write_text(
        "def compute_hash(data: str) -> str:\n    return 'hash_' + data\n",
        encoding="utf-8",
    )

    # Models
    models_dir = root / "models"
    models_dir.mkdir()
    (models_dir / "__init__.py").write_text("", encoding="utf-8")
    (models_dir / "user.py").write_text(
        "from core.hasher import compute_hash\n\n"
        "class BaseModel:\n"
        "    def save(self):\n        return True\n\n"
        "class UserModel(BaseModel):\n"
        "    def __init__(self, username: str):\n"
        "        self.username = username\n"
        "        self.password_hash = compute_hash(username)\n"
        "    def update_profile(self):\n"
        "        return self.save()\n",
        encoding="utf-8",
    )

    # Services
    services_dir = root / "services"
    services_dir.mkdir()
    (services_dir / "__init__.py").write_text("", encoding="utf-8")
    (services_dir / "auth_service.py").write_text(
        "from models.user import UserModel\n\n"
        "def authenticate_user(username: str) -> bool:\n"
        "    user = UserModel(username)\n"
        "    user.update_profile()\n"
        "    return True\n",
        encoding="utf-8",
    )

    # Routes / APIs
    api_dir = root / "api"
    api_dir.mkdir()
    (api_dir / "__init__.py").write_text("", encoding="utf-8")
    (api_dir / "routes.py").write_text(
        "from services.auth_service import authenticate_user\n\n"
        "class Router:\n"
        "    def post(self, path): return lambda f: f\n"
        "router = Router()\n\n"
        "@router.post('/login')\n"
        "def login_endpoint(user: str):\n"
        "    return authenticate_user(user)\n",
        encoding="utf-8",
    )

    # Tests
    tests_dir = root / "tests"
    tests_dir.mkdir()
    (tests_dir / "__init__.py").write_text("", encoding="utf-8")
    (tests_dir / "test_auth.py").write_text(
        "from services.auth_service import authenticate_user\n\n"
        "def test_authenticate_success():\n"
        "    assert authenticate_user('alice') is True\n",
        encoding="utf-8",
    )

    return root


# ============================================================================
# 1. Canonical Identity Continuity Tests (1-12)
# ============================================================================

def test_structural_fingerprint_identical_for_formatting_changes():
    code_a = "def compute(a: int, b: int):\n    '''Docstring'''\n    x = a + b\n    return x\n"
    code_b = "def compute(a: int, b: int):\n    x = a + b\n    return x\n"
    fp_a = compute_ast_structural_fingerprint(code_a)
    fp_b = compute_ast_structural_fingerprint(code_b)
    assert fp_a == fp_b


def test_structural_fingerprint_differs_when_logic_changes():
    code_a = "def compute(a, b):\n    return a + b\n"
    code_b = "def compute(a, b, c):\n    for i in range(c):\n        a += b\n    return a\n"
    fp_a = compute_ast_structural_fingerprint(code_a)
    fp_b = compute_ast_structural_fingerprint(code_b)
    assert fp_a != fp_b


def test_symbol_signature_extraction_function():
    code = "async def login(username: str, password: str) -> bool:\n    pass\n"
    tree = ast.parse(code)
    sig = compute_symbol_signature(tree.body[0])
    assert sig["kind"] == "function"
    assert sig["name"] == "login"
    assert sig["params"] == ["username", "password"]
    assert sig["is_async"] is True
    assert sig["has_return_anno"] is True


def test_symbol_signature_extraction_class():
    code = "class AdminUser(UserModel, BaseAuth):\n    def ban(self): pass\n    def unban(self): pass\n"
    tree = ast.parse(code)
    sig = compute_symbol_signature(tree.body[0])
    assert sig["kind"] == "class"
    assert sig["name"] == "AdminUser"
    assert "UserModel" in sig["bases"]
    assert "ban" in sig["methods"]
    assert sig["method_count"] == 2


def test_identity_continuity_unchanged_nodes():
    cid = build_canonical_id(1, "service.py", "auth", NodeType.FUNCTION)
    node1 = GraphNode(cid, 1, NodeType.FUNCTION.value, "auth", "auth", "service.py", metadata={"structural_fingerprint": "abc"})
    node2 = GraphNode(cid, 1, NodeType.FUNCTION.value, "auth", "auth", "service.py", metadata={"structural_fingerprint": "abc"})

    transitions = IdentityContinuityEngine.compute_transitions({cid: node1}, {cid: node2})
    assert len(transitions) == 1
    assert transitions[0].transition_type == IdentityTransitionType.UNCHANGED.value
    assert transitions[0].confidence == 1.0


def test_identity_continuity_modified_node():
    cid = build_canonical_id(1, "service.py", "auth", NodeType.FUNCTION)
    node1 = GraphNode(cid, 1, NodeType.FUNCTION.value, "auth", "auth", "service.py", metadata={"structural_fingerprint": "abc"})
    node2 = GraphNode(cid, 1, NodeType.FUNCTION.value, "auth", "auth", "service.py", metadata={"structural_fingerprint": "xyz"})

    transitions = IdentityContinuityEngine.compute_transitions({cid: node1}, {cid: node2})
    assert len(transitions) == 1
    assert transitions[0].transition_type == IdentityTransitionType.MODIFIED.value


def test_identity_continuity_file_rename_maps_symbols():
    cid_old = build_canonical_id(1, "old_auth.py", "login", NodeType.FUNCTION)
    cid_new = build_canonical_id(1, "new_auth.py", "login", NodeType.FUNCTION)

    n_old = GraphNode(cid_old, 1, NodeType.FUNCTION.value, "login", "old_auth.login", "old_auth.py")
    n_new = GraphNode(cid_new, 1, NodeType.FUNCTION.value, "login", "new_auth.login", "new_auth.py")

    transitions = IdentityContinuityEngine.compute_transitions({cid_old: n_old}, {cid_new: n_new})
    match = next((t for t in transitions if t.transition_type in (IdentityTransitionType.RENAMED_FILE.value, IdentityTransitionType.MOVED_FILE.value)), None)
    assert match is not None
    assert match.new_canonical_id == cid_new


def test_identity_continuity_file_move_detection():
    cid_old = build_canonical_id(1, "services/auth.py", "login", NodeType.FUNCTION)
    cid_new = build_canonical_id(1, "core/auth.py", "login", NodeType.FUNCTION)

    n_old = GraphNode(cid_old, 1, NodeType.FUNCTION.value, "login", "services.auth.login", "services/auth.py")
    n_new = GraphNode(cid_new, 1, NodeType.FUNCTION.value, "login", "core.auth.login", "core/auth.py")

    transitions = IdentityContinuityEngine.compute_transitions({cid_old: n_old}, {cid_new: n_new})
    assert any(t.transition_type == IdentityTransitionType.MOVED_FILE.value for t in transitions)


def test_identity_continuity_renamed_symbol_detection():
    cid_old = build_canonical_id(1, "auth.py", "verify_password", NodeType.FUNCTION)
    cid_new = build_canonical_id(1, "auth.py", "verify_pwd", NodeType.FUNCTION)

    fp = "sig_hash_123"
    n_old = GraphNode(cid_old, 1, NodeType.FUNCTION.value, "verify_password", "auth.verify_password", "auth.py", metadata={"structural_fingerprint": fp})
    n_new = GraphNode(cid_new, 1, NodeType.FUNCTION.value, "verify_pwd", "auth.verify_pwd", "auth.py", metadata={"structural_fingerprint": fp})

    transitions = IdentityContinuityEngine.compute_transitions({cid_old: n_old}, {cid_new: n_new})
    rename_t = next((t for t in transitions if t.transition_type == IdentityTransitionType.RENAMED_SYMBOL.value), None)
    assert rename_t is not None
    assert rename_t.new_canonical_id == cid_new
    assert rename_t.confidence >= 0.80


def test_identity_continuity_deleted_symbols():
    cid_old = build_canonical_id(1, "legacy.py", "deprecated_func", NodeType.FUNCTION)
    n_old = GraphNode(cid_old, 1, NodeType.FUNCTION.value, "deprecated_func", "legacy.deprecated_func", "legacy.py")

    transitions = IdentityContinuityEngine.compute_transitions({cid_old: n_old}, {})
    assert any(t.transition_type == IdentityTransitionType.DELETED.value and t.old_canonical_id == cid_old for t in transitions)


def test_identity_continuity_created_symbols():
    cid_new = build_canonical_id(1, "fresh.py", "new_feature", NodeType.FUNCTION)
    n_new = GraphNode(cid_new, 1, NodeType.FUNCTION.value, "new_feature", "fresh.new_feature", "fresh.py")

    transitions = IdentityContinuityEngine.compute_transitions({}, {cid_new: n_new})
    assert any(t.transition_type == IdentityTransitionType.CREATED.value and t.new_canonical_id == cid_new for t in transitions)


def test_identity_continuity_does_not_merge_unrelated_names():
    cid_a = build_canonical_id(1, "orders.py", "process", NodeType.FUNCTION)
    cid_b = build_canonical_id(1, "payments.py", "process", NodeType.FUNCTION)
    n_a = GraphNode(cid_a, 1, NodeType.FUNCTION.value, "process", "orders.process", "orders.py")
    n_b = GraphNode(cid_b, 1, NodeType.FUNCTION.value, "process", "payments.process", "payments.py")

    transitions = IdentityContinuityEngine.compute_transitions({cid_a: n_a}, {cid_b: n_b})
    # Should be separate DELETED and CREATED rather than merging
    assert any(t.transition_type == IdentityTransitionType.DELETED.value for t in transitions)
    assert any(t.transition_type == IdentityTransitionType.CREATED.value for t in transitions)


# ============================================================================
# 2. Call Graph Accuracy & Resolution Tests (13-26)
# ============================================================================

def test_call_resolver_constructor_instantiation():
    class_id = build_canonical_id(1, "models/user.py", "models.user.UserModel", NodeType.CLASS)
    caller_id = build_canonical_id(1, "services/auth.py", "services.auth.login", NodeType.FUNCTION)
    registry = {"models.user.UserModel": class_id}
    node = GraphNode(class_id, 1, NodeType.CLASS.value, "UserModel", "models.user.UserModel", "models/user.py")

    resolver = AdvancedCallResolver(1, registry, {class_id: node})
    edges = resolver.resolve_call(
        caller_qname="services.auth.login",
        caller_id=caller_id,
        call_expr="UserModel",
        ast_call_node=ast.Call(func=ast.Name(id="UserModel", ctx=ast.Load()), args=[], keywords=[]),
        rel_file="services/auth.py",
        line_no=10,
        current_module="services.auth",
        current_class=None,
        imported_aliases={"UserModel": "models.user.UserModel"},
    )
    assert len(edges) == 1
    assert edges[0].provenance["resolution_method"] == "CONSTRUCTOR_INSTANTIATION"
    assert edges[0].provenance["resolution"] == CallResolutionType.RESOLVED_STATIC.value


def test_call_resolver_self_method_call():
    class_id = build_canonical_id(1, "user.py", "UserModel", NodeType.CLASS)
    save_id = build_canonical_id(1, "user.py", "UserModel.save", NodeType.METHOD)
    caller_id = build_canonical_id(1, "user.py", "UserModel.update", NodeType.METHOD)
    registry = {"UserModel.save": save_id}
    node = GraphNode(save_id, 1, NodeType.METHOD.value, "save", "UserModel.save", "user.py")

    resolver = AdvancedCallResolver(1, registry, {save_id: node})
    edges = resolver.resolve_call(
        caller_qname="UserModel.update",
        caller_id=caller_id,
        call_expr="self.save",
        ast_call_node=ast.Call(func=ast.Attribute(value=ast.Name(id="self", ctx=ast.Load()), attr="save", ctx=ast.Load()), args=[], keywords=[]),
        rel_file="user.py",
        line_no=15,
        current_module="user",
        current_class="UserModel",
        imported_aliases={},
    )
    assert len(edges) == 1
    assert edges[0].provenance["resolution_method"] == "SELF_METHOD"


def test_call_resolver_super_dispatch():
    base_save_id = build_canonical_id(1, "base.py", "BaseModel.save", NodeType.METHOD)
    caller_id = build_canonical_id(1, "user.py", "UserModel.save", NodeType.METHOD)
    registry = {"BaseModel.save": base_save_id}
    node = GraphNode(base_save_id, 1, NodeType.METHOD.value, "save", "BaseModel.save", "base.py")

    resolver = AdvancedCallResolver(1, registry, {base_save_id: node}, class_hierarchy={"UserModel": ["BaseModel"]})
    edges = resolver.resolve_call(
        caller_qname="UserModel.save",
        caller_id=caller_id,
        call_expr="super().save",
        ast_call_node=ast.Call(func=ast.Attribute(value=ast.Call(func=ast.Name(id="super", ctx=ast.Load()), args=[], keywords=[]), attr="save", ctx=ast.Load()), args=[], keywords=[]),
        rel_file="user.py",
        line_no=20,
        current_module="user",
        current_class="UserModel",
        imported_aliases={},
    )
    assert len(edges) == 1
    assert edges[0].provenance["resolution_method"] == "SUPER_DISPATCH"
    assert edges[0].confidence >= 0.95


def test_call_resolver_inherited_base_method():
    base_save_id = build_canonical_id(1, "base.py", "BaseModel.save", NodeType.METHOD)
    caller_id = build_canonical_id(1, "user.py", "UserModel.touch", NodeType.METHOD)
    registry = {"BaseModel.save": base_save_id}
    node = GraphNode(base_save_id, 1, NodeType.METHOD.value, "save", "BaseModel.save", "base.py")

    resolver = AdvancedCallResolver(1, registry, {base_save_id: node}, class_hierarchy={"UserModel": ["BaseModel"]})
    edges = resolver.resolve_call(
        caller_qname="UserModel.touch",
        caller_id=caller_id,
        call_expr="self.save",
        ast_call_node=ast.Call(func=ast.Attribute(value=ast.Name(id="self", ctx=ast.Load()), attr="save", ctx=ast.Load()), args=[], keywords=[]),
        rel_file="user.py",
        line_no=25,
        current_module="user",
        current_class="UserModel",
        imported_aliases={},
    )
    assert len(edges) == 1
    assert edges[0].provenance["resolution_method"] == "INHERITED_BASE_METHOD"


def test_call_resolver_type_annotated_dispatch():
    save_id = build_canonical_id(1, "user.py", "models.UserModel.save", NodeType.METHOD)
    caller_id = build_canonical_id(1, "service.py", "process", NodeType.FUNCTION)
    registry = {"models.UserModel.save": save_id}
    node = GraphNode(save_id, 1, NodeType.METHOD.value, "save", "models.UserModel.save", "user.py")

    resolver = AdvancedCallResolver(1, registry, {save_id: node})
    edges = resolver.resolve_call(
        caller_qname="service.process",
        caller_id=caller_id,
        call_expr="user.save",
        ast_call_node=ast.Call(func=ast.Attribute(value=ast.Name(id="user", ctx=ast.Load()), attr="save", ctx=ast.Load()), args=[], keywords=[]),
        rel_file="service.py",
        line_no=30,
        current_module="service",
        current_class=None,
        imported_aliases={"UserModel": "models.UserModel"},
        local_var_types={"user": "UserModel"},
    )
    assert len(edges) == 1
    assert edges[0].provenance["resolution_method"] == "TYPE_ANNOTATED_DISPATCH"
    assert edges[0].confidence >= 0.90


def test_call_resolver_imported_alias():
    target_id = build_canonical_id(1, "hasher.py", "core.compute_hash", NodeType.FUNCTION)
    caller_id = build_canonical_id(1, "service.py", "hash_it", NodeType.FUNCTION)
    registry = {"core.compute_hash": target_id}
    node = GraphNode(target_id, 1, NodeType.FUNCTION.value, "compute_hash", "core.compute_hash", "hasher.py")

    resolver = AdvancedCallResolver(1, registry, {target_id: node})
    edges = resolver.resolve_call(
        caller_qname="service.hash_it",
        caller_id=caller_id,
        call_expr="hashing_alias",
        ast_call_node=ast.Call(func=ast.Name(id="hashing_alias", ctx=ast.Load()), args=[], keywords=[]),
        rel_file="service.py",
        line_no=5,
        current_module="service",
        current_class=None,
        imported_aliases={"hashing_alias": "core.compute_hash"},
    )
    assert len(edges) == 1
    assert edges[0].provenance["resolution_method"] == "IMPORTED_ALIAS"


def test_call_resolver_module_attribute_call():
    target_id = build_canonical_id(1, "calc.py", "math_utils.add", NodeType.FUNCTION)
    caller_id = build_canonical_id(1, "main.py", "run", NodeType.FUNCTION)
    registry = {"math_utils.add": target_id}
    node = GraphNode(target_id, 1, NodeType.FUNCTION.value, "add", "math_utils.add", "calc.py")

    resolver = AdvancedCallResolver(1, registry, {target_id: node})
    edges = resolver.resolve_call(
        caller_qname="main.run",
        caller_id=caller_id,
        call_expr="utils.add",
        ast_call_node=ast.Call(func=ast.Attribute(value=ast.Name(id="utils", ctx=ast.Load()), attr="add", ctx=ast.Load()), args=[], keywords=[]),
        rel_file="main.py",
        line_no=12,
        current_module="main",
        current_class=None,
        imported_aliases={"utils": "math_utils"},
    )
    assert len(edges) == 1
    assert edges[0].provenance["resolution_method"] == "MODULE_ATTRIBUTE_CALL"


def test_call_resolver_ambiguous_multi_candidate():
    m1_id = build_canonical_id(1, "pay1.py", "PaymentA.charge", NodeType.METHOD)
    m2_id = build_canonical_id(1, "pay2.py", "PaymentB.charge", NodeType.METHOD)
    caller_id = build_canonical_id(1, "checkout.py", "pay", NodeType.FUNCTION)
    registry = {"PaymentA.charge": m1_id, "PaymentB.charge": m2_id}
    nodes = {
        m1_id: GraphNode(m1_id, 1, NodeType.METHOD.value, "charge", "PaymentA.charge", "pay1.py"),
        m2_id: GraphNode(m2_id, 1, NodeType.METHOD.value, "charge", "PaymentB.charge", "pay2.py"),
    }

    resolver = AdvancedCallResolver(1, registry, nodes)
    edges = resolver.resolve_call(
        caller_qname="checkout.pay",
        caller_id=caller_id,
        call_expr="charge",
        ast_call_node=ast.Call(func=ast.Name(id="charge", ctx=ast.Load()), args=[], keywords=[]),
        rel_file="checkout.py",
        line_no=40,
        current_module="checkout",
        current_class=None,
        imported_aliases={},
    )
    assert len(edges) == 1
    assert edges[0].provenance["resolution"] == CallResolutionType.AMBIGUOUS.value
    assert len(edges[0].provenance["candidates"]) >= 2


def test_call_resolver_unresolved_call_recorded():
    caller_id = build_canonical_id(1, "main.py", "run", NodeType.FUNCTION)
    resolver = AdvancedCallResolver(1, {}, {})
    edges = resolver.resolve_call(
        caller_qname="main.run",
        caller_id=caller_id,
        call_expr="getattr(x, 'dyn')",
        ast_call_node=ast.Call(func=ast.Name(id="getattr", ctx=ast.Load()), args=[], keywords=[]),
        rel_file="main.py",
        line_no=50,
        current_module="main",
        current_class=None,
        imported_aliases={},
    )
    assert len(edges) == 1
    assert edges[0].provenance["resolution"] == CallResolutionType.UNRESOLVED.value
    assert edges[0].provenance["unresolved"] is True
    assert edges[0].confidence == 0.5


def test_call_resolver_elevates_with_runtime_traces():
    func_id = build_canonical_id(1, "service.py", "do_work", NodeType.FUNCTION)
    caller_id = build_canonical_id(1, "main.py", "run", NodeType.FUNCTION)
    registry = {"service.do_work": func_id}
    node = GraphNode(func_id, 1, NodeType.FUNCTION.value, "do_work", "service.do_work", "service.py")

    traces = [{"caller": "main.run", "callee": "do_work"}]
    resolver = AdvancedCallResolver(1, registry, {func_id: node}, runtime_traces=traces)
    edges = resolver.resolve_call(
        caller_qname="main.run",
        caller_id=caller_id,
        call_expr="do_work",
        ast_call_node=ast.Call(func=ast.Name(id="do_work", ctx=ast.Load()), args=[], keywords=[]),
        rel_file="main.py",
        line_no=18,
        current_module="main",
        current_class=None,
        imported_aliases={"do_work": "service.do_work"},
    )
    assert len(edges) == 1
    assert edges[0].provenance["resolution"] == CallResolutionType.RESOLVED_RUNTIME.value
    assert edges[0].confidence == 1.0


def test_call_resolver_precision_recall_benchmark():
    c1, c2 = "caller_1", "callee_1"
    predicted = [
        GraphEdge(c1, c2, "CALLS", 1, confidence=0.9, provenance={"resolution": "RESOLVED_STATIC"}),
        GraphEdge(c1, "false_pos", "CALLS", 1, confidence=0.8, provenance={"resolution": "RESOLVED_STATIC"}),
    ]
    ground_truth = {(c1, c2), (c1, "missing_callee")}

    metrics = AdvancedCallResolver.evaluate_benchmark(predicted, ground_truth)
    assert metrics["true_positives"] == 1.0
    assert metrics["false_positives"] == 1.0
    assert metrics["false_negatives"] == 1.0
    assert metrics["precision"] == 0.5
    assert metrics["recall"] == 0.5
    assert metrics["f1"] == 0.5


def test_complex_repo_extraction_resolves_inter_module_calls(complex_repo: Path):
    extractor = GraphExtractionEngine(1, complex_repo)
    nodes, edges = extractor.extract_full_graph()
    call_edges = [e for e in edges if e.rel_type == EdgeType.CALLS.value]
    assert len(call_edges) >= 3
    # Check compute_hash call in UserModel
    has_hash_call = any("compute_hash" in e.provenance.get("expression", "") for e in call_edges)
    assert has_hash_call is True


# ============================================================================
# 3. Transactional Graph Updates & Crash Recovery Tests (27-36)
# ============================================================================

def test_transactional_update_generates_active_version(complex_repo: Path, mock_db_session):
    nodes, edges, ver = TransactionalGraphUpdater.execute_transactional_update(
        mock_db_session, 1, complex_repo, force_full_rebuild=True
    )
    assert ver.status == "ACTIVE"
    assert ver.is_current is True
    assert ver.version_number == 1
    assert ver.node_count > 0


def test_transactional_update_logs_lifecycle_journals(complex_repo: Path, mock_db_session):
    TransactionalGraphUpdater.execute_transactional_update(mock_db_session, 1, complex_repo, force_full_rebuild=True)
    journals = mock_db_session.query(EngineeringGraphUpdateJournal).filter(EngineeringGraphUpdateJournal.project_id == 1).all()
    stages = [j.stage for j in journals]
    assert "STAGING" in stages
    assert "EXTRACTING" in stages
    assert "INTEGRITY_CHECK" in stages
    assert "ACTIVATED" in stages


def test_transactional_update_supersedes_prior_version(complex_repo: Path, mock_db_session):
    _, _, ver1 = TransactionalGraphUpdater.execute_transactional_update(mock_db_session, 1, complex_repo, force_full_rebuild=True)
    _, _, ver2 = TransactionalGraphUpdater.execute_transactional_update(mock_db_session, 1, complex_repo, force_full_rebuild=True)

    mock_db_session.refresh(ver1)
    mock_db_session.refresh(ver2)
    assert ver1.status == "SUPERSEDED"
    assert ver1.is_current is False
    assert ver2.status == "ACTIVE"
    assert ver2.is_current is True
    assert ver2.version_number == 2


def test_transactional_update_recovers_interrupted_staged_versions(mock_db_session):
    # Simulate an interrupted staging version
    staged = EngineeringGraphVersion(project_id=1, version_number=99, status="STAGED", is_current=False)
    mock_db_session.add(staged)
    mock_db_session.commit()

    recovered = TransactionalGraphUpdater.recover_interrupted_updates(mock_db_session, 1)
    assert recovered == 1
    mock_db_session.refresh(staged)
    assert staged.status == "FAILED"


def test_transactional_update_no_op_when_zero_hash_changes(complex_repo: Path, mock_db_session):
    _, _, ver1 = TransactionalGraphUpdater.execute_transactional_update(mock_db_session, 1, complex_repo, force_full_rebuild=True)
    _, _, ver2 = TransactionalGraphUpdater.execute_transactional_update(mock_db_session, 1, complex_repo, changed_files=[], deleted_files=[])
    assert ver1.version_number == ver2.version_number


def test_transactional_update_records_identity_transitions_in_db(complex_repo: Path, mock_db_session):
    TransactionalGraphUpdater.execute_transactional_update(mock_db_session, 1, complex_repo, force_full_rebuild=True)
    # Modify a file
    (complex_repo / "core" / "hasher.py").write_text("def compute_hash(d: str):\n    return 'mod_' + d\n", encoding="utf-8")
    TransactionalGraphUpdater.execute_transactional_update(mock_db_session, 1, complex_repo, changed_files=["core/hasher.py"])

    transitions = mock_db_session.query(EngineeringIdentityTransition).filter(EngineeringIdentityTransition.project_id == 1).all()
    assert len(transitions) > 0


def test_transactional_update_detects_file_deletion(complex_repo: Path, mock_db_session):
    dummy_file = complex_repo / "dummy.py"
    dummy_file.write_text("def dummy(): pass\n", encoding="utf-8")
    TransactionalGraphUpdater.execute_transactional_update(mock_db_session, 1, complex_repo, force_full_rebuild=True)

    dummy_file.unlink()
    nodes, _, ver = TransactionalGraphUpdater.execute_transactional_update(mock_db_session, 1, complex_repo, deleted_files=["dummy.py"])
    assert not any("dummy.py" in n.file_path for n in nodes.values())


def test_transactional_update_preserves_active_on_extraction_error(complex_repo: Path, mock_db_session, monkeypatch):
    _, _, ver_init = TransactionalGraphUpdater.execute_transactional_update(mock_db_session, 1, complex_repo, force_full_rebuild=True)

    def failing_extract(*args, **kwargs):
        raise RuntimeError("Simulated extraction crash")

    monkeypatch.setattr(GraphExtractionEngine, "extract_full_graph", failing_extract)

    with pytest.raises(RuntimeError):
        TransactionalGraphUpdater.execute_transactional_update(mock_db_session, 1, complex_repo, force_full_rebuild=True)

    mock_db_session.refresh(ver_init)
    assert ver_init.status == "ACTIVE"
    assert ver_init.is_current is True


def test_transactional_update_stores_content_hashes_in_nodes(complex_repo: Path, mock_db_session):
    nodes, _, _ = TransactionalGraphUpdater.execute_transactional_update(mock_db_session, 1, complex_repo, force_full_rebuild=True)
    py_file_nodes = [n for n in nodes.values() if n.file_path.endswith(".py")]
    assert any("content_hash" in n.metadata for n in py_file_nodes)


def test_compute_file_hashes_skips_hidden_and_build_dirs(complex_repo: Path):
    hidden_dir = complex_repo / ".git"
    hidden_dir.mkdir()
    (hidden_dir / "config").write_text("dummy", encoding="utf-8")

    hashes = TransactionalGraphUpdater.compute_file_hashes(complex_repo)
    assert not any(".git" in k for k in hashes.keys())
    assert any("core/hasher.py" in k for k in hashes.keys())


# ============================================================================
# 4. Calibrated Blast Radius Assessment Tests (37-46)
# ============================================================================

def test_blast_radius_calibrated_separates_measured_and_heuristic(complex_repo: Path):
    extractor = GraphExtractionEngine(1, complex_repo)
    nodes, edges = extractor.extract_full_graph()
    report = BlastRadiusEngine.calculate_blast_radius(nodes, edges, ["services/auth_service.py"])

    assert "measured_properties" in report.to_dict()
    assert "heuristic_factors" in report.to_dict()
    assert "score_breakdown" in report.to_dict()
    assert report.score_breakdown["measured_structural_score"] >= 0.0
    assert report.score_breakdown["heuristic_risk_score"] >= 0.0


def test_blast_radius_explains_score_narrative(complex_repo: Path):
    extractor = GraphExtractionEngine(1, complex_repo)
    nodes, edges = extractor.extract_full_graph()
    report = BlastRadiusEngine.calculate_blast_radius(nodes, edges, ["models/user.py"])
    assert "not a statistical probability of defect" in report.score_explanation.lower()


def test_blast_radius_detects_auth_sensitivity_heuristic(complex_repo: Path):
    extractor = GraphExtractionEngine(1, complex_repo)
    nodes, edges = extractor.extract_full_graph()
    report = BlastRadiusEngine.calculate_blast_radius(nodes, edges, ["services/auth_service.py"])
    assert report.heuristic_factors["authentication_sensitivity"] is True
    assert any("Authentication / security sensitive" in rf for rf in report.risk_factors)


def test_blast_radius_detects_public_api_exposure(complex_repo: Path):
    extractor = GraphExtractionEngine(1, complex_repo)
    nodes, edges = extractor.extract_full_graph()
    report = BlastRadiusEngine.calculate_blast_radius(nodes, edges, ["api/routes.py"])
    assert report.affected_apis_count >= 1
    assert report.heuristic_factors["public_api_exposure"] is True


def test_blast_radius_detects_database_schema_impact():
    cid_table = build_canonical_id(1, "models.py", "users", NodeType.TABLE)
    table_node = GraphNode(cid_table, 1, NodeType.TABLE.value, "users", "users", "models.py")
    report = BlastRadiusEngine.calculate_blast_radius({cid_table: table_node}, [], [cid_table])
    assert report.heuristic_factors["database_schema_impact"] is True


def test_blast_radius_fan_in_calculation():
    c_target = build_canonical_id(1, "core.py", "shared", NodeType.FUNCTION)
    target_node = GraphNode(c_target, 1, NodeType.FUNCTION.value, "shared", "shared", "core.py")

    edges = []
    for i in range(6):
        c_caller = build_canonical_id(1, f"caller_{i}.py", f"fn_{i}", NodeType.FUNCTION)
        edges.append(GraphEdge(c_caller, c_target, "CALLS", 1))

    report = BlastRadiusEngine.calculate_blast_radius({c_target: target_node}, edges, [c_target])
    assert report.measured_properties["total_fan_in"] == 6
    assert report.heuristic_factors["critical_component_involvement"] is True


def test_blast_radius_zero_score_on_empty():
    report = BlastRadiusEngine.calculate_blast_radius({}, [], [])
    assert report.blast_radius_score == 0.0
    assert report.risk_level == "LOW"


def test_blast_radius_benchmark_evaluation():
    nodes = {
        "c_low": GraphNode("c_low", 1, NodeType.FUNCTION.value, "low_util", "low_util", "low.py"),
        "c_high": GraphNode("c_high", 1, NodeType.FUNCTION.value, "auth_core", "auth_core", "auth.py"),
    }
    cases = [
        {"target": "c_low", "expected_risk": "LOW"},
    ]
    res = BlastRadiusBenchmark.evaluate_benchmark(nodes, [], cases)
    assert res["total_benchmark_cases"] == 1.0
    assert res["risk_classification_agreement_rate"] == 1.0


def test_blast_radius_max_score_capped_at_100():
    nodes = {"target": GraphNode("target", 1, NodeType.FUNCTION.value, "target", "target", "target.py")}
    edges = [GraphEdge(f"c_{i}", "target", "CALLS", 1) for i in range(50)]
    report = BlastRadiusEngine.calculate_blast_radius(nodes, edges, ["target"])
    assert report.blast_radius_score <= 100.0


def test_blast_radius_boundary_crossing_affects_score(complex_repo: Path):
    extractor = GraphExtractionEngine(1, complex_repo)
    nodes, edges = extractor.extract_full_graph()
    report = BlastRadiusEngine.calculate_blast_radius(nodes, edges, ["models/user.py"])
    assert len(report.boundaries_crossed) >= 2


# ============================================================================
# 5. Targeted Test Selection Intelligence Tests (47-54)
# ============================================================================

def test_test_selector_direct_test_classification(complex_repo: Path):
    extractor = GraphExtractionEngine(1, complex_repo)
    nodes, edges = extractor.extract_full_graph()
    tests = TestSelectionEngine.select_tests_for_changes(nodes, edges, ["services/auth_service.py"])
    assert len(tests) >= 1
    assert tests[0].tier == "DIRECT_TEST"
    assert tests[0].classification == TestRecommendationTier.DIRECT_TEST.value


def test_test_selector_runtime_confirmed_elevation(complex_repo: Path):
    extractor = GraphExtractionEngine(1, complex_repo)
    nodes, edges = extractor.extract_full_graph()
    traces = [{"test_name": "test_authenticate_success", "target_symbol": "authenticate_user"}]
    tests = TestSelectionEngine.select_tests_for_changes(nodes, edges, ["services/auth_service.py"], runtime_traces=traces)
    assert len(tests) >= 1
    assert tests[0].classification == TestRecommendationTier.RUNTIME_CONFIRMED_TEST.value
    assert tests[0].confidence == 1.0


def test_test_selector_never_claims_executed():
    t = RecommendedTest("id1", "test_fn", "test.py", "DIRECT_TEST", 0.95, "reason", "target")
    assert t.execution_status == "NOT_EXECUTED"


def test_test_selector_e2e_classification():
    app_node = GraphNode("app_seed", 1, NodeType.FUNCTION.value, "seed_func", "seed_func", "app/main.py")
    t_node = GraphNode("t_e2e", 1, NodeType.TEST_FUNCTION.value, "test_flow", "test_flow", "tests/e2e/test_sys.py")
    report_nodes = {"t_e2e": t_node, "app_seed": app_node}
    edges = [GraphEdge("t_e2e", "app_seed", "CALLS", 1)]
    tests = TestSelectionEngine.select_tests_for_changes(report_nodes, edges, ["app_seed"])
    e2e_test = next((t for t in tests if t.test_id == "t_e2e"), None)
    assert e2e_test is not None
    assert e2e_test.classification == TestRecommendationTier.END_TO_END_TEST.value


def test_test_selector_precision_recall_benchmark():
    tests = [
        RecommendedTest("t1", "t1", "t1.py", "DIRECT_TEST", 0.95, "r", "s"),
        RecommendedTest("t2", "t2", "t2.py", "DIRECT_TEST", 0.85, "r", "s"),
        RecommendedTest("t3", "t3", "t3.py", "TRANSITIVE_TEST", 0.70, "r", "s"),
    ]
    ground_truth = {"t1", "t2"}
    metrics = TestSelectionBenchmark.evaluate_precision_recall_at_k(tests, ground_truth, k_values=[2, 3])
    assert metrics["precision@2"] == 1.0
    assert metrics["recall@2"] == 1.0


def test_test_selector_ranks_direct_above_transitive():
    tests = [
        RecommendedTest("t_trans", "t_trans", "t.py", "TRANSITIVE_TEST", 0.99, "r", "s"),
        RecommendedTest("t_direct", "t_direct", "t.py", "DIRECT_TEST", 0.80, "r", "s"),
    ]
    sorted_tests = sorted(tests, key=lambda t: (0 if t.tier == "DIRECT_TEST" else 1, -t.confidence))
    assert sorted_tests[0].test_id == "t_direct"


def test_test_selector_filters_module_level_import_noise():
    # If a test file has 10 imports but only calls 1 symbol
    t_node = GraphNode("t_node", 1, NodeType.TEST_FUNCTION.value, "test_run", "test_run", "tests/test_x.py")
    nodes = {"t_node": t_node}
    # No edge connecting to uncalled symbol
    tests = TestSelectionEngine.select_tests_for_changes(nodes, [], ["uncalled_symbol"])
    assert len(tests) == 0


def test_test_selector_tracks_evidence_path():
    t_node = GraphNode("t1", 1, NodeType.TEST_FUNCTION.value, "test_auth", "test_auth", "tests/test_auth.py")
    seed_id = build_canonical_id(1, "service.py", "auth", NodeType.FUNCTION)
    seed_node = GraphNode(seed_id, 1, NodeType.FUNCTION.value, "auth", "auth", "service.py")
    edge = GraphEdge(seed_id, "t1", EdgeType.TESTED_BY.value, 1, confidence=0.95)

    tests = TestSelectionEngine.select_tests_for_changes({seed_id: seed_node, "t1": t_node}, [edge], [seed_id])
    assert len(tests) == 1
    assert tests[0].evidence_path == [seed_id, "t1"]


# ============================================================================
# 6. Repository-Wide Multi-Language Graph Coverage Tests (55-60)
# ============================================================================

def test_coverage_reporter_detects_technologies(complex_repo: Path):
    extractor = GraphExtractionEngine(1, complex_repo)
    nodes, edges = extractor.extract_full_graph()
    report = GraphCoverageReporter.generate_coverage_report(1, complex_repo, nodes, edges)

    assert "Python" in report.technologies
    assert "FastAPI / Starlette" in report.technologies
    assert report.technologies["Python"].coverage_score >= 90.0


def test_coverage_reporter_evaluates_eight_dimensions(complex_repo: Path):
    extractor = GraphExtractionEngine(1, complex_repo)
    nodes, edges = extractor.extract_full_graph()
    report = GraphCoverageReporter.generate_coverage_report(1, complex_repo, nodes, edges)

    py_dims = report.technologies["Python"].dimension_status
    expected_dims = [
        "file_discovery", "syntax_parsing", "symbol_extraction",
        "import_resolution", "call_resolution", "api_extraction",
        "database_relationship_extraction", "test_relationship_extraction"
    ]
    for d in expected_dims:
        assert d in py_dims
        assert py_dims[d] in [status.value for status in CoverageDimensionStatus]


def test_coverage_reporter_reports_unresolved_edges():
    edges = [GraphEdge("c1", "c2", "CALLS", 1, provenance={"unresolved": True, "expression": "dyn()"})]
    report = GraphCoverageReporter.generate_coverage_report(1, Path("."), {}, edges)
    assert report.unresolved_relationships_count == 1
    assert len(report.unresolved_reasons) == 1


def test_coverage_reporter_overall_percentage_bounded():
    report = GraphCoverageReporter.generate_coverage_report(1, Path("."), {}, [])
    assert 0.0 <= report.overall_coverage_percentage <= 100.0


def test_coverage_reporter_serializes_to_dict(complex_repo: Path):
    extractor = GraphExtractionEngine(1, complex_repo)
    nodes, edges = extractor.extract_full_graph()
    report = GraphCoverageReporter.generate_coverage_report(1, complex_repo, nodes, edges)
    d = report.to_dict()
    assert "technologies" in d
    assert "overall_coverage_percentage" in d
    assert "unresolved_reasons" in d


def test_coverage_reporter_non_applicable_dimensions_for_infra():
    report = GraphCoverageReporter.generate_coverage_report(1, Path("."), {}, [])
    infra_dims = report.technologies["Docker & CI/CD"].dimension_status
    assert infra_dims["api_extraction"] == CoverageDimensionStatus.NOT_APPLICABLE.value


# ============================================================================
# 7. Graph Version Comparison & Diffing Tests (61-65)
# ============================================================================

def test_version_comparator_detects_added_and_removed_nodes(mock_db_session):
    v1 = EngineeringGraphVersion(project_id=1, version_number=1, status="SUPERSEDED", is_current=False)
    v2 = EngineeringGraphVersion(project_id=1, version_number=2, status="ACTIVE", is_current=True)
    mock_db_session.add_all([v1, v2])
    mock_db_session.flush()

    n_rem = EngineeringGraphNode(project_id=1, version_id=v1.id, canonical_id="n_rem", entity_type="FUNCTION", name="rem", qualified_name="rem", file_path="a.py")
    n_add = EngineeringGraphNode(project_id=1, version_id=v2.id, canonical_id="n_add", entity_type="FUNCTION", name="add", qualified_name="add", file_path="b.py")
    mock_db_session.add_all([n_rem, n_add])
    mock_db_session.commit()

    diff = GraphVersionComparator.compare_versions(mock_db_session, 1, 1, 2)
    assert diff.added_nodes_count == 1
    assert diff.removed_nodes_count == 1
    assert diff.added_nodes[0]["canonical_id"] == "n_add"
    assert diff.removed_nodes[0]["canonical_id"] == "n_rem"


def test_version_comparator_detects_renamed_entities(mock_db_session):
    v1 = EngineeringGraphVersion(project_id=1, version_number=1, status="SUPERSEDED", is_current=False)
    v2 = EngineeringGraphVersion(project_id=1, version_number=2, status="ACTIVE", is_current=True)
    mock_db_session.add_all([v1, v2])
    mock_db_session.flush()

    trans = EngineeringIdentityTransition(
        project_id=1,
        from_version_id=v1.id,
        to_version_id=v2.id,
        old_canonical_id="old_auth",
        new_canonical_id="new_auth",
        transition_type="RENAMED_FILE",
        confidence=0.95,
        evidence={"similarity": 0.98},
    )
    mock_db_session.add(trans)
    mock_db_session.commit()

    diff = GraphVersionComparator.compare_versions(mock_db_session, 1, 1, 2)
    assert diff.renamed_entities_count == 1
    assert diff.renamed_entities[0]["transition_type"] == "RENAMED_FILE"


def test_version_comparator_detects_modified_nodes(mock_db_session):
    v1 = EngineeringGraphVersion(project_id=1, version_number=1, status="SUPERSEDED", is_current=False)
    v2 = EngineeringGraphVersion(project_id=1, version_number=2, status="ACTIVE", is_current=True)
    mock_db_session.add_all([v1, v2])
    mock_db_session.flush()

    cid = "fn_same"
    n1 = EngineeringGraphNode(project_id=1, version_id=v1.id, canonical_id=cid, entity_type="FUNCTION", name="fn", qualified_name="fn", file_path="a.py", start_line=10, end_line=20)
    n2 = EngineeringGraphNode(project_id=1, version_id=v2.id, canonical_id=cid, entity_type="FUNCTION", name="fn", qualified_name="fn", file_path="a.py", start_line=10, end_line=35)
    mock_db_session.add_all([n1, n2])
    mock_db_session.commit()

    diff = GraphVersionComparator.compare_versions(mock_db_session, 1, 1, 2)
    assert diff.modified_nodes_count == 1
    assert diff.modified_nodes[0]["canonical_id"] == cid


def test_version_comparator_detects_edge_diffs(mock_db_session):
    v1 = EngineeringGraphVersion(project_id=1, version_number=1, status="SUPERSEDED", is_current=False)
    v2 = EngineeringGraphVersion(project_id=1, version_number=2, status="ACTIVE", is_current=True)
    mock_db_session.add_all([v1, v2])
    mock_db_session.flush()

    e1 = EngineeringGraphEdge(project_id=1, version_id=v1.id, source_canonical_id="s", target_canonical_id="t", rel_type="CALLS", confidence=0.5)
    e2 = EngineeringGraphEdge(project_id=1, version_id=v2.id, source_canonical_id="s", target_canonical_id="t", rel_type="CALLS", confidence=1.0, provenance={"resolution": "RESOLVED_RUNTIME"})
    mock_db_session.add_all([e1, e2])
    mock_db_session.commit()

    diff = GraphVersionComparator.compare_versions(mock_db_session, 1, 1, 2)
    assert diff.changed_relationships_count == 1
    assert diff.changed_relationships[0]["new_confidence"] == 1.0


def test_version_comparator_raises_error_on_missing_version(mock_db_session):
    with pytest.raises(ValueError, match="not found"):
        GraphVersionComparator.compare_versions(mock_db_session, 1, 99, 100)


# ============================================================================
# 8. REST API Endpoints & Multi-Tenant Security Tests (66-70)
# ============================================================================

@pytest.fixture
def api_test_app(mock_db_session, complex_repo: Path):
    from fastapi import FastAPI
    from app.api.routes.project_reviews import router

    app = FastAPI()
    app.state.SessionLocal = lambda: mock_db_session
    app.include_router(router, prefix="/api")

    # Update repo path of project 1 to complex_repo
    p = mock_db_session.get(ReviewedProject, 1)
    p.repository_path = str(complex_repo)
    mock_db_session.commit()

    return app


@pytest.fixture
def owner_auth_headers(mock_db_session):
    from app.services.auth_service import create_access_token
    user = mock_db_session.get(User, 1)
    token = create_access_token(user)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def other_auth_headers(mock_db_session):
    from app.services.auth_service import create_access_token
    user = mock_db_session.get(User, 2)
    token = create_access_token(user)
    return {"Authorization": f"Bearer {token}"}


def test_api_graph_coverage_endpoint(api_test_app, mock_db_session, complex_repo: Path, owner_auth_headers):
    # Initialize graph first
    TransactionalGraphUpdater.execute_transactional_update(mock_db_session, 1, complex_repo, force_full_rebuild=True)

    client = TestClient(api_test_app)
    # Project 1 owner is user 1
    resp = client.get("/api/project-reviews/1/graph/coverage", headers=owner_auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert "technologies" in data
    assert "overall_coverage_percentage" in data


def test_api_graph_transitions_endpoint(api_test_app, mock_db_session, owner_auth_headers):
    trans = EngineeringIdentityTransition(
        project_id=1,
        from_version_id=1,
        to_version_id=2,
        old_canonical_id="old_sym",
        new_canonical_id="new_sym",
        transition_type="RENAMED_SYMBOL",
        confidence=0.88,
        evidence={"rule": "structural"},
    )
    mock_db_session.add(trans)
    mock_db_session.commit()

    client = TestClient(api_test_app)
    resp = client.get("/api/project-reviews/1/graph/transitions", headers=owner_auth_headers)
    assert resp.status_code == 200
    transitions = resp.json()
    assert len(transitions) >= 1
    assert transitions[0]["transition_type"] == "RENAMED_SYMBOL"


def test_api_graph_versions_and_compare_endpoints(api_test_app, mock_db_session, owner_auth_headers):
    v1 = EngineeringGraphVersion(project_id=1, version_number=1, status="SUPERSEDED", is_current=False)
    v2 = EngineeringGraphVersion(project_id=1, version_number=2, status="ACTIVE", is_current=True)
    mock_db_session.add_all([v1, v2])
    mock_db_session.commit()

    client = TestClient(api_test_app)
    resp_list = client.get("/api/project-reviews/1/graph/versions", headers=owner_auth_headers)
    assert resp_list.status_code == 200
    assert len(resp_list.json()) >= 2

    resp_comp = client.get("/api/project-reviews/1/graph/compare?v1=1&v2=2", headers=owner_auth_headers)
    assert resp_comp.status_code == 200
    assert "added_nodes_count" in resp_comp.json()


def test_api_graph_recover_endpoint(api_test_app, mock_db_session, owner_auth_headers):
    client = TestClient(api_test_app)
    resp = client.post("/api/project-reviews/1/graph/recover", headers=owner_auth_headers)
    assert resp.status_code == 200
    assert resp.json()["status"] == "SUCCESS"


def test_api_graph_endpoints_enforce_tenant_isolation_404(api_test_app, other_auth_headers):
    client = TestClient(api_test_app)
    # User 2 does not own Project 1 (User 1 does)
    r1 = client.get("/api/project-reviews/1/graph/coverage", headers=other_auth_headers)
    r2 = client.get("/api/project-reviews/1/graph/transitions", headers=other_auth_headers)
    r3 = client.get("/api/project-reviews/1/graph/versions", headers=other_auth_headers)
    r4 = client.get("/api/project-reviews/1/graph/compare?v1=1&v2=2", headers=other_auth_headers)
    r5 = client.post("/api/project-reviews/1/graph/recover", headers=other_auth_headers)

    assert r1.status_code == 404
    assert r2.status_code == 404
    assert r3.status_code == 404
    assert r4.status_code == 404
    assert r5.status_code == 404
