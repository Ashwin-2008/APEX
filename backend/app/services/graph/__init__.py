"""Unified Project-Wide Engineering Knowledge Graph Package for APEX 2.0 (Phase 3.1)."""

from app.services.graph.architecture import ArchitectureIntelligenceEngine, ArchitectureMetricsReport
from app.services.graph.blast_radius import (
    BlastRadiusBenchmark,
    BlastRadiusEngine,
    BlastRadiusReport,
)
from app.services.graph.call_resolver import AdvancedCallResolver, CallResolutionType
from app.services.graph.coverage_reporter import (
    CoverageDimensionStatus,
    GraphCoverageReport,
    GraphCoverageReporter,
    TechnologyCoverageSummary,
)
from app.services.graph.extractor import GraphExtractionEngine
from app.services.graph.identity_continuity import (
    IdentityContinuityEngine,
    IdentityTransitionRecord,
    IdentityTransitionType,
    compute_ast_structural_fingerprint,
    compute_symbol_signature,
)
from app.services.graph.impact_engine import (
    ChangeImpactEngine,
    ChangeImpactReport,
    ImpactedComponent,
)
from app.services.graph.incremental import IncrementalGraphUpdater
from app.services.graph.models import (
    EdgeType,
    GraphEdge,
    GraphNode,
    ImpactLevel,
    NodeType,
    build_canonical_id,
)
from app.services.graph.query_engine import GraphQueryEngine
from app.services.graph.storage import GraphStorageManager
from app.services.graph.test_selector import (
    RecommendedTest,
    TestRecommendationTier,
    TestSelectionBenchmark,
    TestSelectionEngine,
)
from app.services.graph.transactional_updater import TransactionalGraphUpdater
from app.services.graph.version_comparator import GraphVersionComparator, VersionDiffReport

__all__ = [
    "AdvancedCallResolver",
    "ArchitectureIntelligenceEngine",
    "ArchitectureMetricsReport",
    "BlastRadiusBenchmark",
    "BlastRadiusEngine",
    "BlastRadiusReport",
    "CallResolutionType",
    "ChangeImpactEngine",
    "ChangeImpactReport",
    "CoverageDimensionStatus",
    "EdgeType",
    "GraphCoverageReport",
    "GraphCoverageReporter",
    "GraphEdge",
    "GraphExtractionEngine",
    "GraphNode",
    "GraphQueryEngine",
    "GraphStorageManager",
    "GraphVersionComparator",
    "IdentityContinuityEngine",
    "IdentityTransitionRecord",
    "IdentityTransitionType",
    "ImpactLevel",
    "ImpactedComponent",
    "IncrementalGraphUpdater",
    "NodeType",
    "RecommendedTest",
    "TechnologyCoverageSummary",
    "TestRecommendationTier",
    "TestSelectionBenchmark",
    "TestSelectionEngine",
    "TransactionalGraphUpdater",
    "VersionDiffReport",
    "build_canonical_id",
    "compute_ast_structural_fingerprint",
    "compute_symbol_signature",
]
