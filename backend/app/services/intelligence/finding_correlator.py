"""Cross-Analyzer Finding Correlation and Relationship Graph Engine for APEX 2.0.

Discovers semantic, architectural, and causal relationships across findings from
different analyzers and performs multi-stage deduplication while preserving evidence.
"""
from __future__ import annotations

import hashlib
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from app.services.analyzers.base import FindingItem


class CorrelationRelationship(str, Enum):
    SAME_ROOT_CAUSE = "SAME_ROOT_CAUSE"
    SUPPORTING_EVIDENCE = "SUPPORTING_EVIDENCE"
    DEPENDENT_ON = "DEPENDENT_ON"
    POSSIBLE_DUPLICATE = "POSSIBLE_DUPLICATE"
    CAUSALLY_RELATED = "CAUSALLY_RELATED"
    RUNTIME_CORROBORATES = "RUNTIME_CORROBORATES"
    ARCHITECTURALLY_RELATED = "ARCHITECTURALLY_RELATED"
    REGRESSION_OF = "REGRESSION_OF"


@dataclass
class FindingRelationship:
    source_finding_id: str
    target_finding_id: str
    relationship_type: CorrelationRelationship
    confidence: float
    reason: str
    is_inferred: bool = False

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["relationship_type"] = self.relationship_type.value
        return data


