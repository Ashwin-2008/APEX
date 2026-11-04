"""Graph Storage & Versioning Architecture for APEX 2.0.

Provides robust relational persistence across SQLite and PostgreSQL for graph nodes,
edges, and immutable versions with strict multi-tenant isolation, consistency checks,
and atomic snapshot management.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.models.entities import (
    EngineeringGraphEdge,
    EngineeringGraphNode,
    EngineeringGraphVersion,
)
from app.services.graph.models import GraphEdge, GraphNode

logger = logging.getLogger(__name__)


class GraphStorageManager:
    """Manages graph persistence, versioning, tenant isolation, and consistency."""

    @classmethod
    def persist_graph(
        cls,
        db: Session,
        project_id: int,
        nodes: dict[str, GraphNode],
        edges: list[GraphEdge],
        commit_sha: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> EngineeringGraphVersion:
        """Persists a new active graph version and marks prior versions inactive."""
        # Determine next version number
        latest = (
            db.query(EngineeringGraphVersion)
            .filter(EngineeringGraphVersion.project_id == project_id)
            .order_by(EngineeringGraphVersion.version_number.desc())
            .first()
        )
        next_ver = (latest.version_number + 1) if latest else 1

        # Deactivate previous active version
        db.query(EngineeringGraphVersion).filter(
            EngineeringGraphVersion.project_id == project_id,
            EngineeringGraphVersion.is_current == True,
        ).update({"is_current": False, "status": "SUPERSEDED"})

        new_version = EngineeringGraphVersion(
            project_id=project_id,
            version_number=next_ver,
            commit_sha=commit_sha,
            is_current=True,
            status="ACTIVE",
            node_count=len(nodes),
            edge_count=len(edges),
            metadata_json=metadata or {},
        )
        db.add(new_version)
        db.flush()

        # Insert nodes
        db_nodes = []
        for n in nodes.values():
            db_nodes.append(
                EngineeringGraphNode(
                    project_id=project_id,
                    version_id=new_version.id,
                    canonical_id=n.canonical_id,
                    entity_type=n.entity_type,
                    name=n.name,
                    qualified_name=n.qualified_name,
                    file_path=n.file_path,
                    start_line=n.start_line,
                    end_line=n.end_line,
                    node_metadata=n.metadata,
                )
            )
        db.bulk_save_objects(db_nodes)

        # Insert edges
        db_edges = []
        for e in edges:
            db_edges.append(
                EngineeringGraphEdge(
                    project_id=project_id,
                    version_id=new_version.id,
                    source_canonical_id=e.source_canonical_id,
                    target_canonical_id=e.target_canonical_id,
                    rel_type=e.rel_type,
                    confidence=e.confidence,
                    evidence_location=e.evidence_location,
                    analyzer_source=e.analyzer_source,
                    provenance=e.provenance,
                )
            )
        db.bulk_save_objects(db_edges)
        db.commit()
        db.refresh(new_version)
        return new_version

    @classmethod
    def get_current_version(cls, db: Session, project_id: int) -> EngineeringGraphVersion | None:
        return (
            db.query(EngineeringGraphVersion)
            .filter(
                EngineeringGraphVersion.project_id == project_id,
                EngineeringGraphVersion.is_current == True,
            )
            .first()
        )

    @classmethod
    def load_active_graph(
        cls,
        db: Session,
        project_id: int,
    ) -> tuple[dict[str, GraphNode], list[GraphEdge], EngineeringGraphVersion | None]:
        """Loads the currently active graph into memory."""
        version = cls.get_current_version(db, project_id)
        if not version:
            return {}, [], None

        db_nodes = (
            db.query(EngineeringGraphNode)
            .filter(
                EngineeringGraphNode.project_id == project_id,
                EngineeringGraphNode.version_id == version.id,
            )
            .all()
        )
        db_edges = (
            db.query(EngineeringGraphEdge)
            .filter(
                EngineeringGraphEdge.project_id == project_id,
                EngineeringGraphEdge.version_id == version.id,
            )
            .all()
        )

        nodes: dict[str, GraphNode] = {}
        for dn in db_nodes:
            nodes[dn.canonical_id] = GraphNode(
                canonical_id=dn.canonical_id,
                project_id=dn.project_id,
                entity_type=dn.entity_type,
                name=dn.name,
                qualified_name=dn.qualified_name,
                file_path=dn.file_path,
                start_line=dn.start_line,
                end_line=dn.end_line,
                metadata=dn.node_metadata or {},
            )

        edges: list[GraphEdge] = []
        for de in db_edges:
            edges.append(
                GraphEdge(
                    source_canonical_id=de.source_canonical_id,
                    target_canonical_id=de.target_canonical_id,
                    rel_type=de.rel_type,
                    project_id=de.project_id,
                    confidence=de.confidence,
                    evidence_location=de.evidence_location,
                    analyzer_source=de.analyzer_source,
                    provenance=de.provenance or {},
                )
            )

        return nodes, edges, version

    @classmethod
    def verify_consistency(
        cls,
        nodes: dict[str, GraphNode],
        edges: list[GraphEdge],
    ) -> dict[str, Any]:
        """Runs integrity and consistency checks on in-memory or persisted graph data."""
        dangling_sources = []
        dangling_targets = []
        edge_keys = set()
        duplicate_edges = 0

        for edge in edges:
            key = (edge.source_canonical_id, edge.target_canonical_id, edge.rel_type)
            if key in edge_keys:
                duplicate_edges += 1
            edge_keys.add(key)

            if edge.source_canonical_id not in nodes:
                dangling_sources.append(edge.source_canonical_id)
            if edge.target_canonical_id not in nodes and not edge.provenance.get("unresolved"):
                dangling_targets.append(edge.target_canonical_id)

        is_consistent = duplicate_edges == 0 and len(dangling_sources) == 0

        return {
            "is_consistent": is_consistent,
            "node_count": len(nodes),
            "edge_count": len(edges),
            "duplicate_edges": duplicate_edges,
            "dangling_sources_count": len(dangling_sources),
            "dangling_targets_count": len(dangling_targets),
            "unresolved_edges_count": sum(1 for e in edges if e.provenance.get("unresolved")),
        }

