"""Architecture & Dependency Graph Intelligence Engine for APEX 2.0.

Provides rigorous graph analysis:
- Tarjan strongly connected components for cycle detection.
- Fan-in and Fan-out centrality metrics.
- Layer boundary coupling and architectural violation detection.
- Orphaned and unresolved dependency identification.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, dataclass, field
from typing import Any

from app.services.analyzers.repository_graph import TarjanCycleDetector
from app.services.graph.models import EdgeType, GraphEdge, GraphNode, NodeType


@dataclass
class ArchitectureMetricsReport:
    total_modules: int
    circular_dependencies: list[list[str]]
    high_fan_in_modules: list[dict[str, Any]]
    high_fan_out_modules: list[dict[str, Any]]
    orphaned_modules: list[str]
    unresolved_imports: list[dict[str, Any]]
    layer_violations: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ArchitectureIntelligenceEngine:
    """Analyzes high-level architectural health and module dependencies."""

    @classmethod
    def analyze_architecture(
        cls,
        nodes: dict[str, GraphNode],
        edges: list[GraphEdge],
    ) -> ArchitectureMetricsReport:
        # 1. Build module-level dependency graph
        mod_nodes = {nid: n for nid, n in nodes.items() if n.entity_type == NodeType.MODULE.value}
        mod_graph: dict[str, set[str]] = defaultdict(set)
        fan_in: dict[str, int] = defaultdict(int)
        fan_out: dict[str, int] = defaultdict(int)
        unresolved_imports = []
        layer_violations = []

        for edge in edges:
            if edge.rel_type in (EdgeType.IMPORTS.value, EdgeType.DEPENDS_ON.value):
                src_node = nodes.get(edge.source_canonical_id)
                tgt_node = nodes.get(edge.target_canonical_id)

                if src_node and src_node.entity_type == NodeType.MODULE.value:
                    if tgt_node and tgt_node.entity_type == NodeType.MODULE.value:
                        mod_graph[src_node.name].add(tgt_node.name)
                        fan_out[src_node.name] += 1
                        fan_in[tgt_node.name] += 1

                        # Layer violation check: data/model layer importing api layer
                        src_lower = src_node.file_path.lower()
                        tgt_lower = tgt_node.file_path.lower()
                        if ("model" in src_lower or "db" in src_lower) and ("api" in tgt_lower or "routes" in tgt_lower):
                            layer_violations.append({
                                "source": src_node.name,
                                "target": tgt_node.name,
                                "rule": "DATA_LAYER_DEPENDS_ON_API_LAYER",
                                "severity": "HIGH",
                                "evidence": edge.evidence_location,
                            })

                if edge.provenance.get("unresolved"):
                    unresolved_imports.append({
                        "source": src_node.name if src_node else edge.source_canonical_id,
                        "target": edge.target_canonical_id,
                        "location": edge.evidence_location,
                    })

        # 2. Cycle detection via Tarjan's SCC
        cycles = TarjanCycleDetector.find_cycles(mod_graph)

        # 3. High fan-in and fan-out
        high_fan_in = [
            {"module": mod, "fan_in": count}
            for mod, count in sorted(fan_in.items(), key=lambda x: -x[1])[:10]
        ]
        high_fan_out = [
            {"module": mod, "fan_out": count}
            for mod, count in sorted(fan_out.items(), key=lambda x: -x[1])[:10]
        ]

        # 4. Orphaned modules
        all_mod_names = {n.name for n in mod_nodes.values()}
        orphaned = [
            m for m in sorted(all_mod_names)
            if fan_in[m] == 0 and fan_out[m] == 0 and not m.endswith("__main__") and not m.endswith("__init__")
        ]

        return ArchitectureMetricsReport(
            total_modules=len(mod_nodes),
            circular_dependencies=cycles,
            high_fan_in_modules=high_fan_in,
            high_fan_out_modules=high_fan_out,
            orphaned_modules=orphaned,
            unresolved_imports=unresolved_imports,
            layer_violations=layer_violations,
        )

