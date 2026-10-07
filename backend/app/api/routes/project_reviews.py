from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
import re, subprocess
from pathlib import Path
from pydantic import BaseModel, Field

from app.services.project_review_service import analyze_project
from app.services.project_review_persistence import compare_reviews, persist_analysis, project_history
from app.services.project_evolution_service import evolution, trajectory, requirements, research_observations
from app.services.mistiq_apr_research_service import (
    research_dataset,
    research_evaluation,
    research_prediction,
    research_status,
)
from app.services.project_monitor import event_bus, start_watcher, stop_watcher
from app.models.entities import ReviewedProject

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
        if not request.repository_url or not re.match(r"^https://github\.com/[^/]+/[^/]+(?:\.git)?/?$", request.repository_url): raise HTTPException(422, "Only public HTTPS GitHub repository URLs are supported.")
        slug = request.repository_url.rstrip("/").removesuffix(".git").split("/")[-2:]
        target = (Path("data/repositories") / "-".join(slug)).resolve(); base = Path("data/repositories").resolve()
        if base not in target.parents: raise HTTPException(422, "Unsafe repository path.")
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            try: subprocess.run(["git", "clone", "--depth", "1", request.repository_url, str(target)], check=True, capture_output=True, text=True, timeout=180)
            except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as error: raise HTTPException(502, "Public GitHub repository could not be cloned.") from error
        path = str(target)
    if not path or not Path(path).is_dir(): raise HTTPException(422, "A valid local project directory is required.")
    try:
        analysis = analyze_project(path)
        with app_request.app.state.SessionLocal() as session:
            persisted = persist_analysis(session, analysis); project = session.get(ReviewedProject, persisted["project_id"]); project.source_type = request.source_type; project.repository_url = request.repository_url; project.branch = request.branch; project.monitoring_status = "active"; session.commit()
        project_id = persisted["project_id"]
        def on_change(event):
            event_bus.emit(project_id, {**event, "type": "analysis.started"})
            if event.get("type") == "project.changed":
                try:
                    updated = analyze_project(path)
                    with app_request.app.state.SessionLocal() as session:
                        saved = persist_analysis(session, updated)
                    event_bus.emit(project_id, {"type": "analysis.completed", "project_id": project_id, "review_id": saved["id"], "review_number": saved["review_number"], "files": event.get("files", []), "analyzers": event.get("analyzers", [])})
                except Exception as error:
                    event_bus.emit(project_id, {"type": "analysis.failed", "project_id": project_id, "message": str(error)})
        start_watcher(project_id, path, on_change)
        return {"project_id": persisted["project_id"], "review_id": persisted["id"], "review_number": persisted["review_number"], "source_type": request.source_type, "path": path, "monitoring_status": "active", "analysis": analysis}
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
