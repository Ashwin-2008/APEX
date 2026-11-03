"""Architecture Intelligence Engine: canonical module resolution, dependency graphs, and cycle detection.

Implements Module B of Phase 2A:
- Canonical Python module resolution (eliminating path vs module mismatches).
- Directed dependency graph with typed edges (import, call).
- Cycle detection via Tarjan's Strongly Connected Components algorithm.
- Architectural coupling, fan-in/fan-out metrics, and layer violation detection.
- Structured graph visualization data for frontend consumers.
"""
from __future__ import annotations

import time
from collections import defaultdict
from pathlib import Path
from typing import Any

from app.services.analyzers.base import AnalyzerOutput, AnalyzerStatus, FindingItem
from app.services.analyzers.repository_graph import (
    RepositorySymbolIndex,
    TarjanCycleDetector,
)

LAYER_RANKS = {
    "db": 1,
    "model": 2,
    "models": 2,
    "core": 2,
    "utils": 2,
    "util": 2,
    "service": 3,
    "services": 3,
    "api": 4,
    "routes": 4,
    "views": 4,
    "controllers": 4,
    "main": 5,
}


def _classify_layer(module_name: str, file_path: str) -> str:
    parts = (module_name + "." + file_path.replace("/", ".")).lower().split(".")
    for part in parts:
        if part in LAYER_RANKS:
            return part
    return "general"


