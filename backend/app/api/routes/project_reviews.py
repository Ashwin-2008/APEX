from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
import subprocess
from pathlib import Path
from pydantic import BaseModel, Field
from urllib.parse import urlparse

from app.services.project_review_service import analyze_project
from app.services.project_review_persistence import compare_reviews, failure_history, persist_analysis, project_history, serialize_review
from app.services.project_evolution_service import evolution, trajectory, requirements, research_observations
from app.services.mistiq_apr_research_service import (
    research_dataset,
    research_evaluation,
    research_prediction,
    research_status,
)
from app.services.project_monitor import event_bus, start_watcher, stop_watcher
from app.services.git_service import get_current_sha, get_branch, is_git_repository
from app.models.entities import ProjectReview, ReviewedProject
from sqlalchemy import select

router = APIRouter(prefix="/project-reviews")


class ReviewRequest(BaseModel):
    project_path: str = Field(..., min_length=1, description="Path to a repository visible to the API worker")

class ConnectRequest(BaseModel):
    source_type: str = Field(..., pattern="^(local|github)$")
    path: str | None = None
    repository_url: str | None = None
    branch: str | None = None


@router.post("/analyze", summary="Run an evidence-first project review")
def analyze(request: ReviewRequest, app_request: Request):
    try:
        analysis = analyze_project(request.project_path)
        with app_request.app.state.SessionLocal() as session:
            persisted = persist_analysis(session, analysis)
        analysis["persistence"] = {"project_id": persisted["project_id"], "review_id": persisted["id"], "review_number": persisted["review_number"]}
        return analysis
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/taxonomy", summary="List supported engineering failure categories")
def taxonomy():
    from app.services.project_review_service import FAILURE_CATEGORIES
    return {"categories": FAILURE_CATEGORIES}

