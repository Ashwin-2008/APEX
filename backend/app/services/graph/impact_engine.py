"""Change Impact Intelligence Engine for APEX 2.0.

Computes multi-level structural, call, and behavioral impact when files or code
symbols are modified, tracing direct callers, transitive dependents, affected APIs,
database entities, relevant tests, and evidence paths.
"""
from __future__ import annotations

from collections import deque
from dataclasses import asdict, dataclass, field
from typing import Any

from app.services.graph.models import (
    EdgeType,
    GraphEdge,
    GraphNode,
    ImpactLevel,
    NodeType,
)


@dataclass
class ImpactedComponent:
    canonical_id: str
    name: str
    entity_type: str
    file_path: str
    impact_level: str  # DIRECTLY_AFFECTED, TRANSITIVELY_AFFECTED, POTENTIALLY_AFFECTED
    depth: int
    confidence: float
    evidence_path: list[str] = field(default_factory=list)
    relationship_to_source: str = ""
    details: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ChangeImpactReport:
    target_canonical_ids: list[str]
    total_impacted_count: int
    directly_affected_count: int
    transitively_affected_count: int
    potentially_affected_count: int
    impacted_components: list[ImpactedComponent]
    affected_apis: list[dict[str, Any]]
    affected_tables: list[dict[str, Any]]
    affected_tests: list[dict[str, Any]]
    affected_findings: list[dict[str, Any]]
    potential_breaking_changes: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ChangeImpactEngine:
    """Calculates bounded direct and transitive impact across the knowledge graph."""

    MAX_DEFAULT_DEPTH = 5

    @classmethod
    def analyze_impact(
        cls,
        nodes: dict[str, GraphNode],
        edges: list[GraphEdge],
        target_ids_or_files: list[str],
        max_depth: int = MAX_DEFAULT_DEPTH,
    ) -> ChangeImpactReport:
        """Computes change impact for given canonical IDs or file paths."""
        # 1. Resolve seed nodes
        seed_node_ids = set()
        for item in target_ids_or_files:
            if item in nodes:
                seed_node_ids.add(item)
            else:
                norm = item.replace("\\", "/").strip("/")
                for nid, n in nodes.items():
                    if n.file_path == norm or n.canonical_id == item:
                        seed_node_ids.add(nid)

        if not seed_node_ids:
            return ChangeImpactReport(
                target_canonical_ids=[],
                total_impacted_count=0,
                directly_affected_count=0,
                transitively_affected_count=0,
                potentially_affected_count=0,
                impacted_components=[],
                affected_apis=[],
                affected_tables=[],
                affected_tests=[],
                affected_findings=[],
                potential_breaking_changes=[],
            )

        # 2. Build reverse adjacency map (target -> list of incoming edges)
        reverse_graph: dict[str, list[GraphEdge]] = {}
        for edge in edges:
            reverse_graph.setdefault(edge.target_canonical_id, []).append(edge)

        # 3. BFS traversal to discover affected components
        impacted_map: dict[str, ImpactedComponent] = {}
        queue: deque[tuple[str, int, float, list[str], str]] = deque()

        for seed in seed_node_ids:
            queue.append((seed, 0, 1.0, [seed], "ROOT"))

        visited: set[str] = set(seed_node_ids)

        while queue:
            curr_id, depth, conf, path, rel = queue.popleft()

            if depth > 0:
                curr_node = nodes.get(curr_id)
                if curr_node:
                    if depth == 1:
                        level = ImpactLevel.DIRECTLY_AFFECTED.value
                    elif conf > 0.6:
                        level = ImpactLevel.TRANSITIVELY_AFFECTED.value
                    else:
                        level = ImpactLevel.POTENTIALLY_AFFECTED.value

                    impacted_map[curr_id] = ImpactedComponent(
                        canonical_id=curr_id,
                        name=curr_node.name,
                        entity_type=curr_node.entity_type,
                        file_path=curr_node.file_path,
                        impact_level=level,
                        depth=depth,
                        confidence=round(conf, 3),
                        evidence_path=path,
                        relationship_to_source=rel,
                        details=f"Impacted via {rel} from {path[-2] if len(path) > 1 else 'root'}",
                    )

            if depth >= max_depth:
                continue

            for incoming_edge in reverse_graph.get(curr_id, []):
                parent_id = incoming_edge.source_canonical_id
                if parent_id not in visited and parent_id in nodes:
                    visited.add(parent_id)
                    edge_conf = incoming_edge.confidence
                    next_conf = conf * edge_conf * 0.95
                    queue.append((
                        parent_id,
                        depth + 1,
                        next_conf,
                        path + [parent_id],
                        incoming_edge.rel_type,
                    ))

        # 4. Group results into domain-specific categories
        affected_apis = []
        affected_tables = []
        affected_tests = []
        affected_findings = []
        potential_breaking = []

        direct_count = 0
        transitive_count = 0
        potential_count = 0

        for comp in impacted_map.values():
            if comp.impact_level == ImpactLevel.DIRECTLY_AFFECTED.value:
                direct_count += 1
            elif comp.impact_level == ImpactLevel.TRANSITIVELY_AFFECTED.value:
                transitive_count += 1
            else:
                potential_count += 1

            if comp.entity_type == NodeType.API_ENDPOINT.value:
                affected_apis.append(comp.to_dict())
            elif comp.entity_type == NodeType.TABLE.value:
                affected_tables.append(comp.to_dict())
            elif comp.entity_type in (NodeType.TEST_FUNCTION.value, NodeType.TEST_FILE.value):
                affected_tests.append(comp.to_dict())
            elif comp.entity_type == NodeType.FINDING.value:
                affected_findings.append(comp.to_dict())

            # Detect potential breaking change if public API or high confidence caller
            if comp.impact_level == ImpactLevel.DIRECTLY_AFFECTED.value and comp.relationship_to_source in (EdgeType.CALLS.value, EdgeType.HANDLES_ROUTE.value):
                potential_breaking.append(f"Direct caller '{comp.name}' in {comp.file_path} depends on modified interface.")

        return ChangeImpactReport(
            target_canonical_ids=list(seed_node_ids),
            total_impacted_count=len(impacted_map),
            directly_affected_count=direct_count,
            transitively_affected_count=transitive_count,
            potentially_affected_count=potential_count,
            impacted_components=list(impacted_map.values()),
            affected_apis=affected_apis,
            affected_tables=affected_tables,
            affected_tests=affected_tests,
            affected_findings=affected_findings,
            potential_breaking_changes=potential_breaking,
        )

