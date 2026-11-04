"""Graph Version Comparison & Diffing Engine for APEX 2.0 (Phase 3.1).

Computes comprehensive structural and relationship diffs between two knowledge graph versions:
- Added, removed, and modified nodes.
- Renamed and moved files and symbols (correlated with IdentityContinuity transitions).
- Added, removed, and modified edges (confidence, resolution status).
- Quantitative diff summary metrics.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from app.models.entities import (
    EngineeringGraphEdge,
    EngineeringGraphNode,
    EngineeringGraphVersion,
    EngineeringIdentityTransition,
)


@dataclass
class VersionDiffReport:
    project_id: int
    version_a_number: int
    version_b_number: int
    added_nodes_count: int
    removed_nodes_count: int
    modified_nodes_count: int
    renamed_entities_count: int
    added_edges_count: int
    removed_edges_count: int
    changed_relationships_count: int
    added_nodes: list[dict[str, Any]] = field(default_factory=list)
    removed_nodes: list[dict[str, Any]] = field(default_factory=list)
    modified_nodes: list[dict[str, Any]] = field(default_factory=list)
    renamed_entities: list[dict[str, Any]] = field(default_factory=list)
    added_edges: list[dict[str, Any]] = field(default_factory=list)
    removed_edges: list[dict[str, Any]] = field(default_factory=list)
    changed_relationships: list[dict[str, Any]] = field(default_factory=list)
    # Phase 3.2 additions:
    split_entities: list[dict[str, Any]] = field(default_factory=list)
    merged_entities: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class GraphVersionComparator:
    """Compares two persistent graph version snapshots to reveal architectural evolution."""

    @classmethod
    def compare_versions(
        cls,
        db: Session,
        project_id: int,
        version_a_id_or_number: int,
        version_b_id_or_number: int,
    ) -> VersionDiffReport:
        # Load version records
        ver_a = (
            db.query(EngineeringGraphVersion)
            .filter(
                EngineeringGraphVersion.project_id == project_id,
                (EngineeringGraphVersion.id == version_a_id_or_number)
                | (EngineeringGraphVersion.version_number == version_a_id_or_number),
            )
            .first()
        )
        ver_b = (
            db.query(EngineeringGraphVersion)
            .filter(
                EngineeringGraphVersion.project_id == project_id,
                (EngineeringGraphVersion.id == version_b_id_or_number)
                | (EngineeringGraphVersion.version_number == version_b_id_or_number),
            )
            .first()
        )

        if not ver_a or not ver_b:
            raise ValueError(f"One or both graph versions not found for project {project_id}.")

        # Load nodes
        nodes_a = {
            n.canonical_id: n
            for n in db.query(EngineeringGraphNode)
            .filter(
                EngineeringGraphNode.project_id == project_id,
                EngineeringGraphNode.version_id == ver_a.id,
            )
            .all()
        }
        nodes_b = {
            n.canonical_id: n
            for n in db.query(EngineeringGraphNode)
            .filter(
                EngineeringGraphNode.project_id == project_id,
                EngineeringGraphNode.version_id == ver_b.id,
            )
            .all()
        }

        # Load edges
        edges_a = {
            (e.source_canonical_id, e.target_canonical_id, e.rel_type): e
            for e in db.query(EngineeringGraphEdge)
            .filter(
                EngineeringGraphEdge.project_id == project_id,
                EngineeringGraphEdge.version_id == ver_a.id,
            )
            .all()
        }
        edges_b = {
            (e.source_canonical_id, e.target_canonical_id, e.rel_type): e
            for e in db.query(EngineeringGraphEdge)
            .filter(
                EngineeringGraphEdge.project_id == project_id,
                EngineeringGraphEdge.version_id == ver_b.id,
            )
            .all()
        }

        # Load identity transitions between these versions
        transitions = (
            db.query(EngineeringIdentityTransition)
            .filter(
                EngineeringIdentityTransition.project_id == project_id,
                EngineeringIdentityTransition.to_version_id == ver_b.id,
            )
            .all()
        )

        renamed_transitions = [
            t for t in transitions
            if t.transition_type in (
                "RENAMED_FILE", "MOVED_FILE", "RENAMED_SYMBOL",
                "RENAMED_AND_MODIFIED", "SPLIT", "MERGED"
            )
        ]

        renamed_old_ids: set[str] = set()
        renamed_new_ids: set[str] = set()
        for t in renamed_transitions:
            for oid in (t.old_canonical_id or "").split(","):
                if oid.strip():
                    renamed_old_ids.add(oid.strip())
            for nid in (t.new_canonical_id or "").split(","):
                if nid.strip():
                    renamed_new_ids.add(nid.strip())

        split_entities = [
            {
                "old_canonical_id": t.old_canonical_id,
                "new_canonical_id": t.new_canonical_id,
                "transition_type": t.transition_type,
                "confidence": t.confidence,
                "evidence": t.evidence,
            }
            for t in transitions
            if t.transition_type == "SPLIT"
        ]

        merged_entities = [
            {
                "old_canonical_id": t.old_canonical_id,
                "new_canonical_id": t.new_canonical_id,
                "transition_type": t.transition_type,
                "confidence": t.confidence,
                "evidence": t.evidence,
            }
            for t in transitions
            if t.transition_type == "MERGED"
        ]

        # 1. Added Nodes: present in B, not in A, and not a target of rename
        added_nodes = [
            {
                "canonical_id": cid,
                "name": n.name,
                "entity_type": n.entity_type,
                "file_path": n.file_path,
                "start_line": n.start_line,
            }
            for cid, n in nodes_b.items()
            if cid not in nodes_a and cid not in renamed_new_ids
        ]

        # 2. Removed Nodes: present in A, not in B, and not an origin of rename
        removed_nodes = [
            {
                "canonical_id": cid,
                "name": n.name,
                "entity_type": n.entity_type,
                "file_path": n.file_path,
                "start_line": n.start_line,
            }
            for cid, n in nodes_a.items()
            if cid not in nodes_b and cid not in renamed_old_ids
        ]

        # 3. Modified Nodes: present in both with changed line numbers or structural fingerprints
        modified_nodes = []
        for cid, n_b in nodes_b.items():
            if cid in nodes_a:
                n_a = nodes_a[cid]
                fp_a = (n_a.node_metadata or {}).get("structural_fingerprint")
                fp_b = (n_b.node_metadata or {}).get("structural_fingerprint")
                lines_changed = (n_a.start_line != n_b.start_line) or (n_a.end_line != n_b.end_line)
                if lines_changed or (fp_a and fp_b and fp_a != fp_b):
                    modified_nodes.append({
                        "canonical_id": cid,
                        "name": n_b.name,
                        "entity_type": n_b.entity_type,
                        "file_path": n_b.file_path,
                        "old_lines": (n_a.start_line, n_a.end_line),
                        "new_lines": (n_b.start_line, n_b.end_line),
                    })

        # 4. Renamed Entities
        renamed_entities = [
            {
                "old_canonical_id": t.old_canonical_id,
                "new_canonical_id": t.new_canonical_id,
                "transition_type": t.transition_type,
                "confidence": t.confidence,
                "evidence": t.evidence,
            }
            for t in renamed_transitions
        ]

        # 5. Added Edges
        added_edges = [
            {
                "source": k[0],
                "target": k[1],
                "rel_type": k[2],
                "confidence": e.confidence,
            }
            for k, e in edges_b.items()
            if k not in edges_a
        ]

        # 6. Removed Edges
        removed_edges = [
            {
                "source": k[0],
                "target": k[1],
                "rel_type": k[2],
                "confidence": e.confidence,
            }
            for k, e in edges_a.items()
            if k not in edges_b
        ]

        # 7. Changed Relationships (same source/target/type but confidence or resolution changed)
        changed_relationships = []
        for k, e_b in edges_b.items():
            if k in edges_a:
                e_a = edges_a[k]
                res_a = (e_a.provenance or {}).get("resolution")
                res_b = (e_b.provenance or {}).get("resolution")
                if abs(e_a.confidence - e_b.confidence) > 0.05 or res_a != res_b:
                    changed_relationships.append({
                        "source": k[0],
                        "target": k[1],
                        "rel_type": k[2],
                        "old_confidence": e_a.confidence,
                        "new_confidence": e_b.confidence,
                        "old_resolution": res_a,
                        "new_resolution": res_b,
                    })

        return VersionDiffReport(
            project_id=project_id,
            version_a_number=ver_a.version_number,
            version_b_number=ver_b.version_number,
            added_nodes_count=len(added_nodes),
            removed_nodes_count=len(removed_nodes),
            modified_nodes_count=len(modified_nodes),
            renamed_entities_count=len(renamed_entities),
            added_edges_count=len(added_edges),
            removed_edges_count=len(removed_edges),
            changed_relationships_count=len(changed_relationships),
            added_nodes=added_nodes[:100],
            removed_nodes=removed_nodes[:100],
            modified_nodes=modified_nodes[:100],
            renamed_entities=renamed_entities,
            added_edges=added_edges[:100],
            removed_edges=removed_edges[:100],
            changed_relationships=changed_relationships[:100],
            split_entities=split_entities,
            merged_entities=merged_entities,
        )

