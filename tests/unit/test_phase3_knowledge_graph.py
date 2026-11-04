"""Comprehensive Unit Tests for APEX 2.0 Phase 3:
Project-Wide Engineering Knowledge Graph & Change Impact Intelligence.

Covers:
1. Canonical Graph Entities, Node Types, and Edge Relationships.
2. Full Graph Extraction Pipeline (AST, Calls, APIs, DB Models, Tests, Findings).
3. Storage Manager, Snapshot Management, Versioning, and Consistency Checks.
4. Incremental Graph Updates (file additions, modifications, deletions, no-op).
5. Change Impact Intelligence (direct, transitive, potential, evidence paths).
6. Blast Radius Scoring, Boundary Crossing, and Risk Classifications.
7. Test Selection Intelligence and Evidence-Based Ranking.
8. Architecture Intelligence, Tarjan SCC Cycles, Fan-in/out, and Layer Violations.
9. Guarded Query Engine (subgraphs, shortest path, callers, callees, pagination).
10. REST API Route Integration, Multi-Tenant Security, and Non-Disclosing 404s.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.models.entities import (
    EngineeringGraphEdge,
    EngineeringGraphNode,
    EngineeringGraphVersion,
    ReviewedProject,
    User,
)
from app.services.graph.architecture import ArchitectureIntelligenceEngine
from app.services.graph.blast_radius import BlastRadiusEngine
from app.services.graph.extractor import GraphExtractionEngine
from app.services.graph.impact_engine import ChangeImpactEngine, ImpactLevel
from app.services.graph.incremental import IncrementalGraphUpdater
from app.services.graph.models import (
    EdgeType,
    GraphEdge,
    GraphNode,
    NodeType,
    build_canonical_id,
)
from app.services.graph.query_engine import GraphQueryEngine
from app.services.graph.storage import GraphStorageManager
from app.services.graph.test_selector import TestSelectionEngine


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def sample_repo(tmp_path: Path):
    """Creates a sample multi-layer project repository structure for knowledge graph testing."""
    repo = tmp_path / "project_root"
    repo.mkdir(parents=True, exist_ok=True)

    # 1. Models Layer (Database)
    models_dir = repo / "app" / "models"
    models_dir.mkdir(parents=True, exist_ok=True)
    (models_dir / "__init__.py").write_text("", encoding="utf-8")
    (models_dir / "user_model.py").write_text(
        "class UserModel:\n"
        "    __tablename__ = 'users'\n"
        "    id = 1\n"
        "    name = 'alice'\n",
        encoding="utf-8",
    )

    # 2. Services Layer
    services_dir = repo / "app" / "services"
    services_dir.mkdir(parents=True, exist_ok=True)
    (services_dir / "__init__.py").write_text("", encoding="utf-8")
    (services_dir / "user_service.py").write_text(
        "from app.models.user_model import UserModel\n\n"
        "def get_user_by_id(uid):\n"
        "    query(UserModel)\n"
        "    return UserModel\n\n"
        "def format_user_name(u):\n"
        "    return u.name.upper()\n",
        encoding="utf-8",
    )
    (services_dir / "auth_service.py").write_text(
        "from app.services.user_service import get_user_by_id\n\n"
        "def authenticate(token):\n"
        "    user = get_user_by_id(1)\n"
        "    return user\n",
        encoding="utf-8",
    )

    # 3. API Routes Layer
    api_dir = repo / "app" / "api"
    api_dir.mkdir(parents=True, exist_ok=True)
    (api_dir / "__init__.py").write_text("", encoding="utf-8")
    (api_dir / "routes.py").write_text(
        "from app.services.auth_service import authenticate\n\n"
        "@router.get('/api/users/me')\n"
        "def get_current_user():\n"
        "    return authenticate('token')\n",
        encoding="utf-8",
    )

    # 4. Tests Layer
    tests_dir = repo / "tests"
    tests_dir.mkdir(parents=True, exist_ok=True)
    (tests_dir / "test_user_service.py").write_text(
        "from app.services.user_service import get_user_by_id\n\n"
        "def test_get_user():\n"
        "    assert get_user_by_id(1) is not None\n",
        encoding="utf-8",
    )

    return repo


@pytest.fixture
def mock_db_session(sample_repo: Path):
    """Provides isolated in-memory DB session with registered project."""
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    TestingSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = TestingSession()

    user = User(
        id=1,
        email="architect@example.com",
        username="lead_architect",
        hashed_password="pw",
        is_active=True,
    )
    session.add(user)
    session.commit()

    project = ReviewedProject(
        id=1,
        name="Knowledge Graph Test Project",
        repository_path=str(sample_repo),
        owner_id=user.id,
    )
    session.add(project)
    session.commit()

    yield session
    session.close()


@pytest.fixture
def client_app(mock_db_session, sample_repo: Path):
    """Provides FastAPI TestClient connected to isolated in-memory DB."""
    from app.main import create_app
    app = create_app()
    app.state.SessionLocal = lambda: mock_db_session
    return TestClient(app)


# ============================================================================
# 1. Canonical IDs and Data Models Tests (1-10)
# ============================================================================

def test_build_canonical_id_creates_stable_id():
    cid = build_canonical_id(1, "app/models/user.py", "UserModel", NodeType.CLASS)
    assert cid == "1::app/models/user.py::UserModel::CLASS"


def test_build_canonical_id_normalizes_slashes():
    cid1 = build_canonical_id(1, "app\\models\\user.py", "UserModel", NodeType.CLASS)
    cid2 = build_canonical_id(1, "app/models/user.py", "UserModel", NodeType.CLASS)
    assert cid1 == cid2


def test_graph_node_to_dict():
    node = GraphNode(
        canonical_id="1::a.py::func::FUNCTION",
        project_id=1,
        entity_type=NodeType.FUNCTION.value,
        name="func",
        qualified_name="a.func",
        file_path="a.py",
        start_line=10,
        end_line=20,
        metadata={"async": True},
    )
    d = node.to_dict()
    assert d["canonical_id"] == "1::a.py::func::FUNCTION"
    assert d["start_line"] == 10
    assert d["metadata"]["async"] is True


def test_graph_edge_to_dict():
    edge = GraphEdge(
        source_canonical_id="n1",
        target_canonical_id="n2",
        rel_type=EdgeType.CALLS.value,
        project_id=1,
        confidence=0.95,
        evidence_location="service.py:15",
        analyzer_source="ast",
    )
    d = edge.to_dict()
    assert d["rel_type"] == "CALLS"
    assert d["confidence"] == 0.95
    assert d["evidence_location"] == "service.py:15"


def test_node_types_enum_coverage():
    assert NodeType.REPOSITORY.value == "REPOSITORY"
    assert NodeType.API_ENDPOINT.value == "API_ENDPOINT"
    assert NodeType.TABLE.value == "TABLE"
    assert NodeType.TEST_FUNCTION.value == "TEST_FUNCTION"
    assert NodeType.FINDING.value == "FINDING"


def test_edge_types_enum_coverage():
    assert EdgeType.CALLS.value == "CALLS"
    assert EdgeType.IMPORTS.value == "IMPORTS"
    assert EdgeType.HANDLES_ROUTE.value == "HANDLES_ROUTE"
    assert EdgeType.TESTED_BY.value == "TESTED_BY"
    assert EdgeType.DEFINES.value == "DEFINES"


def test_impact_level_enum():
    assert ImpactLevel.DIRECTLY_AFFECTED.value == "DIRECTLY_AFFECTED"
    assert ImpactLevel.TRANSITIVELY_AFFECTED.value == "TRANSITIVELY_AFFECTED"
    assert ImpactLevel.POTENTIALLY_AFFECTED.value == "POTENTIALLY_AFFECTED"


def test_canonical_id_distinct_for_different_entity_types():
    cid_func = build_canonical_id(1, "service.py", "validate", NodeType.FUNCTION)
    cid_call = build_canonical_id(1, "service.py", "validate", NodeType.CALL)
    assert cid_func != cid_call


def test_canonical_id_distinct_for_different_projects():
    cid_p1 = build_canonical_id(1, "service.py", "validate", NodeType.FUNCTION)
    cid_p2 = build_canonical_id(2, "service.py", "validate", NodeType.FUNCTION)
    assert cid_p1 != cid_p2


def test_canonical_id_distinct_for_different_files():
    cid1 = build_canonical_id(1, "service_a.py", "validate", NodeType.FUNCTION)
    cid2 = build_canonical_id(1, "service_b.py", "validate", NodeType.FUNCTION)
    assert cid1 != cid2


# ============================================================================
# 2. Graph Extraction Pipeline Tests (11-25)
# ============================================================================

def test_extract_repository_structure(sample_repo: Path):
    extractor = GraphExtractionEngine(1, sample_repo)
    extractor.extract_repository_structure()
    assert len(extractor.nodes) > 0
    assert any(n.entity_type == NodeType.REPOSITORY.value for n in extractor.nodes.values())
    assert any(n.entity_type == NodeType.DIRECTORY.value for n in extractor.nodes.values())
    assert any(n.entity_type == NodeType.FILE.value for n in extractor.nodes.values())


def test_extract_code_symbols_classes_and_functions(sample_repo: Path):
    extractor = GraphExtractionEngine(1, sample_repo)
    extractor.extract_code_intelligence()
    assert any(n.entity_type == NodeType.CLASS.value and n.name == "UserModel" for n in extractor.nodes.values())
    assert any(n.entity_type == NodeType.FUNCTION.value and n.name == "get_user_by_id" for n in extractor.nodes.values())
    assert any(n.entity_type == NodeType.FUNCTION.value and n.name == "authenticate" for n in extractor.nodes.values())


def test_extract_cross_file_calls(sample_repo: Path):
    extractor = GraphExtractionEngine(1, sample_repo)
    extractor.extract_code_intelligence()
    # authenticate() calls get_user_by_id()
    call_edges = [e for e in extractor.edges if e.rel_type == EdgeType.CALLS.value]
    assert len(call_edges) > 0
    auth_calls = [
        e for e in call_edges
        if "auth_service" in e.source_canonical_id and "get_user_by_id" in e.target_canonical_id
    ]
    assert len(auth_calls) >= 1
    assert auth_calls[0].confidence >= 0.9


def test_extract_imports_relationships(sample_repo: Path):
    extractor = GraphExtractionEngine(1, sample_repo)
    extractor.extract_code_intelligence()
    import_edges = [e for e in extractor.edges if e.rel_type == EdgeType.IMPORTS.value]
    assert len(import_edges) > 0


def test_extract_api_route_endpoints(sample_repo: Path):
    extractor = GraphExtractionEngine(1, sample_repo)
    extractor.extract_code_intelligence()
    extractor.extract_api_graph()
    api_nodes = [n for n in extractor.nodes.values() if n.entity_type == NodeType.API_ENDPOINT.value]
    assert len(api_nodes) >= 1
    assert any("GET /api/users/me" in n.name for n in api_nodes)

    route_edges = [e for e in extractor.edges if e.rel_type == EdgeType.HANDLES_ROUTE.value]
    assert len(route_edges) >= 1


def test_extract_database_tables_and_models(sample_repo: Path):
    extractor = GraphExtractionEngine(1, sample_repo)
    extractor.extract_code_intelligence()
    extractor.extract_database_graph()
    table_nodes = [n for n in extractor.nodes.values() if n.entity_type == NodeType.TABLE.value]
    assert len(table_nodes) >= 1
    assert any(n.name == "users" for n in table_nodes)


def test_extract_database_query_relationship(sample_repo: Path):
    extractor = GraphExtractionEngine(1, sample_repo)
    extractor.extract_code_intelligence()
    extractor.extract_database_graph()
    # get_user_by_id queries UserModel / users table
    query_edges = [e for e in extractor.edges if e.rel_type in (EdgeType.READS_TABLE.value, EdgeType.QUERIES_TABLE.value)]
    assert len(query_edges) >= 1


def test_extract_test_functions_and_tested_by_edge(sample_repo: Path):
    extractor = GraphExtractionEngine(1, sample_repo)
    extractor.extract_code_intelligence()
    extractor.extract_testing_graph()

    test_nodes = [n for n in extractor.nodes.values() if n.entity_type == NodeType.TEST_FUNCTION.value]
    assert len(test_nodes) >= 1
    assert any(n.name == "test_get_user" for n in test_nodes)

    tested_by_edges = [e for e in extractor.edges if e.rel_type == EdgeType.TESTED_BY.value]
    assert len(tested_by_edges) >= 1


def test_extract_full_graph_end_to_end(sample_repo: Path):
    extractor = GraphExtractionEngine(1, sample_repo)
    nodes, edges = extractor.extract_full_graph()
    assert len(nodes) >= 10
    assert len(edges) >= 10


def test_extract_findings_linked_to_code(sample_repo: Path):
    extractor = GraphExtractionEngine(1, sample_repo)
    nodes, edges = extractor.extract_full_graph(
        findings=[
            {
                "id": "finding_101",
                "rule_id": "SEC001",
                "file_path": "app/services/auth_service.py",
                "start_line": 3,
                "severity": "high",
                "category": "security",
                "message": "Insecure token authentication",
            }
        ]
    )
    finding_nodes = [n for n in nodes.values() if n.entity_type == NodeType.FINDING.value]
    assert len(finding_nodes) == 1
    assert finding_nodes[0].name == "SEC001"

    finding_edges = [e for e in edges if e.rel_type == EdgeType.PRODUCES_FINDING.value]
    assert len(finding_edges) == 1


def test_extract_remediation_transaction_linked_to_files(sample_repo: Path):
    extractor = GraphExtractionEngine(1, sample_repo)
    nodes, edges = extractor.extract_full_graph(
        transactions=[
            {
                "transaction_id": "txn_abc_123",
                "state": "COMMITTED",
                "manifest": {"files": [{"rel_path": "app/services/auth_service.py"}]},
            }
        ]
    )
    txn_nodes = [n for n in nodes.values() if n.entity_type == NodeType.REMEDIATION_TRANSACTION.value]
    assert len(txn_nodes) == 1
    affects_edges = [e for e in edges if e.rel_type == EdgeType.AFFECTS.value]
    assert len(affects_edges) == 1


def test_extract_unresolved_call_recorded_with_provenance(sample_repo: Path):
    # Add a file with a dynamic call
    (sample_repo / "dynamic_call.py").write_text("def test():\n    getattr(obj, 'action')()\n", encoding="utf-8")
    extractor = GraphExtractionEngine(1, sample_repo)
    nodes, edges = extractor.extract_full_graph()
    call_edges = [e for e in edges if e.rel_type == EdgeType.CALLS.value and e.provenance.get("unresolved")]
    assert len(call_edges) >= 1
    assert call_edges[0].confidence == 0.5


def test_extractor_handles_parse_error_gracefully(sample_repo: Path):
    (sample_repo / "broken.py").write_text("def syntax_err(: pass", encoding="utf-8")
    extractor = GraphExtractionEngine(1, sample_repo)
    nodes, edges = extractor.extract_full_graph()
    assert len(nodes) > 0  # Still extracts other valid files


def test_duplicate_edges_not_added(sample_repo: Path):
    extractor = GraphExtractionEngine(1, sample_repo)
    extractor.add_edge("n1", "n2", EdgeType.CALLS)
    extractor.add_edge("n1", "n2", EdgeType.CALLS)
    assert len(extractor.edges) == 1


def test_mccabe_complexity_in_method_metadata(sample_repo: Path):
    extractor = GraphExtractionEngine(1, sample_repo)
    nodes, _ = extractor.extract_full_graph()
    user_func = next(n for n in nodes.values() if n.name == "format_user_name")
    assert "complexity" in user_func.metadata
    assert user_func.metadata["complexity"] >= 1


# ============================================================================
# 3. Storage, Snapshot & Consistency Tests (26-35)
# ============================================================================

def test_persist_graph_creates_db_version_and_records(sample_repo: Path, mock_db_session):
    extractor = GraphExtractionEngine(1, sample_repo)
    nodes, edges = extractor.extract_full_graph()

    ver = GraphStorageManager.persist_graph(mock_db_session, 1, nodes, edges, commit_sha="sha_1")
    assert ver.version_number == 1
    assert ver.is_current is True
    assert ver.node_count == len(nodes)
    assert ver.edge_count == len(edges)

    db_nodes_count = mock_db_session.query(EngineeringGraphNode).filter_by(version_id=ver.id).count()
    assert db_nodes_count == len(nodes)


def test_persist_second_graph_deactivates_first(sample_repo: Path, mock_db_session):
    extractor = GraphExtractionEngine(1, sample_repo)
    nodes, edges = extractor.extract_full_graph()

    ver1 = GraphStorageManager.persist_graph(mock_db_session, 1, nodes, edges)
    ver2 = GraphStorageManager.persist_graph(mock_db_session, 1, nodes, edges)

    mock_db_session.refresh(ver1)
    assert ver1.is_current is False
    assert ver1.status == "SUPERSEDED"
    assert ver2.is_current is True
    assert ver2.version_number == 2


def test_load_active_graph_returns_nodes_and_edges(sample_repo: Path, mock_db_session):
    extractor = GraphExtractionEngine(1, sample_repo)
    nodes, edges = extractor.extract_full_graph()
    GraphStorageManager.persist_graph(mock_db_session, 1, nodes, edges)

    loaded_nodes, loaded_edges, ver = GraphStorageManager.load_active_graph(mock_db_session, 1)
    assert ver is not None
    assert len(loaded_nodes) == len(nodes)
    assert len(loaded_edges) == len(edges)


def test_load_active_graph_empty_when_no_version_exists(mock_db_session):
    nodes, edges, ver = GraphStorageManager.load_active_graph(mock_db_session, 999)
    assert nodes == {}
    assert edges == []
    assert ver is None


def test_verify_consistency_detects_clean_graph(sample_repo: Path):
    extractor = GraphExtractionEngine(1, sample_repo)
    nodes, edges = extractor.extract_full_graph()
    report = GraphStorageManager.verify_consistency(nodes, edges)
    assert report["is_consistent"] is True
    assert report["duplicate_edges"] == 0


def test_verify_consistency_detects_duplicate_edges():
    nodes = {
        "n1": GraphNode("n1", 1, "FILE", "a", "a", "a.py"),
        "n2": GraphNode("n2", 1, "FILE", "b", "b", "b.py"),
    }
    edges = [
        GraphEdge("n1", "n2", "CALLS", 1),
        GraphEdge("n1", "n2", "CALLS", 1),
    ]
    report = GraphStorageManager.verify_consistency(nodes, edges)
    assert report["duplicate_edges"] == 1
    assert report["is_consistent"] is False


def test_verify_consistency_detects_dangling_sources():
    nodes = {"n2": GraphNode("n2", 1, "FILE", "b", "b", "b.py")}
    edges = [GraphEdge("missing_source", "n2", "CALLS", 1)]
    report = GraphStorageManager.verify_consistency(nodes, edges)
    assert report["dangling_sources_count"] == 1
    assert report["is_consistent"] is False


def test_tenant_isolation_in_storage(sample_repo: Path, mock_db_session):
    # Store graph for project 1
    extractor = GraphExtractionEngine(1, sample_repo)
    nodes, edges = extractor.extract_full_graph()
    GraphStorageManager.persist_graph(mock_db_session, 1, nodes, edges)

    # Project 2 must not see project 1's graph
    nodes_p2, edges_p2, ver_p2 = GraphStorageManager.load_active_graph(mock_db_session, 2)
    assert ver_p2 is None
    assert len(nodes_p2) == 0


def test_graph_version_tracks_custom_metadata(mock_db_session):
    nodes = {"n1": GraphNode("n1", 1, "FILE", "a", "a", "a.py")}
    ver = GraphStorageManager.persist_graph(mock_db_session, 1, nodes, [], metadata={"trigger": "user_action"})
    assert ver.metadata_json["trigger"] == "user_action"


def test_get_current_version_helper(sample_repo: Path, mock_db_session):
    extractor = GraphExtractionEngine(1, sample_repo)
    nodes, edges = extractor.extract_full_graph()
    GraphStorageManager.persist_graph(mock_db_session, 1, nodes, edges)
    ver = GraphStorageManager.get_current_version(mock_db_session, 1)
    assert ver is not None
    assert ver.is_current is True


# ============================================================================
# 4. Incremental Graph Updates Tests (36-42)
# ============================================================================

def test_incremental_update_triggers_full_rebuild_if_no_prior(sample_repo: Path, mock_db_session):
    nodes, edges, ver = IncrementalGraphUpdater.update_graph(mock_db_session, 1, sample_repo)
    assert ver.version_number == 1
    assert len(nodes) > 0


def test_incremental_update_prunes_and_reindexes_changed_file(sample_repo: Path, mock_db_session):
    # Initial build
    IncrementalGraphUpdater.update_graph(mock_db_session, 1, sample_repo, force_full_rebuild=True)

    # Modify user_service.py with a new function
    svc_file = sample_repo / "app" / "services" / "user_service.py"
    svc_file.write_text(
        "def newly_added_service_function():\n    return 'new'\n",
        encoding="utf-8",
    )

    nodes, edges, ver = IncrementalGraphUpdater.update_graph(
        mock_db_session,
        1,
        sample_repo,
        changed_files=["app/services/user_service.py"],
    )
    assert ver.version_number == 2
    assert any(n.name == "newly_added_service_function" for n in nodes.values())


def test_incremental_update_removes_deleted_file_nodes(sample_repo: Path, mock_db_session):
    IncrementalGraphUpdater.update_graph(mock_db_session, 1, sample_repo, force_full_rebuild=True)

    # Delete test file
    (sample_repo / "tests" / "test_user_service.py").unlink()

    nodes, edges, ver = IncrementalGraphUpdater.update_graph(
        mock_db_session,
        1,
        sample_repo,
        deleted_files=["tests/test_user_service.py"],
    )
    assert ver.version_number == 2
    assert not any("tests/test_user_service.py" in n.file_path for n in nodes.values())


def test_incremental_update_no_op_when_no_changes(sample_repo: Path, mock_db_session):
    nodes1, _, ver1 = IncrementalGraphUpdater.update_graph(mock_db_session, 1, sample_repo, force_full_rebuild=True)
    nodes2, _, ver2 = IncrementalGraphUpdater.update_graph(mock_db_session, 1, sample_repo, changed_files=[], deleted_files=[])
    assert ver1.version_number == ver2.version_number
    assert len(nodes1) == len(nodes2)


def test_incremental_force_full_rebuild(sample_repo: Path, mock_db_session):
    IncrementalGraphUpdater.update_graph(mock_db_session, 1, sample_repo, force_full_rebuild=True)
    _, _, ver2 = IncrementalGraphUpdater.update_graph(mock_db_session, 1, sample_repo, force_full_rebuild=True)
    assert ver2.version_number == 2
    assert ver2.metadata_json.get("build_type") == "FULL_REBUILD"


def test_incremental_metadata_records_changed_and_deleted_lists(sample_repo: Path, mock_db_session):
    IncrementalGraphUpdater.update_graph(mock_db_session, 1, sample_repo, force_full_rebuild=True)
    _, _, ver = IncrementalGraphUpdater.update_graph(
        mock_db_session,
        1,
        sample_repo,
        changed_files=["app/models/user_model.py"],
        deleted_files=["dummy.py"],
    )
    assert "app/models/user_model.py" in ver.metadata_json["changed_files"]
    assert "dummy.py" in ver.metadata_json["deleted_files"]


def test_incremental_update_preserves_unrelated_nodes(sample_repo: Path, mock_db_session):
    IncrementalGraphUpdater.update_graph(mock_db_session, 1, sample_repo, force_full_rebuild=True)

    # Only modify routes.py
    (sample_repo / "app" / "api" / "routes.py").write_text("# comment", encoding="utf-8")
    nodes, _, _ = IncrementalGraphUpdater.update_graph(
        mock_db_session,
        1,
        sample_repo,
        changed_files=["app/api/routes.py"],
    )
    # UserModel should remain untouched in nodes
    assert any(n.name == "UserModel" for n in nodes.values())


# ============================================================================
# 5. Change Impact Intelligence Tests (43-48)
# ============================================================================

def test_change_impact_direct_callers_identified(sample_repo: Path):
    extractor = GraphExtractionEngine(1, sample_repo)
    nodes, edges = extractor.extract_full_graph()

    # Changing user_service.py -> authenticate() in auth_service calls get_user_by_id()
    report = ChangeImpactEngine.analyze_impact(nodes, edges, ["app/services/user_service.py"])
    assert report.total_impacted_count > 0
    assert report.directly_affected_count >= 1
    # auth_service or authenticate should be in impacted components
    names = [c.name for c in report.impacted_components]
    assert any("authenticate" in name or "auth_service" in name for name in names)


def test_change_impact_transitive_propagation_to_apis(sample_repo: Path):
    extractor = GraphExtractionEngine(1, sample_repo)
    nodes, edges = extractor.extract_full_graph()

    # Changing user_model.py should transitively impact user_service -> auth_service -> GET /api/users/me
    report = ChangeImpactEngine.analyze_impact(nodes, edges, ["app/models/user_model.py"], max_depth=5)
    assert report.transitively_affected_count >= 1
    assert len(report.affected_apis) >= 1
    assert any("GET /api/users/me" in api["name"] for api in report.affected_apis)


def test_change_impact_evidence_path_populated(sample_repo: Path):
    extractor = GraphExtractionEngine(1, sample_repo)
    nodes, edges = extractor.extract_full_graph()

    report = ChangeImpactEngine.analyze_impact(nodes, edges, ["app/services/user_service.py"])
    for comp in report.impacted_components:
        assert len(comp.evidence_path) >= 1


def test_change_impact_unknown_target_returns_empty():
    nodes = {}
    edges = []
    report = ChangeImpactEngine.analyze_impact(nodes, edges, ["non_existent_file.py"])
    assert report.total_impacted_count == 0


def test_change_impact_max_depth_respected(sample_repo: Path):
    extractor = GraphExtractionEngine(1, sample_repo)
    nodes, edges = extractor.extract_full_graph()

    # With max_depth=1, only direct dependents are returned
    report = ChangeImpactEngine.analyze_impact(nodes, edges, ["app/models/user_model.py"], max_depth=1)
    for comp in report.impacted_components:
        assert comp.depth <= 1


def test_change_impact_confidence_decays_with_depth(sample_repo: Path):
    extractor = GraphExtractionEngine(1, sample_repo)
    nodes, edges = extractor.extract_full_graph()

    report = ChangeImpactEngine.analyze_impact(nodes, edges, ["app/models/user_model.py"], max_depth=5)
    depth_1_conf = [c.confidence for c in report.impacted_components if c.depth == 1]
    depth_2_conf = [c.confidence for c in report.impacted_components if c.depth >= 2]

    if depth_1_conf and depth_2_conf:
        assert max(depth_2_conf) <= max(depth_1_conf)


# ============================================================================
# 6. Blast Radius Analysis Tests (49-53)
# ============================================================================

def test_blast_radius_calculation_scores_and_risk(sample_repo: Path):
    extractor = GraphExtractionEngine(1, sample_repo)
    nodes, edges = extractor.extract_full_graph()

    report = BlastRadiusEngine.calculate_blast_radius(nodes, edges, ["app/models/user_model.py"])
    assert 0.0 <= report.blast_radius_score <= 100.0
    assert report.risk_level in ("CRITICAL", "HIGH", "MEDIUM", "LOW")
    assert isinstance(report.risk_factors, list)


def test_blast_radius_detects_boundaries_crossed(sample_repo: Path):
    extractor = GraphExtractionEngine(1, sample_repo)
    nodes, edges = extractor.extract_full_graph()

    # Changing user_model touches DATA_ACCESS_LAYER, SERVICE_LAYER, API_LAYER
    report = BlastRadiusEngine.calculate_blast_radius(nodes, edges, ["app/models/user_model.py"])
    assert len(report.boundaries_crossed) >= 2


def test_blast_radius_empty_target_yields_low_score():
    report = BlastRadiusEngine.calculate_blast_radius({}, [], [])
    assert report.blast_radius_score == 0.0
    assert report.risk_level == "LOW"


def test_blast_radius_high_risk_on_critical_dependency(sample_repo: Path):
    extractor = GraphExtractionEngine(1, sample_repo)
    nodes, edges = extractor.extract_full_graph()

    report = BlastRadiusEngine.calculate_blast_radius(nodes, edges, ["app/services/auth_service.py"])
    assert report.affected_apis_count >= 1
    assert any("public API endpoint" in rf for rf in report.risk_factors)


def test_blast_radius_serializes_to_dict(sample_repo: Path):
    extractor = GraphExtractionEngine(1, sample_repo)
    nodes, edges = extractor.extract_full_graph()

    report = BlastRadiusEngine.calculate_blast_radius(nodes, edges, ["app/services/user_service.py"])
    d = report.to_dict()
    assert "blast_radius_score" in d
    assert "risk_level" in d
    assert "boundaries_crossed" in d


# ============================================================================
# 7. Test Selection Intelligence Tests (54-57)
# ============================================================================

def test_select_tests_finds_direct_test(sample_repo: Path):
    extractor = GraphExtractionEngine(1, sample_repo)
    nodes, edges = extractor.extract_full_graph()

    tests = TestSelectionEngine.select_tests_for_changes(nodes, edges, ["app/services/user_service.py"])
    assert len(tests) >= 1
    assert any("test_get_user" in t.test_name for t in tests)
    assert any(t.tier == "DIRECT_TEST" for t in tests)


def test_select_tests_ranks_direct_higher_than_transitive():
    nodes = {
        "s1": GraphNode("s1", 1, "FUNCTION", "func_a", "a.func_a", "a.py"),
        "t1": GraphNode("t1", 1, "TEST_FUNCTION", "test_direct", "test.test_direct", "test.py"),
        "t2": GraphNode("t2", 1, "TEST_FUNCTION", "test_transitive", "test.test_transitive", "test.py"),
    }
    edges = [
        GraphEdge("s1", "t1", EdgeType.TESTED_BY.value, 1, confidence=1.0),
        GraphEdge("s1", "t2", EdgeType.TESTED_BY.value, 1, confidence=0.7),
    ]
    ranked = TestSelectionEngine.select_tests_for_changes(nodes, edges, ["s1"])
    assert ranked[0].test_name == "test_direct"
    assert ranked[0].confidence >= ranked[1].confidence


def test_select_tests_empty_when_no_tests():
    nodes = {"s1": GraphNode("s1", 1, "FUNCTION", "func_a", "a.func_a", "a.py")}
    ranked = TestSelectionEngine.select_tests_for_changes(nodes, [], ["s1"])
    assert ranked == []


def test_recommended_test_to_dict():
    from app.services.graph.test_selector import RecommendedTest
    rt = RecommendedTest("t1", "test_func", "test.py", "DIRECT_TEST", 0.95, "Direct call", "func")
    d = rt.to_dict()
    assert d["tier"] == "DIRECT_TEST"
    assert d["confidence"] == 0.95


# ============================================================================
# 8. Architecture Intelligence & Tarjan Cycles Tests (58-61)
# ============================================================================

def test_architecture_detects_clean_acyclic_graph(sample_repo: Path):
    extractor = GraphExtractionEngine(1, sample_repo)
    nodes, edges = extractor.extract_full_graph()

    metrics = ArchitectureIntelligenceEngine.analyze_architecture(nodes, edges)
    assert len(metrics.circular_dependencies) == 0


def test_architecture_detects_tarjan_circular_dependencies():
    nodes = {
        "m_a": GraphNode("m_a", 1, "MODULE", "mod_a", "mod_a", "mod_a.py"),
        "m_b": GraphNode("m_b", 1, "MODULE", "mod_b", "mod_b", "mod_b.py"),
        "m_c": GraphNode("m_c", 1, "MODULE", "mod_c", "mod_c", "mod_c.py"),
    }
    edges = [
        GraphEdge("m_a", "m_b", EdgeType.IMPORTS.value, 1),
        GraphEdge("m_b", "m_c", EdgeType.IMPORTS.value, 1),
        GraphEdge("m_c", "m_a", EdgeType.IMPORTS.value, 1),
    ]
    metrics = ArchitectureIntelligenceEngine.analyze_architecture(nodes, edges)
    assert len(metrics.circular_dependencies) >= 1
    cycle = metrics.circular_dependencies[0]
    assert "mod_a" in cycle and "mod_b" in cycle and "mod_c" in cycle


def test_architecture_fan_in_and_fan_out():
    nodes = {
        "core": GraphNode("core", 1, "MODULE", "core", "core", "core.py"),
        "mod1": GraphNode("mod1", 1, "MODULE", "mod1", "mod1", "mod1.py"),
        "mod2": GraphNode("mod2", 1, "MODULE", "mod2", "mod2", "mod2.py"),
    }
    edges = [
        GraphEdge("mod1", "core", EdgeType.IMPORTS.value, 1),
        GraphEdge("mod2", "core", EdgeType.IMPORTS.value, 1),
    ]
    metrics = ArchitectureIntelligenceEngine.analyze_architecture(nodes, edges)
    core_fan_in = next((m for m in metrics.high_fan_in_modules if m["module"] == "core"), None)
    assert core_fan_in is not None
    assert core_fan_in["fan_in"] == 2


def test_architecture_detects_layer_violations():
    nodes = {
        "m_data": GraphNode("m_data", 1, "MODULE", "models", "app.models.user", "app/models/user.py"),
        "m_api": GraphNode("m_api", 1, "MODULE", "routes", "app.api.routes", "app/api/routes.py"),
    }
    # Illegal dependency: models imports routes!
    edges = [GraphEdge("m_data", "m_api", EdgeType.IMPORTS.value, 1, evidence_location="user.py:1")]
    metrics = ArchitectureIntelligenceEngine.analyze_architecture(nodes, edges)
    assert len(metrics.layer_violations) == 1
    assert metrics.layer_violations[0]["rule"] == "DATA_LAYER_DEPENDS_ON_API_LAYER"


# ============================================================================
# 9. Guarded Query Engine Tests (62-66)
# ============================================================================

def test_get_subgraph_bounded_by_radius(sample_repo: Path):
    extractor = GraphExtractionEngine(1, sample_repo)
    nodes, edges = extractor.extract_full_graph()

    first_node_id = next(iter(nodes.keys()))
    subgraph = GraphQueryEngine.get_subgraph(nodes, edges, center_id=first_node_id, radius=2, limit=10)
    assert len(subgraph["nodes"]) <= 10
    assert subgraph["center_id"] == first_node_id


def test_find_shortest_path_success():
    nodes = {
        "n1": GraphNode("n1", 1, "MODULE", "a", "a", "a.py"),
        "n2": GraphNode("n2", 1, "MODULE", "b", "b", "b.py"),
        "n3": GraphNode("n3", 1, "MODULE", "c", "c", "c.py"),
    }
    edges = [
        GraphEdge("n1", "n2", "CALLS", 1),
        GraphEdge("n2", "n3", "CALLS", 1),
    ]
    res = GraphQueryEngine.find_shortest_path(nodes, edges, "n1", "n3")
    assert res["found"] is True
    assert res["length"] == 2
    assert len(res["path"]) == 3


def test_find_shortest_path_not_found():
    nodes = {
        "n1": GraphNode("n1", 1, "MODULE", "a", "a", "a.py"),
        "n2": GraphNode("n2", 1, "MODULE", "b", "b", "b.py"),
    }
    edges = []
    res = GraphQueryEngine.find_shortest_path(nodes, edges, "n1", "n2")
    assert res["found"] is False
    assert res["length"] == -1


def test_get_callers_and_callees():
    nodes = {
        "caller": GraphNode("caller", 1, "FUNCTION", "caller_fn", "a.caller_fn", "a.py"),
        "callee": GraphNode("callee", 1, "FUNCTION", "callee_fn", "b.callee_fn", "b.py"),
    }
    edges = [GraphEdge("caller", "callee", EdgeType.CALLS.value, 1, evidence_location="a.py:5")]

    callers = GraphQueryEngine.get_callers(nodes, edges, "callee")
    assert len(callers) == 1
    assert callers[0]["caller"]["name"] == "caller_fn"

    callees = GraphQueryEngine.get_callees(nodes, edges, "caller")
    assert len(callees) == 1
    assert callees[0]["callee"]["name"] == "callee_fn"


def test_filter_nodes_pagination_and_search():
    nodes = {
        f"n{i}": GraphNode(f"n{i}", 1, "FUNCTION" if i % 2 == 0 else "CLASS", f"item_{i}", f"q_{i}", "file.py")
        for i in range(25)
    }
    # Page 1
    res1 = GraphQueryEngine.filter_nodes(nodes, entity_type="FUNCTION", skip=0, limit=5)
    assert len(res1["nodes"]) == 5
    assert res1["total"] == 13  # 13 even numbers in 0..24

    # Search
    res_search = GraphQueryEngine.filter_nodes(nodes, search="item_10")
    assert len(res_search["nodes"]) == 1


# ============================================================================
# 10. REST API Route Integration & Security Tests (67-75)
# ============================================================================

def test_api_extract_graph(client_app):
    resp = client_app.post("/api/project-reviews/1/graph/extract", json={"force_full_rebuild": True})
    assert resp.status_code == 200
    data = resp.json()
    assert data["node_count"] > 0
    assert data["edge_count"] > 0
    assert data["version_number"] >= 1


def test_api_get_graph_overview(client_app):
    resp = client_app.get("/api/project-reviews/1/graph/overview")
    assert resp.status_code == 200
    data = resp.json()
    assert "node_count" in data
    assert "entity_type_counts" in data
    assert "consistency" in data


def test_api_query_nodes(client_app):
    # Ensure graph is extracted
    client_app.post("/api/project-reviews/1/graph/extract", json={"force_full_rebuild": True})

    resp = client_app.get("/api/project-reviews/1/graph/nodes?limit=10")
    assert resp.status_code == 200
    data = resp.json()
    assert "nodes" in data
    assert len(data["nodes"]) <= 10


def test_api_query_edges(client_app):
    client_app.post("/api/project-reviews/1/graph/extract", json={"force_full_rebuild": True})

    resp = client_app.get("/api/project-reviews/1/graph/edges?limit=10")
    assert resp.status_code == 200
    data = resp.json()
    assert "edges" in data


def test_api_analyze_impact(client_app):
    client_app.post("/api/project-reviews/1/graph/extract", json={"force_full_rebuild": True})

    resp = client_app.post(
        "/api/project-reviews/1/graph/impact",
        json={"targets": ["app/services/user_service.py"], "max_depth": 5},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "total_impacted_count" in data
    assert "impacted_components" in data


def test_api_compute_blast_radius(client_app):
    client_app.post("/api/project-reviews/1/graph/extract", json={"force_full_rebuild": True})

    resp = client_app.post(
        "/api/project-reviews/1/graph/blast-radius",
        json={"targets": ["app/services/auth_service.py"], "max_depth": 5},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "blast_radius_score" in data
    assert "risk_level" in data


def test_api_recommended_tests(client_app):
    client_app.post("/api/project-reviews/1/graph/extract", json={"force_full_rebuild": True})

    resp = client_app.post(
        "/api/project-reviews/1/graph/recommended-tests",
        json={"targets": ["app/services/user_service.py"], "max_depth": 4},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "recommended_tests" in data


def test_api_get_architecture_metrics(client_app):
    client_app.post("/api/project-reviews/1/graph/extract", json={"force_full_rebuild": True})

    resp = client_app.get("/api/project-reviews/1/graph/architecture")
    assert resp.status_code == 200
    data = resp.json()
    assert "circular_dependencies" in data
    assert "high_fan_in_modules" in data


def test_api_tenant_isolation_non_disclosing_404(client_app):
    # Non-existent or unauthorized project 999
    resp = client_app.get("/api/project-reviews/999/graph/overview")
    assert resp.status_code == 404

