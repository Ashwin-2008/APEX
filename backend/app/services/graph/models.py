"""Unified Engineering Knowledge Graph Data Models for APEX 2.0.

Defines canonical node types, edge relationship types, impact categories,
and serializable dataclasses representing repository architecture, code symbols,
application routes, database models, testing components, findings, and remediation operations.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class NodeType(str, Enum):
    REPOSITORY = "REPOSITORY"
    DIRECTORY = "DIRECTORY"
    FILE = "FILE"
    PACKAGE = "PACKAGE"
    MODULE = "MODULE"
    COMPONENT = "COMPONENT"
    CLASS = "CLASS"
    FUNCTION = "FUNCTION"
    METHOD = "METHOD"
    VARIABLE = "VARIABLE"
    CONSTANT = "CONSTANT"
    INTERFACE = "INTERFACE"
    TYPE = "TYPE"
    SYMBOL = "SYMBOL"
    IMPORT = "IMPORT"
    CALL = "CALL"
    API_ENDPOINT = "API_ENDPOINT"
    HTTP_METHOD = "HTTP_METHOD"
    REQUEST_SCHEMA = "REQUEST_SCHEMA"
    RESPONSE_SCHEMA = "RESPONSE_SCHEMA"
    MIDDLEWARE = "MIDDLEWARE"
    CONTROLLER = "CONTROLLER"
    SERVICE = "SERVICE"
    DATABASE_MODEL = "DATABASE_MODEL"
    TABLE = "TABLE"
    COLUMN = "COLUMN"
    FOREIGN_KEY = "FOREIGN_KEY"
    QUERY = "QUERY"
    TEST_FILE = "TEST_FILE"
    TEST_CASE = "TEST_CASE"
    TEST_FUNCTION = "TEST_FUNCTION"
    FIXTURE = "FIXTURE"
    FINDING = "FINDING"
    ROOT_CAUSE = "ROOT_CAUSE"
    EVIDENCE = "EVIDENCE"
    PATCH = "PATCH"
    REMEDIATION_TRANSACTION = "REMEDIATION_TRANSACTION"
    # Phase 3.2 Cross-Technology Nodes
    DOCKER_STAGE = "DOCKER_STAGE"
    CI_WORKFLOW = "CI_WORKFLOW"
    CI_JOB = "CI_JOB"
    ENV_VARIABLE = "ENV_VARIABLE"
    CLIENT_API_CALL = "CLIENT_API_CALL"


class EdgeType(str, Enum):
    CONTAINS = "CONTAINS"
    DEFINES = "DEFINES"
    IMPORTS = "IMPORTS"
    CALLS = "CALLS"
    REFERENCES = "REFERENCES"
    INHERITS = "INHERITS"
    IMPLEMENTS = "IMPLEMENTS"
    DEPENDS_ON = "DEPENDS_ON"
    EXPOSES_API = "EXPOSES_API"
    HANDLES_ROUTE = "HANDLES_ROUTE"
    INVOKES_SERVICE = "INVOKES_SERVICE"
    READS_TABLE = "READS_TABLE"
    WRITES_TABLE = "WRITES_TABLE"
    QUERIES_TABLE = "QUERIES_TABLE"
    VALIDATED_BY = "VALIDATED_BY"
    TESTED_BY = "TESTED_BY"
    PRODUCES_FINDING = "PRODUCES_FINDING"
    EVIDENCED_BY = "EVIDENCED_BY"
    FIXED_BY = "FIXED_BY"
    AFFECTS = "AFFECTS"
    CAUSED_BY = "CAUSED_BY"
    CONNECTED_TO = "CONNECTED_TO"
    # Phase 3.2 Cross-Technology Relationships
    CALLS_API = "CALLS_API"
    QUERIES_MODEL = "QUERIES_MODEL"
    EXECUTES_ENTRYPOINT = "EXECUTES_ENTRYPOINT"
    RUNS_WORKFLOW_TEST = "RUNS_WORKFLOW_TEST"
    CONSUMES_ENV_VAR = "CONSUMES_ENV_VAR"
    DEFINES_CLIENT_CALL = "DEFINES_CLIENT_CALL"
    DEPENDS_ON_SERVICE = "DEPENDS_ON_SERVICE"


class ImpactLevel(str, Enum):
    DIRECTLY_AFFECTED = "DIRECTLY_AFFECTED"
    TRANSITIVELY_AFFECTED = "TRANSITIVELY_AFFECTED"
    POTENTIALLY_AFFECTED = "POTENTIALLY_AFFECTED"
    UNKNOWN_IMPACT = "UNKNOWN_IMPACT"


def build_canonical_id(
    project_id: int,
    file_path: str,
    qualified_name: str,
    entity_type: str | NodeType,
) -> str:
    """Computes a stable, canonical identity string across repository scans."""
    etype = entity_type.value if isinstance(entity_type, NodeType) else str(entity_type)
    norm_path = file_path.replace("\\", "/").strip("/")
    norm_name = qualified_name.strip()
    return f"{project_id}::{norm_path}::{norm_name}::{etype}"


@dataclass
class GraphNode:
    canonical_id: str
    project_id: int
    entity_type: str
    name: str
    qualified_name: str
    file_path: str
    start_line: int = 1
    end_line: int = 1
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class GraphEdge:
    source_canonical_id: str
    target_canonical_id: str
    rel_type: str
    project_id: int
    confidence: float = 1.0
    evidence_location: str | None = None
    analyzer_source: str = "ast"
    provenance: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

