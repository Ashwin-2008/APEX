"""Transactional Graph Update & Crash Recovery Engine for APEX 2.0 (Phase 3.1 & Phase 3.2).

Guarantees transactional integrity, atomic version activation, and crash recovery:
- Workflow:
  1. Content-hash based change detection (SHA-256).
  2. Concurrency protection (active staging lease / conflict detection).
  3. Create staging version (status="STAGED", is_current=False).
  4. Extraction of affected slices and cross-technology relationships.
  5. Multi-signal identity continuity transitions.
  6. Graph consistency & integrity validation (no dangling edges, no duplicate canonical nodes).
  7. Persist staged entities (nodes, edges, transitions).
  8. Atomic activation (status="ACTIVE", is_current=True) & supersede previous.
  9. Retain all historical versions for diffing and auditability.
- Crash recovery:
  - Recovers from interrupted staging processes or sudden worker termination.
  - Cleans up orphaned staging nodes, edges, and transitions while preserving the active graph.
  - Idempotent recovery.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import logging
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.models.entities import (
    EngineeringGraphEdge,
    EngineeringGraphNode,
    EngineeringGraphUpdateJournal,
    EngineeringGraphVersion,
    EngineeringIdentityTransition,
)
from app.services.graph.extractor import GraphExtractionEngine
from app.services.graph.identity_continuity import IdentityContinuityEngine
from app.services.graph.models import GraphEdge, GraphNode, NodeType
from app.services.graph.storage import GraphStorageManager

logger = logging.getLogger(__name__)


class TransactionalGraphUpdater:
    """Manages staged, atomic, crash-resilient graph updates with multi-process concurrency protection."""

    STAGING_LOCK_TIMEOUT_SECONDS = 60

    @classmethod
    def compute_file_hashes(cls, repo_root: Path) -> dict[str, str]:
        """Calculates SHA-256 content hashes for all relevant source files in the repository."""
        file_hashes: dict[str, str] = {}
        for p in repo_root.rglob("*"):
            if not p.is_file():
                continue
            if any(skip in p.parts for skip in {".git", "node_modules", "venv", ".venv", "__pycache__", ".pytest_cache", "dist", "build"}):
                continue
            if p.suffix in {".py", ".ts", ".tsx", ".js", ".jsx", ".json", ".sql", ".dockerfile", ".yml", ".yaml"} or p.name in {"Dockerfile", "docker-compose.yml"}:
                try:
                    rel = str(p.relative_to(repo_root)).replace("\\", "/")
                    content = p.read_bytes()
                    file_hashes[rel] = hashlib.sha256(content).hexdigest()
                except Exception:
                    continue
        return file_hashes

    @classmethod
    def detect_changes_by_hash(
        cls,
        repo_root: Path,
        existing_nodes: dict[str, GraphNode],
    ) -> tuple[set[str], set[str], dict[str, str]]:
        """Compares on-disk file content hashes against stored node metadata hashes."""
        current_hashes = cls.compute_file_hashes(repo_root)

        stored_hashes: dict[str, str] = {}
        for n in existing_nodes.values():
            if n.file_path and "content_hash" in n.metadata:
                stored_hashes[n.file_path] = n.metadata["content_hash"]

        changed_files: set[str] = set()
        deleted_files: set[str] = set()

        for fpath, h in current_hashes.items():
            if fpath not in stored_hashes:
                changed_files.add(fpath)
            elif stored_hashes[fpath] != h:
                changed_files.add(fpath)

        for fpath in stored_hashes.keys():
            if fpath not in current_hashes:
                deleted_files.add(fpath)

        return changed_files, deleted_files, current_hashes

    @classmethod
    def log_journal_entry(
        cls,
        db: Session,
        project_id: int,
        version_id: int,
        stage: str,
        manifest: dict[str, Any] | None = None,
        error_message: str | None = None,
    ) -> EngineeringGraphUpdateJournal:
        """Persists a stage journal entry for auditability and recovery."""
        journal = EngineeringGraphUpdateJournal(
            project_id=project_id,
            version_id=version_id,
            stage=stage,
            manifest=manifest or {},
            error_message=error_message,
        )
        db.add(journal)
        db.flush()
        return journal

    @classmethod
    def check_and_acquire_concurrency_lock(cls, db: Session, project_id: int) -> None:
        """Verifies that no other concurrent worker is actively staging an update for this project."""
        active_staging = (
            db.query(EngineeringGraphVersion)
            .filter(
                EngineeringGraphVersion.project_id == project_id,
                EngineeringGraphVersion.status == "STAGED",
            )
            .first()
        )
        if not active_staging:
            return

        # Check age of most recent journal entry
        recent_jnl = (
            db.query(EngineeringGraphUpdateJournal)
            .filter(
                EngineeringGraphUpdateJournal.project_id == project_id,
                EngineeringGraphUpdateJournal.version_id == active_staging.id,
            )
            .order_by(EngineeringGraphUpdateJournal.id.desc())
            .first()
        )
        if recent_jnl and recent_jnl.created_at:
            created_tz = recent_jnl.created_at.replace(tzinfo=timezone.utc) if recent_jnl.created_at.tzinfo is None else recent_jnl.created_at
            now_tz = datetime.now(timezone.utc)
            delta = (now_tz - created_tz).total_seconds()
            if delta < cls.STAGING_LOCK_TIMEOUT_SECONDS:
                raise RuntimeError(
                    f"Concurrent graph update rejected: staging in progress for project {project_id} "
                    f"(version {active_staging.version_number}, stage '{recent_jnl.stage}', age {int(delta)}s)"
                )

    @classmethod
    def recover_interrupted_updates(cls, db: Session, project_id: int) -> int:
        """Finds any orphaned STAGED versions, cleans up orphaned staged entities, and marks them FAILED."""
        staged_versions = (
            db.query(EngineeringGraphVersion)
            .filter(
                EngineeringGraphVersion.project_id == project_id,
                EngineeringGraphVersion.status == "STAGED",
            )
            .all()
        )

        recovered_count = 0
        for ver in staged_versions:
            logger.warning(
                "Recovering interrupted staged graph version %s (v%d) for project %s",
                ver.id,
                ver.version_number,
                project_id,
            )
            # Purge orphaned staged nodes, edges, transitions
            db.query(EngineeringGraphNode).filter(EngineeringGraphNode.version_id == ver.id).delete()
            db.query(EngineeringGraphEdge).filter(EngineeringGraphEdge.version_id == ver.id).delete()
            db.query(EngineeringIdentityTransition).filter(EngineeringIdentityTransition.to_version_id == ver.id).delete()

            ver.status = "FAILED"
            ver.is_current = False
            cls.log_journal_entry(
                db=db,
                project_id=project_id,
                version_id=ver.id,
                stage="RECOVERED_AFTER_INTERRUPTION",
                error_message="Staging process interrupted before atomic activation. Orphaned staged entities purged.",
            )
            recovered_count += 1

        if recovered_count > 0:
            db.commit()

        return recovered_count

    @classmethod
    def validate_graph_consistency(
        cls,
        nodes: dict[str, GraphNode],
        edges: list[GraphEdge],
    ) -> list[str]:
        """Validates graph invariants prior to persistence and activation."""
        violations: list[str] = []
        node_cids = set(nodes.keys())

        # Check duplicate canonical IDs in node collection
        if len(node_cids) != len(nodes):
            violations.append("Duplicate canonical node IDs detected in nodes mapping.")

        # Check for corrupted nodes
        for cid, n in nodes.items():
            if not n.canonical_id:
                violations.append(f"Node has empty canonical_id: {n}")
            if not n.entity_type:
                violations.append(f"Node '{cid}' missing entity_type.")

        # Check edge endpoints: allow external/synthetic endpoints if documented in provenance
        for e in edges:
            if not e.source_canonical_id or not e.target_canonical_id:
                violations.append(f"Malformed edge missing endpoint: {e}")
            elif e.source_canonical_id not in node_cids and not e.source_canonical_id.startswith(f"{e.project_id}::::"):
                violations.append(f"Dangling edge source '{e.source_canonical_id}' not found in graph nodes.")
            elif (
                e.target_canonical_id not in node_cids
                and not e.target_canonical_id.startswith(f"{e.project_id}::::")
                and not (e.provenance and (e.provenance.get("is_external") or e.provenance.get("synthetic")))
                and not (e.analyzer_source and "unresolved" in e.analyzer_source.lower())
            ):
                violations.append(f"Dangling edge target '{e.target_canonical_id}' not found in graph nodes.")

        return violations

    @classmethod
    def execute_transactional_update(
        cls,
        db: Session,
        project_id: int,
        repo_root: str | Path,
        changed_files: list[str] | None = None,
        deleted_files: list[str] | None = None,
        commit_sha: str | None = None,
        force_full_rebuild: bool = False,
        findings: list[dict[str, Any]] | None = None,
        transactions: list[dict[str, Any]] | None = None,
        runtime_traces: list[dict[str, Any]] | None = None,
    ) -> tuple[dict[str, GraphNode], list[GraphEdge], EngineeringGraphVersion]:
        """Executes a fully transactional, staged graph update with crash-safety and continuity."""
        repo_path = Path(repo_root).resolve()

        # Step 0: Check concurrency lock and clean up stale stages
        cls.recover_interrupted_updates(db, project_id)
        cls.check_and_acquire_concurrency_lock(db, project_id)

        # Step 1: Load active graph and identify changes
        existing_nodes, existing_edges, active_ver = GraphStorageManager.load_active_graph(db, project_id)

        current_file_hashes = cls.compute_file_hashes(repo_path)

        if force_full_rebuild or not active_ver or not existing_nodes:
            is_full = True
            changed_set = set(current_file_hashes.keys())
            deleted_set = set()
        else:
            is_full = False
            if changed_files is None and deleted_files is None:
                changed_set, deleted_set, _ = cls.detect_changes_by_hash(repo_path, existing_nodes)
            else:
                changed_set = set(changed_files or [])
                deleted_set = set(deleted_files or [])

        # If zero file changes and not full rebuild, reuse active
        if not is_full and not changed_set and not deleted_set and active_ver:
            logger.info("Transactional updater: Zero file changes detected. Active graph reused.")
            return existing_nodes, existing_edges, active_ver

        # Step 2: Determine next version and create STAGING record
        latest = (
            db.query(EngineeringGraphVersion)
            .filter(EngineeringGraphVersion.project_id == project_id)
            .order_by(EngineeringGraphVersion.version_number.desc())
            .first()
        )
        next_ver = (latest.version_number + 1) if latest else 1

        staging_version = EngineeringGraphVersion(
            project_id=project_id,
            version_number=next_ver,
            commit_sha=commit_sha,
            is_current=False,
            status="STAGED",
            node_count=0,
            edge_count=0,
            metadata_json={
                "build_type": "FULL_REBUILD" if is_full else "INCREMENTAL",
                "changed_files": sorted(changed_set),
                "deleted_files": sorted(deleted_set),
                "changed_files_count": len(changed_set),
                "deleted_files_count": len(deleted_set),
            },
        )
        db.add(staging_version)
        db.flush()

        cls.log_journal_entry(
            db=db,
            project_id=project_id,
            version_id=staging_version.id,
            stage="STAGING",
            manifest={
                "version_number": next_ver,
                "is_full_rebuild": is_full,
                "changed_files_count": len(changed_set),
                "deleted_files_count": len(deleted_set),
            },
        )
        db.commit()

        try:
            # Step 3: Extraction
            cls.log_journal_entry(db, project_id, staging_version.id, "EXTRACTING")

            engine = GraphExtractionEngine(project_id, repo_path)
            nodes, edges = engine.extract_full_graph(
                findings=findings,
                transactions=transactions,
                runtime_traces=runtime_traces,
            )

            # Annotate nodes with file content hashes
            for cid, node in nodes.items():
                if node.file_path and node.file_path in current_file_hashes:
                    node.metadata["content_hash"] = current_file_hashes[node.file_path]

            # Step 4: Multi-Signal Identity Continuity Transitions
            transitions = IdentityContinuityEngine.compute_transitions(
                old_nodes=existing_nodes,
                new_nodes=nodes,
                repo_root=repo_path,
                from_version_id=active_ver.id if active_ver else None,
                to_version_id=staging_version.id,
            )

            # Step 5: Consistency & Integrity Check
            cls.log_journal_entry(db, project_id, staging_version.id, "INTEGRITY_CHECK")
            violations = cls.validate_graph_consistency(nodes, edges)
            if violations:
                raise ValueError(f"Integrity check failed: {'; '.join(violations)}")

            # Step 6: Persist Staged Entities
            cls.log_journal_entry(db, project_id, staging_version.id, "PERSISTING")

            db_nodes = [
                EngineeringGraphNode(
                    project_id=project_id,
                    version_id=staging_version.id,
                    canonical_id=n.canonical_id,
                    entity_type=n.entity_type,
                    name=n.name,
                    qualified_name=n.qualified_name,
                    file_path=n.file_path,
                    start_line=n.start_line,
                    end_line=n.end_line,
                    node_metadata=n.metadata,
                )
                for n in nodes.values()
            ]
            db.bulk_save_objects(db_nodes)

            db_edges = [
                EngineeringGraphEdge(
                    project_id=project_id,
                    version_id=staging_version.id,
                    source_canonical_id=e.source_canonical_id,
                    target_canonical_id=e.target_canonical_id,
                    rel_type=e.rel_type,
                    confidence=e.confidence,
                    evidence_location=e.evidence_location,
                    analyzer_source=e.analyzer_source,
                    provenance=e.provenance,
                )
                for e in edges
            ]
            db.bulk_save_objects(db_edges)

            db_transitions = [
                EngineeringIdentityTransition(
                    project_id=project_id,
                    from_version_id=t.from_version_id,
                    to_version_id=t.to_version_id or staging_version.id,
                    old_canonical_id=t.old_canonical_id,
                    new_canonical_id=t.new_canonical_id,
                    transition_type=t.transition_type,
                    confidence=t.confidence,
                    evidence=t.evidence,
                )
                for t in transitions
            ]
            db.bulk_save_objects(db_transitions)

            staging_version.node_count = len(nodes)
            staging_version.edge_count = len(edges)

            # Step 7: Atomic Activation within Transaction
            # Deactivate previous active version(s)
            db.query(EngineeringGraphVersion).filter(
                EngineeringGraphVersion.project_id == project_id,
                EngineeringGraphVersion.id != staging_version.id,
                EngineeringGraphVersion.is_current == True,
            ).update({"is_current": False, "status": "SUPERSEDED"})

            staging_version.is_current = True
            staging_version.status = "ACTIVE"

            cls.log_journal_entry(
                db=db,
                project_id=project_id,
                version_id=staging_version.id,
                stage="ACTIVATED",
                manifest={
                    "total_nodes": len(nodes),
                    "total_edges": len(edges),
                    "transitions_count": len(transitions),
                },
            )

            db.commit()
            db.refresh(staging_version)
            logger.info("Successfully activated knowledge graph version %d for project %s", staging_version.version_number, project_id)
            return nodes, edges, staging_version

        except Exception as exc:
            db.rollback()
            logger.exception("Transactional graph update failed for project %s: %s", project_id, exc)
            try:
                # Mark failed in separate sub-transaction and clean up orphaned staged entities
                db.query(EngineeringGraphNode).filter(EngineeringGraphNode.version_id == staging_version.id).delete()
                db.query(EngineeringGraphEdge).filter(EngineeringGraphEdge.version_id == staging_version.id).delete()
                db.query(EngineeringIdentityTransition).filter(EngineeringIdentityTransition.to_version_id == staging_version.id).delete()

                staging_version.status = "FAILED"
                staging_version.is_current = False
                cls.log_journal_entry(
                    db=db,
                    project_id=project_id,
                    version_id=staging_version.id,
                    stage="FAILED",
                    error_message=str(exc),
                )
                db.commit()
            except Exception:
                db.rollback()
            raise