@dataclass
class CorrelatedFindingCluster:
    cluster_id: str
    primary_finding_id: str
    related_finding_ids: list[str] = field(default_factory=list)
    common_category: str = "general"
    file: str | None = None
    line: int | None = None
    confidence: float = 0.80
    explanation: str = ""
    attached_observations: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class FindingCorrelator:
    """Discovers cross-analyzer correlations and constructs the repository finding graph."""

    def __init__(self) -> None:
        self.relationships: list[FindingRelationship] = []
        self.graph_nodes: dict[str, dict[str, Any]] = {}
        self.graph_edges: list[dict[str, Any]] = []

    def correlate(self, findings: list[FindingItem | dict[str, Any]]) -> list[FindingRelationship]:
        """Examine a set of findings across all analyzers to discover relationships."""
        self.relationships.clear()
        self.graph_nodes.clear()
        self.graph_edges.clear()

        normalized: list[dict[str, Any]] = [
            f.to_dict() if isinstance(f, FindingItem) else f for f in findings
        ]

        # 1. Register finding nodes in graph
        for idx, f in enumerate(normalized):
            fid = f.get("fingerprint") or f"f_{idx}"
            self.graph_nodes[fid] = {
                "id": fid,
                "type": "finding",
                "category": f.get("category"),
                "severity": f.get("severity"),
                "file": f.get("file"),
                "line": f.get("line"),
                "rule_id": f.get("rule_id"),
                "analyzer_source": f.get("analyzer_source"),
            }

        # 2. Pairwise cross-analyzer correlation
        n = len(normalized)
        for i in range(n):
            for j in range(i + 1, n):
                f1 = normalized[i]
                f2 = normalized[j]
                fid1 = f1.get("fingerprint") or f"f_{i}"
                fid2 = f2.get("fingerprint") or f"f_{j}"

                self._check_correlation_pair(f1, f2, fid1, fid2)

        return self.relationships

    def _check_correlation_pair(
        self,
        f1: dict[str, Any],
        f2: dict[str, Any],
        fid1: str,
        fid2: str,
    ) -> None:
        file1 = (f1.get("file") or "").replace("\\", "/").lower()
        file2 = (f2.get("file") or "").replace("\\", "/").lower()
        line1 = f1.get("line")
        line2 = f2.get("line")
        cat1 = f1.get("category", "").lower()
        cat2 = f2.get("category", "").lower()
        source1 = f1.get("analyzer_source", "").lower()
        source2 = f2.get("analyzer_source", "").lower()
        ev1 = f1.get("evidence", "").lower()
        ev2 = f2.get("evidence", "").lower()

        # Check 1: Runtime Test Failure Corroboration
        if "[correlated test failure]" in ev1 or "[correlated test failure]" in ev2 or "dynamic" in source1 or "dynamic" in source2:
            if file1 and file1 == file2 and line1 and line2 and abs(line1 - line2) <= 3:
                rel = FindingRelationship(
                    source_finding_id=fid1,
                    target_finding_id=fid2,
                    relationship_type=CorrelationRelationship.RUNTIME_CORROBORATES,
                    confidence=0.92,
                    reason=f"Runtime test execution corroborates static flaw at {file1}:{line1}",
                    is_inferred=False,
                )
                self.relationships.append(rel)
                self._add_edge(fid1, fid2, "corroborates", rel.confidence)
                return

        # Check 2: Same Root Cause across distinct analyzers in same file & line
        if file1 and file1 == file2 and line1 and line2 and abs(line1 - line2) <= 2:
            # Different analyzers observing the same defect
            if source1 != source2:
                rel = FindingRelationship(
                    source_finding_id=fid1,
                    target_finding_id=fid2,
                    relationship_type=CorrelationRelationship.SAME_ROOT_CAUSE,
                    confidence=0.88,
                    reason=f"Analyzers '{source1}' and '{source2}' observe correlated aspects of defect at {file1}:{line1}",
                    is_inferred=True,
                )
                self.relationships.append(rel)
                self._add_edge(fid1, fid2, "same_root_cause", rel.confidence)
                return
            else:
                # Same analyzer, same location -> Possible duplicate
                rel = FindingRelationship(
                    source_finding_id=fid1,
                    target_finding_id=fid2,
                    relationship_type=CorrelationRelationship.POSSIBLE_DUPLICATE,
                    confidence=0.90,
                    reason=f"Identical file and line ({file1}:{line1}) reported by '{source1}'",
                    is_inferred=False,
                )
                self.relationships.append(rel)
                self._add_edge(fid1, fid2, "possible_duplicate", rel.confidence)
                return

        # Check 3: Cross-File Data Flow / Taint Connection
        df1 = f1.get("data_flow", [])
        df2 = f2.get("data_flow", [])
        if df1 and df2:
            files1 = {s.get("file", "").replace("\\", "/").lower() for s in df1}
            files2 = {s.get("file", "").replace("\\", "/").lower() for s in df2}
            if files1.intersection(files2) and (cat1 == "security" or cat2 == "security"):
                rel = FindingRelationship(
                    source_finding_id=fid1,
                    target_finding_id=fid2,
                    relationship_type=CorrelationRelationship.CAUSALLY_RELATED,
                    confidence=0.82,
                    reason=f"Shared taint propagation path across files {list(files1.intersection(files2))}",
                    is_inferred=True,
                )
                self.relationships.append(rel)
                self._add_edge(fid1, fid2, "causally_related", rel.confidence)
                return

        # Check 4: Architectural Cycle Relationship
        if cat1 == "architecture" and cat2 == "architecture":
            cycle1 = f1.get("metadata", {}).get("cycle", [])
            cycle2 = f2.get("metadata", {}).get("cycle", [])
            if cycle1 and cycle2 and set(cycle1).intersection(set(cycle2)):
                rel = FindingRelationship(
                    source_finding_id=fid1,
                    target_finding_id=fid2,
                    relationship_type=CorrelationRelationship.ARCHITECTURALLY_RELATED,
                    confidence=0.95,
                    reason="Shared cyclic dependency component in architecture graph",
                    is_inferred=False,
                )
                self.relationships.append(rel)
                self._add_edge(fid1, fid2, "architecturally_related", rel.confidence)

    def _add_edge(self, source: str, target: str, label: str, weight: float) -> None:
        self.graph_edges.append({
            "source": source,
            "target": target,
            "label": label,
            "weight": round(weight, 2),
        })

    def deduplicate_multi_stage(
        self,
        findings: list[FindingItem | dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], list[CorrelatedFindingCluster]]:
        """Multi-stage deduplication: preserves all evidence as attached observations."""
        normalized: list[dict[str, Any]] = [
            f.to_dict() if isinstance(f, FindingItem) else dict(f) for f in findings
        ]

        # Stage 1: Group by semantic fingerprint
        by_fp: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for f in normalized:
            fp = f.get("fingerprint") or hashlib.sha256(
                f"{f.get('analyzer_source')}:{f.get('rule_id')}:{f.get('file')}:{f.get('line')}".encode()
            ).hexdigest()
            f["fingerprint"] = fp
            by_fp[fp].append(f)

        deduped_stage1: list[dict[str, Any]] = []
        for fp, group in by_fp.items():
            primary = dict(group[0])
            if len(group) > 1:
                # Attach other observations
                primary["attached_observations"] = [
                    {"analyzer_source": g.get("analyzer_source"), "evidence": g.get("evidence"), "rule_id": g.get("rule_id")}
                    for g in group[1:]
                ]
            deduped_stage1.append(primary)

        # Stage 2: Group by identical file, line, and category
        by_location: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for f in deduped_stage1:
            loc_key = f"{f.get('category')}:{f.get('file')}:{f.get('line')}"
            by_location[loc_key].append(f)

        final_findings: list[dict[str, Any]] = []
        clusters: list[CorrelatedFindingCluster] = []

        for loc_key, group in by_location.items():
            primary = group[0]
            if len(group) > 1:
                c_id = f"cluster_{hashlib.sha256(loc_key.encode()).hexdigest()[:10]}"
                cluster = CorrelatedFindingCluster(
                    cluster_id=c_id,
                    primary_finding_id=primary.get("fingerprint", ""),
                    related_finding_ids=[g.get("fingerprint", "") for g in group[1:]],
                    common_category=primary.get("category", "general"),
                    file=primary.get("file"),
                    line=primary.get("line"),
                    explanation=f"{len(group)} analyzers identified related issues at {primary.get('file')}:{primary.get('line')}",
                    attached_observations=[
                        {"source": g.get("analyzer_source"), "rule": g.get("rule_id"), "evidence": g.get("evidence")}
                        for g in group
                    ],
                )
                clusters.append(cluster)
                primary["cluster_id"] = c_id

            final_findings.append(primary)

        return final_findings, clusters