@router.post("/connect")
def connect(request: ConnectRequest, app_request: Request):
    path = request.path.strip().strip('"').strip("'") if request.path else None
    if request.source_type == "github":
        parsed = urlparse(request.repository_url or "")
        parts = [part for part in parsed.path.strip("/").split("/") if part]
        if parsed.scheme != "https" or parsed.hostname != "github.com" or len(parts) != 2 or any(part in {".", ".."} for part in parts):
            raise HTTPException(422, "Only public HTTPS GitHub repository URLs are supported.")
        slug = [parts[0], parts[1].removesuffix(".git")]
        target = (Path("data/repositories") / "-".join(slug)).resolve(); base = Path("data/repositories").resolve()
        if base not in target.parents: raise HTTPException(422, "Unsafe repository path.")
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            command = ["git", "clone"]
            if request.branch:
                command.extend(["--branch", request.branch])
            command.extend([request.repository_url, str(target)])
            try:
                subprocess.run(command, check=True, capture_output=True, text=True, timeout=180)
            except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
                detail = getattr(error, "stderr", "") or "clone failed"
                raise HTTPException(502, f"Public GitHub repository could not be cloned: {detail.strip()[:240]}") from error
        else:
            try:
                subprocess.run(["git", "-C", str(target), "remote", "set-url", "origin", request.repository_url], check=True, capture_output=True, text=True, timeout=30)
                subprocess.run(["git", "-C", str(target), "fetch", "--prune", "origin"], check=True, capture_output=True, text=True, timeout=180)
                remote_ref = f"origin/{request.branch}" if request.branch else "origin/HEAD"
                subprocess.run(["git", "-C", str(target), "reset", "--hard", remote_ref], check=True, capture_output=True, text=True, timeout=30)
            except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
                detail = getattr(error, "stderr", "") or "refresh failed"
                raise HTTPException(502, f"Public GitHub repository could not be refreshed: {detail.strip()[:240]}") from error
        path = str(target)
    if not path or not Path(path).is_dir(): raise HTTPException(422, "A valid local project directory is required.")
    try:
        analysis = analyze_project(path)
        # Detect Git SHA and branch information
        git_sha = get_current_sha(path) if is_git_repository(path) else None
        git_branch = get_branch(path) if is_git_repository(path) else request.branch
        
        with app_request.app.state.SessionLocal() as session:
            persisted = persist_analysis(session, analysis, related_commit=git_sha)
            project = session.get(ReviewedProject, persisted["project_id"])
            project.source_type = request.source_type
            project.repository_url = request.repository_url
            project.branch = git_branch
            project.current_commit_sha = git_sha
            project.monitoring_status = "active"
            session.commit()
        project_id = persisted["project_id"]
        
        # Emit initial project.changed and analysis events for the first connection
        initial_files = []
        initial_analyzers = ["source", "api", "authentication", "testing", "requirements", "coverage", "dependency", "security", "deployment", "configuration"]
        event_bus.emit(project_id, {"type": "project.changed", "project_id": project_id, "files": initial_files, "analyzers": initial_analyzers, "current_commit_sha": git_sha, "branch": git_branch})
        event_bus.emit(project_id, {"type": "analysis.started", "project_id": project_id, "files": initial_files, "analyzers": initial_analyzers, "current_commit_sha": git_sha, "branch": git_branch})
        event_bus.emit(project_id, {"type": "analysis.completed", "project_id": project_id, "review_id": persisted["id"], "review_number": persisted["review_number"], "files": initial_files, "analyzers": initial_analyzers, "current_commit_sha": git_sha, "branch": git_branch})
        
        # Emit finding events for initial findings
        for finding in persisted.get("findings", []):
            event_bus.emit(project_id, {"type": "finding.created", "project_id": project_id, "finding": finding, "related_commit": git_sha})
        
        # Emit requirement, DNA, and prediction events for initial analysis
        if analysis.get("requirements"):
            event_bus.emit(project_id, {"type": "requirement.updated", "project_id": project_id, "requirements": analysis.get("requirements", []), "review_id": persisted["id"], "related_commit": git_sha})
        if analysis.get("failure_dna"):
            event_bus.emit(project_id, {"type": "dna.updated", "project_id": project_id, "failure_dna": analysis["failure_dna"], "review_id": persisted["id"], "related_commit": git_sha})
        if analysis.get("next_failure_predictions"):
            event_bus.emit(project_id, {"type": "prediction.updated", "project_id": project_id, "predictions": analysis["next_failure_predictions"], "review_id": persisted["id"], "related_commit": git_sha})
        
        last_git_sha = git_sha

        def on_change(event):
            nonlocal last_git_sha
            event_type = event.get("type")
            print(f"[E2E] CALLBACK_RECEIVED project={project_id} type={event_type}", flush=True)
            if event_type == "monitoring.status":
                event_bus.emit(project_id, event)
                return
            # Emit project.changed event first for filesystem/Git changes
            if event_type == "project.changed":
                # Extract Git SHA information if available
                current_commit_sha = event.get("current_commit_sha")
                previous_commit_sha = event.get("previous_commit_sha")
                branch = event.get("branch")
                commit_info = event.get("commit_info")
                
                # Emit the project.changed event
                event_bus.emit(project_id, event)
                
                # Update the project's Git SHA in the database if this is a Git transition
                if current_commit_sha and current_commit_sha != last_git_sha:
                    with app_request.app.state.SessionLocal() as session:
                        project = session.get(ReviewedProject, project_id)
                        if project:
                            project.current_commit_sha = current_commit_sha
                            project.branch = branch
                            session.commit()
                    last_git_sha = current_commit_sha
                
                # Emit analysis.started
                print(f"[E2E] ANALYSIS_STARTED project={project_id}", flush=True)
                event_bus.emit(project_id, {"type": "analysis.started", "project_id": project_id, "files": event.get("files", []), "analyzers": event.get("analyzers", []), "current_commit_sha": current_commit_sha, "previous_commit_sha": previous_commit_sha, "branch": branch})
                
                try:
                    updated = analyze_project(path)
                    print(f"[E2E] ANALYSIS_COMPLETED project={project_id}", flush=True)
                    # Pass the current commit SHA to the persistence layer
                    current_sha_for_analysis = current_commit_sha or last_git_sha
                    with app_request.app.state.SessionLocal() as session:
                        print(f"[E2E] PERSISTENCE_STARTED project={project_id}", flush=True)
                        saved = persist_analysis(session, updated, affected_files=event.get("files", []), affected_analyzers=event.get("analyzers", []), related_commit=current_sha_for_analysis)
                    print(f"[E2E] REVIEW_PERSISTED project={project_id} review={saved['id']}", flush=True)
                    
                    # Emit analysis.completed
                    event_bus.emit(project_id, {"type": "analysis.completed", "project_id": project_id, "review_id": saved["id"], "review_number": saved["review_number"], "files": event.get("files", []), "analyzers": event.get("analyzers", []), "current_commit_sha": current_commit_sha, "previous_commit_sha": previous_commit_sha})
                    
                    # Emit finding events
                    for finding in saved.get("findings", []): 
                        finding_status = finding.get("status", "NEW")
                        if finding_status == "ACTIVE":
                            print(f"[E2E] FINDING_UPDATED project={project_id} fingerprint={finding.get('fingerprint')}", flush=True)
                            event_bus.emit(project_id, {"type": "finding.updated", "project_id": project_id, "finding": finding, "related_commit": current_sha_for_analysis})
                        else:
                            print(f"[E2E] FINDING_CREATED project={project_id} fingerprint={finding.get('fingerprint')}", flush=True)
                            event_bus.emit(project_id, {"type": "finding.created", "project_id": project_id, "finding": finding, "related_commit": current_sha_for_analysis})
                    
                    # Emit finding.resolved events
                    for resolved in saved.get("resolved_events", []):
                        print(f"[E2E] FINDING_UPDATED project={project_id} resolved={resolved.get('finding_id')}", flush=True)
                        event_bus.emit(project_id, {"type": "finding.resolved", "project_id": project_id, **resolved, "related_commit": current_sha_for_analysis})
                    
                    # Emit requirement.updated if requirements changed
                    if saved.get("requirements"):
                        event_bus.emit(project_id, {"type": "requirement.updated", "project_id": project_id, "requirements": saved.get("requirements", []), "review_id": saved["id"], "related_commit": current_sha_for_analysis})
                    
                    # Emit dna.updated if failure DNA changed
                    if updated.get("failure_dna"):
                        event_bus.emit(project_id, {"type": "dna.updated", "project_id": project_id, "failure_dna": updated["failure_dna"], "review_id": saved["id"], "related_commit": current_sha_for_analysis})
                    
                    # Emit prediction.updated if predictions changed
                    if updated.get("next_failure_predictions"):
                        event_bus.emit(project_id, {"type": "prediction.updated", "project_id": project_id, "predictions": updated["next_failure_predictions"], "review_id": saved["id"], "related_commit": current_sha_for_analysis})
                    
                except Exception as error:
                    print(f"[E2E] ANALYSIS_FAILED project={project_id} error={error}", flush=True)
                    event_bus.emit(project_id, {"type": "analysis.failed", "project_id": project_id, "message": str(error)})
        start_watcher(project_id, path, on_change, git_sha)
        return {"project_id": persisted["project_id"], "review_id": persisted["id"], "review_number": persisted["review_number"], "source_type": request.source_type, "path": path, "branch": git_branch, "current_commit_sha": git_sha, "monitoring_status": "active", "analysis": analysis, "persisted_review": persisted}
    except ValueError as error: raise HTTPException(422, str(error)) from error

