from __future__ import annotations
import asyncio, os, threading, time
from collections import defaultdict, deque
from pathlib import Path
from typing import Any
from app.core.config import settings

IGNORED = {".git", "node_modules", "dist", "build", "__pycache__", ".venv", "venv", "coverage", "cache"}
SOURCE_SUFFIXES = {".py", ".js", ".jsx", ".ts", ".tsx", ".java", ".go", ".rb", ".php", ".md", ".txt", ".json", ".toml", ".yaml", ".yml", ".sql", ""}

class ProjectEventBus:
    def __init__(self): self._subscribers: dict[int, set[asyncio.Queue]] = defaultdict(set); self._events: dict[int, deque] = defaultdict(lambda: deque(maxlen=100))
    def emit(self, project_id: int, event: dict[str, Any]):
        self._events[project_id].append(event)
        for queue in list(self._subscribers[project_id]):
            try: queue.put_nowait(event)
            except asyncio.QueueFull: pass
    async def subscribe(self, project_id: int):
        queue: asyncio.Queue = asyncio.Queue(maxsize=100); self._subscribers[project_id].add(queue)
        try:
            for event in self._events[project_id]: yield event
            while True: yield await queue.get()
        finally: self._subscribers[project_id].discard(queue)

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

def start_watcher(project_id: int, root: str, callback):
    stop = threading.Event(); _watchers[project_id] = stop
    def run():
        before = snapshot(root); pending: set[str] = set(); changed_at = 0.0
        callback({"type": "monitoring.status", "project_id": project_id, "status": "active"})
        while not stop.wait(1.0):
            after = snapshot(root); paths = set(before) | set(after); changed = {p for p in paths if before.get(p) != after.get(p)}
            if changed: pending.update(changed); changed_at = time.monotonic()
            if pending and time.monotonic() - changed_at >= settings.monitor_debounce_seconds:
                changed_list = sorted(pending); pending.clear(); callback({"type": "project.changed", "project_id": project_id, "files": changed_list, "analyzers": changed_analyzers(changed_list)})
            before = after
        callback({"type": "monitoring.status", "project_id": project_id, "status": "paused"})
    threading.Thread(target=run, daemon=True, name=f"mistiq-monitor-{project_id}").start()
    return stop

def stop_watcher(project_id: int):
    event = _watchers.pop(project_id, None)
    if event: event.set()
