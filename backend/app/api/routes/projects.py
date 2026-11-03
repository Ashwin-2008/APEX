"""Multi-Tenant Project Management & Engineering Intelligence API."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.dependencies import get_authorized_project, get_current_user, get_db
from app.models.entities import ProjectFinding, ProjectReview, ReviewedProject, User
from app.services.analyzers.dynamic_analyzer import run_dynamic_analysis
from app.services.analyzers.engine import run_comprehensive_analysis
from app.services.finding_service import (
    serialize_finding,
    suppress_finding,
    unsuppress_finding,
)
from app.services.git_service import get_branch, get_current_sha, is_git_repository
from app.services.monitoring_service import (
    get_project_monitoring_status,
    queue_background_analysis,
    start_project_monitoring,
    stop_project_monitoring,
)
from app.services.notification_service import (
    create_notification,
    list_project_activity,
    record_activity_event,
)
from app.services.project_review_persistence import persist_analysis, serialize_review
from app.services.project_review_service import analyze_project

router = APIRouter(prefix="/projects")


class ProjectConnectRequest(BaseModel):
    name: str | None = None
    source_type: str = Field(..., pattern="^(local|github)$")
    path: str | None = None
    repository_url: str | None = None
    branch: str | None = None
    enable_monitoring: bool = True
    enabled_analyzers: list[str] | None = None


class ProjectUpdateRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    settings: dict[str, Any] | None = None


class FindingSuppressRequest(BaseModel):
    reason: str = Field(..., min_length=5)
    suppression_type: str = Field("false_positive", pattern="^(false_positive|wont_fix|accepted_risk)$")


class DynamicAnalysisRequest(BaseModel):
    command: list[str] | None = None
    timeout_seconds: int = 30


def _safe_resolve_repository(request: ProjectConnectRequest) -> str:
    """Validate repository boundaries, safe git cloning, and path traversal protection."""
    raw_path = request.path.strip().strip('"').strip("'") if request.path else None

    if request.source_type == "github":
        parsed = urlparse(request.repository_url or "")
        parts = [p for p in parsed.path.strip("/").split("/") if p]
        if parsed.scheme != "https" or parsed.hostname != "github.com" or len(parts) != 2 or any(p in {".", ".."} for p in parts):
            raise HTTPException(422, "Only valid HTTPS GitHub repository URLs (https://github.com/owner/repo) are supported.")
        slug = f"{parts[0]}-{parts[1].removesuffix('.git')}"
        target = (Path("data/repositories") / slug).resolve()
        base = Path("data/repositories").resolve()
        if base not in target.parents:
            raise HTTPException(422, "Path traversal detected; repository path outside approved boundary.")
        target.parent.mkdir(parents=True, exist_ok=True)

        if not target.exists():
            cmd = ["git", "clone"]
            if request.branch:
                cmd.extend(["--branch", request.branch])
            cmd.extend([request.repository_url, str(target)])
            try:
                subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=180)
            except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as err:
                detail = getattr(err, "stderr", "") or "Git clone failed"
                raise HTTPException(502, f"Could not clone repository: {detail[:240]}") from err
        else:
            try:
                subprocess.run(["git", "-C", str(target), "fetch", "--prune", "origin"], check=True, capture_output=True, text=True, timeout=120)
                ref = f"origin/{request.branch}" if request.branch else "origin/HEAD"
                subprocess.run(["git", "-C", str(target), "reset", "--hard", ref], check=True, capture_output=True, text=True, timeout=30)
            except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as err:
                detail = getattr(err, "stderr", "") or "Git refresh failed"
                raise HTTPException(502, f"Could not refresh repository: {detail[:240]}") from err
        return str(target)

    if not raw_path:
        raise HTTPException(422, "A valid local repository directory is required.")

    path_obj = Path(raw_path).expanduser().resolve()
    if not path_obj.is_dir():
        raise HTTPException(422, f"Directory does not exist or is not accessible: {raw_path}")
    return str(path_obj)


@router.get("", summary="List all projects owned by the authenticated user")
def list_user_projects(
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
):
    projects = session.scalars(
        select(ReviewedProject)
        .where(ReviewedProject.owner_id == current_user.id, ReviewedProject.is_archived == False)
        .order_by(ReviewedProject.updated_at.desc())
    ).all()

    result = []
    for p in projects:
        # Compute summary metrics for each project
        rev_count = session.scalar(
            select(func.count(ProjectReview.id)).where(ProjectReview.project_id == p.id)
        ) or 0
        latest_rev = session.scalar(
            select(ProjectReview).where(ProjectReview.project_id == p.id).order_by(ProjectReview.review_number.desc())
        )
        findings_query = (
            select(ProjectFinding)
            .join(ProjectReview, ProjectFinding.review_id == ProjectReview.id)
            .where(ProjectReview.project_id == p.id, ProjectFinding.status.in_(["open", "NEW", "ACTIVE"]))
        )
        active_findings = session.scalars(findings_query).all()
        crit_count = sum(1 for f in active_findings if f.severity == "critical")
        high_count = sum(1 for f in active_findings if f.severity == "high")

        monitoring_info = get_project_monitoring_status(p.id)

        result.append({
            "id": p.id,
            "name": p.name,
            "repository_path": p.repository_path,
            "source_type": p.source_type,
            "repository_url": p.repository_url,
            "branch": p.branch,
            "current_commit_sha": p.current_commit_sha,
            "monitoring_status": monitoring_info["status"] if monitoring_info["status"] == "active" else p.monitoring_status,
            "last_analyzed_at": p.last_analyzed_at.isoformat() if p.last_analyzed_at else None,
            "created_at": p.created_at.isoformat() if p.created_at else None,
            "description": p.description,
            "summary": {
                "reviews_count": rev_count,
                "active_findings_count": len(active_findings),
                "critical_findings_count": crit_count,
                "high_findings_count": high_count,
                "latest_coverage": (p.analysis_coverage or {}).get("coverage_percentage", 85.0),
            },
        })
    return result


@router.post("", status_code=status.HTTP_201_CREATED, summary="Connect and initialize a new project")
def connect_project(
    body: ProjectConnectRequest,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
    app_request: Request = None,
):
    repo_path = _safe_resolve_repository(body)
    display_name = body.name.strip() if body.name else Path(repo_path).name

    # Check Git details
    is_git = is_git_repository(repo_path)
    git_sha = get_current_sha(repo_path) if is_git else None
    git_branch = get_branch(repo_path) if is_git else body.branch

    # Run comprehensive initial analysis
    comp_analysis = run_comprehensive_analysis(repo_path, enabled_analyzers=body.enabled_analyzers)
    # Also run base analyze_project for backward-compatible models/predictions
    base_analysis = analyze_project(repo_path)

    # Check if project already connected by this user
    existing = session.scalar(
        select(ReviewedProject).where(
            ReviewedProject.owner_id == current_user.id,
            ReviewedProject.repository_path == repo_path,
        )
    )
    if existing:
        project = existing
        project.name = display_name
        project.branch = git_branch
        project.current_commit_sha = git_sha
        project.source_type = body.source_type
        project.repository_url = body.repository_url
        project.analysis_coverage = comp_analysis["coverage"]
    else:
        project = ReviewedProject(
            owner_id=current_user.id,
            name=display_name,
            repository_path=repo_path,
            source_type=body.source_type,
            repository_url=body.repository_url,
            branch=git_branch,
            current_commit_sha=git_sha,
            monitoring_status="active" if body.enable_monitoring else "paused",
            analysis_coverage=comp_analysis["coverage"],
            settings={"enabled_analyzers": body.enabled_analyzers or []},
        )
        session.add(project)
    session.commit()
    session.refresh(project)

    # Persist review
    persisted = persist_analysis(session, base_analysis, related_commit=git_sha)
    project.last_analyzed_at = func.now()
    session.commit()

    # Record activity & initial notification
    record_activity_event(
        session,
        project_id=project.id,
        event_type="project.connected",
        title="Project Connected",
        description=f"Project '{display_name}' connected successfully from {body.source_type} source.",
        metadata={"path": repo_path, "commit": git_sha},
    )
    create_notification(
        session,
        user_id=current_user.id,
        project_id=project.id,
        notif_type="project.connected",
        title=f"Project '{display_name}' Connected",
        message=f"Initial analysis completed with {len(persisted.get('findings', []))} findings and {comp_analysis['coverage']['coverage_percentage']}% coverage.",
        data={"project_id": project.id, "review_id": persisted["id"]},
    )

    # Start live monitoring watcher if requested
    if body.enable_monitoring:
        session_factory = app_request.app.state.SessionLocal
        start_project_monitoring(session_factory, project.id, repo_path, current_user.id)

    return {
        "project": {
            "id": project.id,
            "name": project.name,
            "repository_path": project.repository_path,
            "source_type": project.source_type,
            "branch": project.branch,
            "current_commit_sha": project.current_commit_sha,
            "monitoring_status": project.monitoring_status,
            "last_analyzed_at": project.last_analyzed_at.isoformat() if project.last_analyzed_at else None,
            "coverage": comp_analysis["coverage"],
        },
        "review_id": persisted["id"],
        "review_number": persisted["review_number"],
        "analysis": base_analysis,
        "coverage": comp_analysis["coverage"],
        "persisted_review": persisted,
    }


@router.get("/{project_id}", summary="Get project configuration and telemetry")
def get_project(project: ReviewedProject = Depends(get_authorized_project)):
    monitoring_info = get_project_monitoring_status(project.id)
    return {
        "id": project.id,
        "name": project.name,
        "repository_path": project.repository_path,
        "source_type": project.source_type,
        "repository_url": project.repository_url,
        "branch": project.branch,
        "current_commit_sha": project.current_commit_sha,
        "monitoring_status": monitoring_info["status"] if monitoring_info["status"] == "active" else project.monitoring_status,
        "last_analyzed_at": project.last_analyzed_at.isoformat() if project.last_analyzed_at else None,
        "created_at": project.created_at.isoformat() if project.created_at else None,
        "description": project.description,
        "coverage": project.analysis_coverage,
        "settings": project.settings,
    }


@router.patch("/{project_id}", summary="Update project settings or display name")
def update_project(
    body: ProjectUpdateRequest,
    project: ReviewedProject = Depends(get_authorized_project),
    session: Session = Depends(get_db),
):
    if body.name is not None:
        project.name = body.name.strip() or project.name
    if body.description is not None:
        project.description = body.description.strip()
    if body.settings is not None:
        merged = dict(project.settings or {})
        merged.update(body.settings)
        project.settings = merged
    session.commit()
    session.refresh(project)
    return {"id": project.id, "name": project.name, "settings": project.settings}


@router.delete("/{project_id}", summary="Disconnect and remove a project and its records")
def delete_project(
    project: ReviewedProject = Depends(get_authorized_project),
    session: Session = Depends(get_db),
    app_request: Request = None,
):
    session_factory = app_request.app.state.SessionLocal
    stop_project_monitoring(session_factory, project.id)
    session.delete(project)
    session.commit()
    return {"status": "ok", "message": f"Project '{project.name}' successfully removed."}


@router.post("/{project_id}/analyze", summary="Trigger manual comprehensive analysis")
def analyze_project_endpoint(
    project: ReviewedProject = Depends(get_authorized_project),
    session: Session = Depends(get_db),
):
    comp_analysis = run_comprehensive_analysis(project.repository_path)
    base_analysis = analyze_project(project.repository_path)
    git_sha = get_current_sha(project.repository_path) if is_git_repository(project.repository_path) else None

    persisted = persist_analysis(session, base_analysis, related_commit=git_sha)
    project.analysis_coverage = comp_analysis["coverage"]
    project.last_analyzed_at = func.now()
    session.commit()

    record_activity_event(
        session,
        project_id=project.id,
        event_type="analysis.manual",
        title="Manual Analysis Completed",
        description=f"Manual scan completed. Review #{persisted['review_number']} generated.",
        metadata={"review_id": persisted["id"]},
    )
    return {
        "project_id": project.id,
        "review_id": persisted["id"],
        "review_number": persisted["review_number"],
        "coverage": comp_analysis["coverage"],
        "findings_count": len(persisted.get("findings", [])),
    }


@router.post("/{project_id}/monitoring/start", summary="Start live file-system monitoring")
def start_monitoring_endpoint(
    project: ReviewedProject = Depends(get_authorized_project),
    current_user: User = Depends(get_current_user),
    app_request: Request = None,
):
    session_factory = app_request.app.state.SessionLocal
    start_project_monitoring(session_factory, project.id, project.repository_path, current_user.id)
    return {"project_id": project.id, "monitoring_status": "active"}


@router.post("/{project_id}/monitoring/stop", summary="Pause live monitoring")
def stop_monitoring_endpoint(
    project: ReviewedProject = Depends(get_authorized_project),
    app_request: Request = None,
):
    session_factory = app_request.app.state.SessionLocal
    stop_project_monitoring(session_factory, project.id)
    return {"project_id": project.id, "monitoring_status": "paused"}


@router.get("/{project_id}/coverage", summary="Get detailed analysis coverage transparency report")
def get_project_coverage(
    project: ReviewedProject = Depends(get_authorized_project),
):
    if project.analysis_coverage:
        return project.analysis_coverage
    # If not yet cached, compute it
    comp = run_comprehensive_analysis(project.repository_path)
    return comp["coverage"]


@router.get("/{project_id}/findings", summary="List findings for this project with filters")
def get_project_findings(
    status_filter: str | None = None,
    severity: str | None = None,
    category: str | None = None,
    suppressed: bool | None = False,
    project: ReviewedProject = Depends(get_authorized_project),
    session: Session = Depends(get_db),
):
    query = (
        select(ProjectFinding)
        .join(ProjectReview, ProjectFinding.review_id == ProjectReview.id)
        .where(ProjectReview.project_id == project.id)
    )
    if suppressed is not None:
        query = query.where(ProjectFinding.suppressed == suppressed)
    if status_filter:
        query = query.where(ProjectFinding.status == status_filter)
    if severity:
        query = query.where(ProjectFinding.severity == severity)
    if category:
        query = query.where(ProjectFinding.category == category)
    query = query.order_by(ProjectFinding.detected_at.desc())

    findings = session.scalars(query).all()
    return [serialize_finding(f) for f in findings]


@router.post("/{project_id}/findings/{finding_id}/suppress", summary="Mark finding as false positive or suppressed")
def suppress_finding_endpoint(
    finding_id: int,
    body: FindingSuppressRequest,
    project: ReviewedProject = Depends(get_authorized_project),
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
):
    finding = session.get(ProjectFinding, finding_id)
    if not finding:
        raise HTTPException(404, "Finding not found")
    # Verify finding belongs to this project
    review = session.get(ProjectReview, finding.review_id)
    if not review or review.project_id != project.id:
        raise HTTPException(404, "Finding does not belong to this project")

    updated = suppress_finding(session, finding_id, current_user.id, body.reason, body.suppression_type)
    record_activity_event(
        session,
        project_id=project.id,
        event_type="finding.suppressed",
        title="Finding Suppressed",
        description=f"Finding '{finding.title or finding.fingerprint[:8]}' suppressed as {body.suppression_type}: {body.reason}",
        metadata={"finding_id": finding_id, "reason": body.reason},
    )
    return serialize_finding(updated)


@router.post("/{project_id}/findings/{finding_id}/reopen", summary="Reopen a previously suppressed finding")
def reopen_finding_endpoint(
    finding_id: int,
    project: ReviewedProject = Depends(get_authorized_project),
    session: Session = Depends(get_db),
):
    finding = session.get(ProjectFinding, finding_id)
    if not finding:
        raise HTTPException(404, "Finding not found")
    review = session.get(ProjectReview, finding.review_id)
    if not review or review.project_id != project.id:
        raise HTTPException(404, "Finding does not belong to this project")

    updated = unsuppress_finding(session, finding_id)
    record_activity_event(
        session,
        project_id=project.id,
        event_type="finding.reopened",
        title="Finding Reopened",
        description=f"Suppressed finding '{finding.title or finding.fingerprint[:8]}' was reopened.",
        metadata={"finding_id": finding_id},
    )
    return serialize_finding(updated)


@router.get("/{project_id}/activity", summary="Get live activity timeline for this project")
def get_project_activity(
    project: ReviewedProject = Depends(get_authorized_project),
    session: Session = Depends(get_db),
):
    return list_project_activity(session, project.id)


@router.post("/{project_id}/dynamic-analysis", summary="Run isolated sandboxed dynamic test execution")
def run_dynamic_analysis_endpoint(
    body: DynamicAnalysisRequest,
    project: ReviewedProject = Depends(get_authorized_project),
):
    output = run_dynamic_analysis(
        project.repository_path,
        enabled=True,
        command=body.command,
        timeout_seconds=body.timeout_seconds,
    )
    return output.to_dict()