@router.post("/{project_id}/monitoring/stop")
def stop_monitoring(project_id: int, request: Request):
    stop_watcher(project_id)
    with request.app.state.SessionLocal() as session:
        project = session.get(ReviewedProject, project_id)
        if not project: raise HTTPException(404, "Project not found")
        project.monitoring_status = "paused"; session.commit()
    return {"project_id": project_id, "monitoring_status": "paused"}

@router.get("/{project_id}/events")
async def project_events(project_id: int):
    async def stream():
        async for event in event_bus.subscribe(project_id):
            import json
            yield f"event: {event.get('type', 'project.event')}\ndata: {json.dumps(event)}\n\n"
    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "Connection": "keep-alive"})


@router.get("/{project_id}/history", summary="Return chronological persisted reviews")
def history(project_id: int, request: Request):
    try:
        with request.app.state.SessionLocal() as session:
            return project_history(session, project_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/{project_id}/failure-history", summary="Aggregate persisted failure findings across reviews")
def failure_history_report(project_id: int, request: Request):
    try:
        with request.app.state.SessionLocal() as session:
            return failure_history(session, project_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/{project_id}/compare", summary="Compare the latest two persisted reviews")
def compare(project_id: int, request: Request):
    try:
        with request.app.state.SessionLocal() as session:
            return compare_reviews(session, project_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/{project_id}/evolution")
def evolution_report(project_id: int, request: Request):
    with request.app.state.SessionLocal() as session:
        return evolution(session, project_id)


@router.get("/{project_id}/trajectory")
def trajectory_report(project_id: int, request: Request):
    with request.app.state.SessionLocal() as session:
        return trajectory(session, project_id)


@router.get("/{project_id}/requirements")
def requirement_report(project_id: int, request: Request):
    with request.app.state.SessionLocal() as session:
        return requirements(session, project_id)


@router.get("/{project_id}/requirements/coverage")
def requirement_coverage(project_id: int, request: Request):
    with request.app.state.SessionLocal() as session:
        return requirements(session, project_id)


@router.get("/{project_id}/research-observations")
def research_data(project_id: int, request: Request):
    with request.app.state.SessionLocal() as session:
        return research_observations(session, project_id)


@router.get("/{project_id}/research-prediction", summary="Next-failure prediction from the saved MISTIQ-APR artifact")
def research_prediction_report(project_id: int, request: Request):
    with request.app.state.SessionLocal() as session:
        try:
            return research_prediction(session, project_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/research/status")
def research_status_report(request: Request):
    with request.app.state.SessionLocal() as session:
        return research_status(session)


@router.get("/research/dataset")
def research_dataset_report(request: Request):
    with request.app.state.SessionLocal() as session:
        return research_dataset(session)


@router.get("/research/evaluation")
def research_evaluation_report(request: Request):
    with request.app.state.SessionLocal() as session:
        return research_evaluation(session)


@router.get("/projects", summary="List all reviewed projects")
def list_projects(request: Request):
    with request.app.state.SessionLocal() as session:
        projects = session.scalars(select(ReviewedProject).order_by(ReviewedProject.updated_at.desc())).all()
        return [
            {
                "id": p.id,
                "name": p.name,
                "repository_path": p.repository_path,
                "source_type": p.source_type,
                "repository_url": p.repository_url,
                "branch": p.branch,
                "current_commit_sha": p.current_commit_sha,
                "monitoring_status": p.monitoring_status,
                "updated_at": p.updated_at.isoformat() if p.updated_at else None,
            }
            for p in projects
        ]


@router.get("/{project_id}/latest", summary="Get latest completed review for a project")
def get_latest_review(project_id: int, request: Request):
    with request.app.state.SessionLocal() as session:
        latest = session.scalar(
            select(ProjectReview)
            .where(ProjectReview.project_id == project_id)
            .order_by(ProjectReview.review_number.desc())
        )
        if not latest:
            raise HTTPException(404, "No reviews found for this project")
        return serialize_review(session, latest.id)

