"""Continuous Live Project Monitoring & Background Job Orchestration Service."""
from __future__ import annotations

import concurrent.futures
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.entities import ProjectReview, ReviewedProject
from app.services.git_service import get_branch, get_current_sha, is_git_repository
from app.services.notification_service import create_notification, record_activity_event
from app.services.project_monitor import (
    IGNORED,
    changed_analyzers,
    event_bus,
    snapshot,
    start_watcher,
    stop_watcher,
)
from app.services.project_review_persistence import persist_analysis
from app.services.project_review_service import analyze_project

# Background job executor for asynchronous repository analysis
_ANALYSIS_EXECUTOR = concurrent.futures.ThreadPoolExecutor(max_workers=4, thread_name_prefix="apex-analyzer")
_ACTIVE_JOBS: dict[str, dict[str, Any]] = {}
_ACTIVE_WATCHERS: dict[int, dict[str, Any]] = {}
_WATCHER_LOCK = threading.Lock()


def get_project_monitoring_status(project_id: int) -> dict[str, Any]:
    with _WATCHER_LOCK:
        watcher_info = _ACTIVE_WATCHERS.get(project_id)
        if watcher_info and watcher_info.get("active"):
            return {
                "project_id": project_id,
                "status": "active",
                "started_at": watcher_info.get("started_at"),
                "last_change_detected": watcher_info.get("last_change_detected"),
            }
        return {
            "project_id": project_id,
            "status": "paused",
            "started_at": None,
            "last_change_detected": None,
        }


def queue_background_analysis(
    session_factory: Callable[[], Session],
    project_id: int,
    repository_path: str,
    user_id: int,
    affected_files: list[str] | None = None,
    affected_analyzers: list[str] | None = None,
) -> str:
    """Submit an asynchronous background analysis job for a project."""
    job_id = f"job_{uuid.uuid4().hex[:12]}"
    now_iso = datetime.now(timezone.utc).isoformat()
    _ACTIVE_JOBS[job_id] = {
        "job_id": job_id,
        "project_id": project_id,
        "user_id": user_id,
        "status": "pending",
        "submitted_at": now_iso,
        "started_at": None,
        "completed_at": None,
        "affected_files": affected_files or [],
        "error": None,
    }

    def _worker():
        _ACTIVE_JOBS[job_id]["status"] = "running"
        _ACTIVE_JOBS[job_id]["started_at"] = datetime.now(timezone.utc).isoformat()

        event_bus.emit(
            project_id,
            {
                "type": "analysis.started",
                "job_id": job_id,
                "project_id": project_id,
                "files": affected_files or [],
                "analyzers": affected_analyzers or [],
            },
        )

        with session_factory() as session:
            record_activity_event(
                session,
                project_id=project_id,
                event_type="analysis.started",
                title="Analysis Started",
                description=f"Automated incremental scan started for {len(affected_files or [])} changed file(s).",
                metadata={"job_id": job_id, "files": affected_files or []},
            )

        try:
            analysis = analyze_project(repository_path)
            git_sha = get_current_sha(repository_path) if is_git_repository(repository_path) else None

            with session_factory() as session:
                persisted = persist_analysis(
                    session,
                    analysis,
                    affected_files=affected_files,
                    affected_analyzers=affected_analyzers,
                    related_commit=git_sha,
                )
                proj = session.get(ReviewedProject, project_id)
                if proj:
                    proj.last_analyzed_at = datetime.now(timezone.utc)
                    proj.current_commit_sha = git_sha
                    session.commit()

                # Generate notification for any critical findings
                crit_count = sum(1 for f in persisted.get("findings", []) if f.get("severity") == "critical")
                if crit_count > 0:
                    create_notification(
                        session,
                        user_id=user_id,
                        project_id=project_id,
                        notif_type="finding.critical",
                        title=f"{crit_count} Critical Vulnerability Finding(s) Detected",
                        message=f"A new analysis run identified {crit_count} critical finding(s) requiring immediate attention.",
                        data={"review_id": persisted["id"], "critical_count": crit_count},
                    )

                record_activity_event(
                    session,
                    project_id=project_id,
                    event_type="analysis.completed",
                    title="Analysis Completed",
                    description=f"Review #{persisted['review_number']} generated with {len(persisted.get('findings', []))} total finding(s).",
                    metadata={"review_id": persisted["id"], "review_number": persisted["review_number"]},
                )

            _ACTIVE_JOBS[job_id]["status"] = "completed"
            _ACTIVE_JOBS[job_id]["completed_at"] = datetime.now(timezone.utc).isoformat()

            event_bus.emit(
                project_id,
                {
                    "type": "analysis.completed",
                    "job_id": job_id,
                    "project_id": project_id,
                    "review_id": persisted["id"],
                    "review_number": persisted["review_number"],
                    "files": affected_files or [],
                    "findings_count": len(persisted.get("findings", [])),
                },
            )

            # Emit finding events
            for finding in persisted.get("findings", []):
                event_bus.emit(
                    project_id,
                    {
                        "type": "finding.created" if finding.get("status") == "NEW" else "finding.updated",
                        "project_id": project_id,
                        "finding": finding,
                        "related_commit": git_sha,
                    },
                )

            # Emit finding.resolved events
            for resolved in persisted.get("resolved_events", []):
                event_bus.emit(
                    project_id,
                    {
                        "type": "finding.resolved",
                        "project_id": project_id,
                        **resolved,
                        "related_commit": git_sha,
                    },
                )

        except Exception as exc:
            _ACTIVE_JOBS[job_id]["status"] = "failed"
            _ACTIVE_JOBS[job_id]["error"] = str(exc)
            _ACTIVE_JOBS[job_id]["completed_at"] = datetime.now(timezone.utc).isoformat()

            event_bus.emit(
                project_id,
                {
                    "type": "analysis.failed",
                    "job_id": job_id,
                    "project_id": project_id,
                    "message": f"Analysis failed: {str(exc)}",
                },
            )

            with session_factory() as session:
                record_activity_event(
                    session,
                    project_id=project_id,
                    event_type="analysis.failed",
                    title="Analysis Failed",
                    description=f"Analysis worker encountered an error: {str(exc)[:200]}",
                    metadata={"job_id": job_id, "error": str(exc)},
                )
                create_notification(
                    session,
                    user_id=user_id,
                    project_id=project_id,
                    notif_type="analysis.failed",
                    title="Project Analysis Failed",
                    message=f"The automated scan encountered an issue: {str(exc)[:160]}",
                    data={"job_id": job_id},
                )

    _ANALYSIS_EXECUTOR.submit(_worker)
    return job_id


