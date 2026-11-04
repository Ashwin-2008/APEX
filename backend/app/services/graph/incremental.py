"""Incremental Graph Update Engine for APEX 2.0 (Phase 3.1).

Provides fast, selective graph re-extraction when files change, avoiding costly
full-repository re-indexes while maintaining strict graph consistency and atomic versioning.
Delegates to TransactionalGraphUpdater for crash resilience, staged versioning, and journal logging.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.services.graph.models import GraphEdge, GraphNode

logger = logging.getLogger(__name__)


class IncrementalGraphUpdater:
    """Updates only affected slices of the engineering knowledge graph with transactional safety."""

    @classmethod
    def update_graph(
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
    ) -> tuple[dict[str, GraphNode], list[GraphEdge], Any]:
        """Performs staged, transactional incremental or full graph update."""
        from app.services.graph.transactional_updater import TransactionalGraphUpdater

        return TransactionalGraphUpdater.execute_transactional_update(
            db=db,
            project_id=project_id,
            repo_root=repo_root,
            changed_files=changed_files,
            deleted_files=deleted_files,
            commit_sha=commit_sha,
            force_full_rebuild=force_full_rebuild,
            findings=findings,
            transactions=transactions,
            runtime_traces=runtime_traces,
        )
