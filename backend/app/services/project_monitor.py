from __future__ import annotations
import asyncio, os, threading, time
from collections import defaultdict, deque
from pathlib import Path
from typing import Any
from app.core.config import settings
from app.services.git_service import get_current_sha, get_branch, detect_commit_transition, is_git_repository

IGNORED = {".git", "node_modules", "dist", "build", "__pycache__", ".venv", "venv", "coverage", "cache"}
SOURCE_SUFFIXES = {".py", ".js", ".jsx", ".ts", ".tsx", ".java", ".go", ".rb", ".php", ".md", ".txt", ".json", ".toml", ".yaml", ".yml", ".sql", ""}

class ProjectEventBus:
    def __init__(self): self._subscribers: dict[int, set[asyncio.Queue]] = defaultdict(set); self._loops: dict[int, asyncio.AbstractEventLoop] = {}; self._events: dict[int, deque] = defaultdict(lambda: deque(maxlen=100))
    def emit(self, project_id: int, event: dict[str, Any]):
        self._events[project_id].append(event)
        for queue in list(self._subscribers[project_id]):
            loop = self._loops.get(project_id)
            try:
                if loop and loop.is_running(): loop.call_soon_threadsafe(queue.put_nowait, event)
                else: queue.put_nowait(event)
            except (asyncio.QueueFull, RuntimeError): pass
    async def subscribe(self, project_id: int):
        queue: asyncio.Queue = asyncio.Queue(maxsize=100); self._subscribers[project_id].add(queue); self._loops[project_id] = asyncio.get_running_loop()
        try:
            for event in self._events[project_id]: yield event
            while True: yield await queue.get()
        finally:
            self._subscribers[project_id].discard(queue)
            if not self._subscribers[project_id]: self._loops.pop(project_id, None)

event_bus = ProjectEventBus()
_watchers: dict[int, threading.Event] = {}

def snapshot(root: str) -> dict[str, float]:
    path = Path(root); result = {}
    if not path.is_dir(): return result
    for file in path.rglob("*"):
        if file.is_file() and not any(part in IGNORED for part in file.parts) and file.suffix.lower() in SOURCE_SUFFIXES:
            try: result[str(file)] = file.stat().st_mtime_ns
            except OSError: pass
    return result

def changed_analyzers(paths: list[str]) -> list[str]:
    analyzers = set()
    for raw in paths:
        path = Path(raw); name = path.name.lower(); suffix = path.suffix.lower()
        if suffix in {".py", ".js", ".jsx", ".ts", ".tsx", ".java", ".go"}: analyzers.update({"source", "api", "authentication", "testing"})
        if "readme" in name or "prd" in name or suffix in {".md", ".txt"}: analyzers.update({"requirements", "coverage"})
        if name in {"requirements.txt", "package.json", "pyproject.toml", "package-lock.json", "yarn.lock", "pnpm-lock.yaml"}: analyzers.update({"dependency", "security"})
        if name == "dockerfile" or "docker" in name: analyzers.update({"deployment", "configuration", "dependency"})
        if "test" in name or "spec" in name: analyzers.add("testing")
    return sorted(analyzers)

def start_watcher(project_id: int, root: str, callback, previous_sha: str | None = None):
    stop = threading.Event(); _watchers[project_id] = stop
    is_git_repo = is_git_repository(root)
    
    def run():
        before = snapshot(root); pending: set[str] = set(); changed_at = 0.0
        current_git_sha = previous_sha
        git_branch = get_branch(root) if is_git_repo else None
        
        print(f"[E2E] MONITORING_ACTIVE project={project_id}", flush=True)
        callback({"type": "monitoring.status", "project_id": project_id, "status": "active", "current_commit_sha": current_git_sha, "branch": git_branch})
        
        while not stop.wait(1.0):
            # Check for Git SHA changes if this is a Git repository
            if is_git_repo:
                new_sha = get_current_sha(root)
                if new_sha and new_sha != current_git_sha:
                    transition = detect_commit_transition(root, current_git_sha)
                    if transition:
                        current_git_sha = transition.current_sha
                        git_branch = transition.branch
                        # Emit project.changed event with Git commit transition info
                        print(f"[E2E] FILE_CHANGED project={project_id} files={transition.changed_files}", flush=True)
                        callback({"type": "project.changed", "project_id": project_id, "files": transition.changed_files, "analyzers": changed_analyzers(transition.changed_files), "current_commit_sha": transition.current_sha, "previous_commit_sha": transition.previous_sha, "branch": transition.branch, "commit_info": transition.commit_info.to_dict() if transition.commit_info else None})
                        # Reset pending changes since we handled them via Git
                        pending.clear()
                        before = snapshot(root)
                        continue
            
            # Regular filesystem monitoring
            after = snapshot(root); paths = set(before) | set(after); changed = {p for p in paths if before.get(p) != after.get(p)}
            if changed: pending.update(changed); changed_at = time.monotonic()
            if pending and time.monotonic() - changed_at >= settings.monitor_debounce_seconds:
                changed_list = sorted(pending); pending.clear()
                # For Git repos, try to get current SHA for the event
                current_sha_for_event = get_current_sha(root) if is_git_repo else None
                print(f"[E2E] FILE_CHANGED project={project_id} files={changed_list}", flush=True)
                print(f"[E2E] DEBOUNCE_COMPLETE project={project_id}", flush=True)
                try:
                    callback({"type": "project.changed", "project_id": project_id, "files": changed_list, "analyzers": changed_analyzers(changed_list), "current_commit_sha": current_sha_for_event, "branch": git_branch})
                    print(f"[E2E] CALLBACK_COMPLETE project={project_id}", flush=True)
                except Exception as error:
                    print(f"[E2E] CALLBACK_ERROR project={project_id} error={error}", flush=True)
            before = after
        callback({"type": "monitoring.status", "project_id": project_id, "status": "paused", "current_commit_sha": current_git_sha, "branch": git_branch})
    threading.Thread(target=run, daemon=True, name=f"mistiq-monitor-{project_id}").start()
    return stop

def stop_watcher(project_id: int):
    event = _watchers.pop(project_id, None)
    if event: event.set()