def run_architecture_analysis(root_dir: str | Path) -> AnalyzerOutput:
    """Analyze module boundaries, canonical import graphs, circular dependencies, and layer violations."""
    start_time = time.perf_counter()
    root = Path(root_dir).resolve()
    findings: list[FindingItem] = []

    # 1. Build canonical symbol index and import graph
    symbol_index = RepositorySymbolIndex(root)
    import_graph = symbol_index.import_graph

    # Filter graph to only internal project modules for precise cycle detection
    internal_modules = set(symbol_index.modules.keys())
    clean_graph: dict[str, set[str]] = defaultdict(set)
    incoming_counts: dict[str, int] = defaultdict(int)
    outgoing_counts: dict[str, int] = defaultdict(int)

    for src, targets in import_graph.items():
        for tgt in targets:
            # Check if tgt is an internal module
            if tgt in internal_modules:
                clean_graph[src].add(tgt)
                outgoing_counts[src] += 1
                incoming_counts[tgt] += 1
            else:
                # Check if any internal module ends with target or matches subpackage
                for imod in internal_modules:
                    if imod.endswith(f".{tgt}") or imod == tgt:
                        clean_graph[src].add(imod)
                        outgoing_counts[src] += 1
                        incoming_counts[imod] += 1
                        break

    # Ensure all internal modules exist in clean_graph
    for m in internal_modules:
        if m not in clean_graph:
            clean_graph[m] = set()

    # 2. Cycle Detection via Tarjan's SCC Algorithm
    cycles = TarjanCycleDetector.find_cycles(clean_graph)

    for cycle in cycles:
        cycle_str = " -> ".join(cycle)
        first_mod = cycle[0]
        first_file = symbol_index.modules[first_mod].file_path if first_mod in symbol_index.modules else None

        findings.append(
            FindingItem(
                category="architecture",
                severity="high",
                confidence=0.98,
                evidence=f"Circular module dependency detected: {cycle_str}.",
                analyzer_source="architecture_cycle_analyzer",
                rule_id="ARCH-CIRCULAR-DEPENDENCY",
                file=first_file,
                title=f"Circular Module Dependency ({len(cycle) - 1} hops)",
                remediation="Extract shared abstractions/interfaces into a foundational module or invert dependencies using interfaces.",
                data_flow=[
                    {
                        "step": idx + 1,
                        "module": mod,
                        "file": symbol_index.modules[mod].file_path if mod in symbol_index.modules else mod,
                        "role": "cycle_node",
                    }
                    for idx, mod in enumerate(cycle)
                ],
                metadata={
                    "cycle": cycle,
                    "cycle_length": len(cycle) - 1,
                    "nodes": cycle[:-1],
                },
            )
        )

    # 3. Layer Boundary Violations (e.g. Model importing Controller/API)
    for src, targets in clean_graph.items():
        src_mod = symbol_index.modules.get(src)
        src_file = src_mod.file_path if src_mod else ""
        src_layer = _classify_layer(src, src_file)
        src_rank = LAYER_RANKS.get(src_layer, 0)

        for tgt in targets:
            tgt_mod = symbol_index.modules.get(tgt)
            tgt_file = tgt_mod.file_path if tgt_mod else ""
            tgt_layer = _classify_layer(tgt, tgt_file)
            tgt_rank = LAYER_RANKS.get(tgt_layer, 0)

            # Lower architectural layers must not depend on higher layers (e.g. model importing api)
            if src_rank in {1, 2} and tgt_rank in {4, 5}:
                findings.append(
                    FindingItem(
                        category="architecture",
                        severity="medium",
                        confidence=0.90,
                        evidence=(
                            f"Architectural layer violation: lower layer module '{src}' ({src_layer}) "
                            f"imports higher presentation layer '{tgt}' ({tgt_layer})."
                        ),
                        analyzer_source="layer_boundary_analyzer",
                        rule_id="ARCH-LAYER-VIOLATION",
                        file=src_file,
                        title=f"Architectural Layer Inversion: {src_layer} -> {tgt_layer}",
                        remediation=f"Decouple '{src}' from '{tgt}'. Lower database and model layers must not depend on API/route layers.",
                        metadata={
                            "source_module": src,
                            "source_layer": src_layer,
                            "target_module": tgt,
                            "target_layer": tgt_layer,
                        },
                    )
                )

    # 4. God Module / Extreme Coupling Detection
    for mod_name, mod_info in symbol_index.modules.items():
        fan_in = incoming_counts[mod_name]
        fan_out = outgoing_counts[mod_name]
        loc = mod_info.loc

        if (fan_in >= 12 and fan_out >= 12) or (loc >= 400 and fan_out >= 18):
            findings.append(
                FindingItem(
                    category="architecture",
                    severity="medium",
                    confidence=0.88,
                    evidence=(
                        f"God module detected: '{mod_name}' has high bidirectional coupling "
                        f"(fan-in={fan_in}, fan-out={fan_out}, LOC={loc})."
                    ),
                    analyzer_source="coupling_analyzer",
                    rule_id="ARCH-GOD-MODULE",
                    file=mod_info.file_path,
                    title=f"Architectural Hotspot: God Module '{mod_name}'",
                    remediation="Decompose this module into focused, single-responsibility components with isolated domain boundaries.",
                    metadata={"fan_in": fan_in, "fan_out": fan_out, "loc": loc},
                )
            )

    # 5. Graph Structure for Visualization
    graph_nodes = []
    for mod_name, mod_info in symbol_index.modules.items():
        graph_nodes.append({
            "id": mod_name,
            "label": mod_name.split(".")[-1],
            "file": mod_info.file_path,
            "package": mod_info.package,
            "layer": _classify_layer(mod_name, mod_info.file_path),
            "fan_in": incoming_counts[mod_name],
            "fan_out": outgoing_counts[mod_name],
            "loc": mod_info.loc,
        })

    graph_edges = []
    for src, targets in clean_graph.items():
        for tgt in targets:
            graph_edges.append({
                "source": src,
                "target": tgt,
                "type": "import",
            })

    total_edges = len(graph_edges)
    total_nodes = len(graph_nodes)
    density = round(total_edges / max(1, total_nodes * (total_nodes - 1)), 4) if total_nodes > 1 else 0.0

    duration = (time.perf_counter() - start_time) * 1000
    return AnalyzerOutput(
        analyzer_name="architecture_analyzer",
        status=AnalyzerStatus.COMPLETE,
        findings=findings,
        metrics={
            "module_count": total_nodes,
            "dependency_edges": total_edges,
            "cycle_count": len(cycles),
            "graph_density": density,
            "architecture_graph": {
                "nodes": graph_nodes[:200],  # Bound for UI serialization
                "edges": graph_edges[:500],
                "cycles": cycles,
            },
        },
        duration_ms=duration,
        files_analyzed=len(symbol_index.modules),
        files_skipped=len(symbol_index.parse_errors),
    )