def start_project_monitoring(
    session_factory: Callable[[], Session],
    project_id: int,
    repository_path: str,
    user_id: int,
) -> bool:
    """Start an independent live file-system watcher for a project."""
    with _WATCHER_LOCK:
        if project_id in _ACTIVE_WATCHERS and _ACTIVE_WATCHERS[project_id].get("active"):
            return True

        def _on_change(event: dict[str, Any]):
            event_type = event.get("type")
            if event_type == "project.changed":
                changed_files = event.get("files", [])
                analyzers = event.get("analyzers", [])
                with _WATCHER_LOCK:
                    if project_id in _ACTIVE_WATCHERS:
                        _ACTIVE_WATCHERS[project_id]["last_change_detected"] = datetime.now(timezone.utc).isoformat()

                # Trigger queued non-blocking analysis
                queue_background_analysis(
                    session_factory=session_factory,
                    project_id=project_id,
                    repository_path=repository_path,
                    user_id=user_id,
                    affected_files=changed_files,
                    affected_analyzers=analyzers,
                )

        git_sha = get_current_sha(repository_path) if is_git_repository(repository_path) else None
        stop_event = start_watcher(project_id, repository_path, _on_change, previous_sha=git_sha)

        _ACTIVE_WATCHERS[project_id] = {
            "active": True,
            "stop_event": stop_event,
            "repository_path": repository_path,
            "user_id": user_id,
            "started_at": datetime.now(timezone.utc).isoformat(),
            "last_change_detected": None,
        }

    with session_factory() as session:
        proj = session.get(ReviewedProject, project_id)
        if proj:
            proj.monitoring_status = "active"
            session.commit()
        record_activity_event(
            session,
            project_id=project_id,
            event_type="monitoring.started",
            title="Monitoring Activated",
            description="Real-time file-system watching and Git commit tracking active.",
        )
    return True


def stop_project_monitoring(session_factory: Callable[[], Session], project_id: int) -> bool:
    """Pause or stop live monitoring for a specific project."""
    with _WATCHER_LOCK:
        watcher = _ACTIVE_WATCHERS.pop(project_id, None)
        if watcher:
            stop_watcher(project_id)

    with session_factory() as session:
        proj = session.get(ReviewedProject, project_id)
        if proj:
            proj.monitoring_status = "paused"
            session.commit()
        record_activity_event(
            session,
            project_id=project_id,
            event_type="monitoring.stopped",
            title="Monitoring Paused",
            description="Real-time file watching paused.",
        )
    return True

