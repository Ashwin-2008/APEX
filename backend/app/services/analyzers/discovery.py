"""Repository Discovery Engine: structural inventory, languages, frameworks, and manifest mapping."""
from __future__ import annotations

import os
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.services.analyzers.base import AnalyzerOutput, AnalyzerStatus

IGNORED_DIRECTORIES = frozenset({
    ".git", "node_modules", "venv", ".venv", "__pycache__", "dist", "build",
    ".pytest_cache", ".next", "coverage", ".zed", ".idea", ".vscode", "target", "vendor",
})

LANGUAGE_BY_EXT = {
    ".py": "Python",
    ".ts": "TypeScript",
    ".tsx": "TypeScript (React)",
    ".js": "JavaScript",
    ".jsx": "JavaScript (React)",
    ".java": "Java",
    ".go": "Go",
    ".rs": "Rust",
    ".rb": "Ruby",
    ".php": "PHP",
    ".c": "C",
    ".cpp": "C++",
    ".h": "C/C++ Header",
    ".cs": "C#",
    ".scala": "Scala",
    ".kt": "Kotlin",
    ".sql": "SQL",
    ".sh": "Shell",
    ".ps1": "PowerShell",
    ".html": "HTML",
    ".css": "CSS",
    ".scss": "SCSS",
    ".json": "JSON",
    ".yaml": "YAML",
    ".yml": "YAML",
    ".toml": "TOML",
    ".md": "Markdown",
}

FRAMEWORK_SIGNATURES = [
    ("FastAPI", ["from fastapi import", "import fastapi"], [".py"]),
    ("Flask", ["from flask import", "import flask"], [".py"]),
    ("Django", ["django.db", "from django."], [".py"]),
    ("React", ["from 'react'", "from \"react\"", "import React"], [".js", ".jsx", ".ts", ".tsx"]),
    ("Next.js", ["from 'next/", "from \"next/\""], [".js", ".jsx", ".ts", ".tsx"]),
    ("Vue", ["from 'vue'", "from \"vue\""], [".js", ".ts", ".vue"]),
    ("Express", ["require('express')", "from 'express'", "import express"], [".js", ".ts"]),
    ("Spring Boot", ["org.springframework.boot", "@SpringBootApplication"], [".java"]),
    ("Gin", ["github.com/gin-gonic/gin"], [".go"]),
    ("Fiber", ["github.com/gofiber/fiber"], [".go"]),
    ("Actix Web", ["actix_web"], [".rs"]),
]


@dataclass
class DiscoveryInventory:
    root_path: str
    total_files: int
    supported_files: int
    skipped_files: int
    excluded_files: int
    language_counts: dict[str, int]
    primary_language: str
    detected_frameworks: list[str]
    package_managers: list[str]
    entry_points: list[str]
    test_directories: list[str]
    config_files: list[str]
    ci_cd_files: list[str]
    docker_files: list[str]
    unsupported_extensions: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "root_path": self.root_path,
            "total_files": self.total_files,
            "supported_files": self.supported_files,
            "skipped_files": self.skipped_files,
            "excluded_files": self.excluded_files,
            "language_counts": self.language_counts,
            "primary_language": self.primary_language,
            "detected_frameworks": self.detected_frameworks,
            "package_managers": self.package_managers,
            "entry_points": self.entry_points,
            "test_directories": self.test_directories,
            "config_files": self.config_files,
            "ci_cd_files": self.ci_cd_files,
            "docker_files": self.docker_files,
            "unsupported_extensions": self.unsupported_extensions,
        }


def discover_repository(root_dir: str | Path) -> DiscoveryInventory:
    """Inspect and inventory the repository structure and technology stack."""
    root = Path(root_dir).resolve()
    all_files: list[Path] = []
    excluded_count = 0

    for dirpath, dirnames, filenames in os.walk(root):
        rel_dir = Path(dirpath).relative_to(root)
        if any(part in IGNORED_DIRECTORIES for part in rel_dir.parts):
            excluded_count += len(filenames)
            continue
        # prune in-place so os.walk does not descend into ignored trees
        dirnames[:] = [d for d in dirnames if d not in IGNORED_DIRECTORIES]
        for f in filenames:
            all_files.append(Path(dirpath) / f)

    total_files = len(all_files) + excluded_count
    ext_counter = Counter(p.suffix.lower() for p in all_files if p.suffix)
    language_counter: Counter[str] = Counter()
    unsupported_exts: list[str] = []

    for ext, count in ext_counter.items():
        if ext in LANGUAGE_BY_EXT:
            language_counter[LANGUAGE_BY_EXT[ext]] += count
        else:
            unsupported_exts.append(ext)

    supported_files = sum(language_counter.values())
    skipped_files = len(all_files) - supported_files

    primary_language = language_counter.most_common(1)[0][0] if language_counter else "Unknown"

    detected_frameworks: set[str] = set()
    package_managers: set[str] = set()
    entry_points: list[str] = []
    test_dirs: set[str] = set()
    config_files: list[str] = []
    ci_cd_files: list[str] = []
    docker_files: list[str] = []

    for p in all_files:
        rel = str(p.relative_to(root)).replace("\\", "/")
        rel_lower = rel.lower()
        name_lower = p.name.lower()

        # Package managers & build files
        if name_lower == "package.json":
            package_managers.add("npm / node")
            config_files.append(rel)
        elif name_lower == "pnpm-lock.yaml":
            package_managers.add("pnpm")
        elif name_lower == "yarn.lock":
            package_managers.add("yarn")
        elif name_lower in {"requirements.txt", "pyproject.toml", "pipfile", "setup.py"}:
            package_managers.add("pip / python")
            config_files.append(rel)
        elif name_lower in {"pom.xml", "build.gradle"}:
            package_managers.add("maven / gradle")
            config_files.append(rel)
        elif name_lower == "go.mod":
            package_managers.add("go modules")
            config_files.append(rel)
        elif name_lower == "cargo.toml":
            package_managers.add("cargo")
            config_files.append(rel)

        # Docker & Containers
        if "dockerfile" in name_lower or name_lower.endswith(".dockerfile") or name_lower in {"docker-compose.yml", "docker-compose.yaml"}:
            docker_files.append(rel)

        # CI/CD Workflows
        if ".github/workflows" in rel_lower or name_lower in {".gitlab-ci.yml", "jenkinsfile", "azure-pipelines.yml"}:
            ci_cd_files.append(rel)

        # Tests
        if "test" in p.parts or "tests" in p.parts or name_lower.startswith("test_") or "_test." in name_lower or ".spec." in name_lower or ".test." in name_lower:
            parts = p.relative_to(root).parts
            if len(parts) > 1:
                test_dirs.add(parts[0])

        # Entry points
        if name_lower in {"main.py", "app.py", "wsgi.py", "asgi.py", "index.ts", "index.js", "main.go", "server.js", "server.ts", "main.rs"}:
            entry_points.append(rel)

        # Framework detection by content sampling (first 100 code files)
        if len(detected_frameworks) < len(FRAMEWORK_SIGNATURES) and p.suffix.lower() in LANGUAGE_BY_EXT and p.stat().st_size < 1_000_000:
            try:
                sample = p.read_text(encoding="utf-8", errors="ignore")[:4000]
                for fw_name, signatures, exts in FRAMEWORK_SIGNATURES:
                    if fw_name not in detected_frameworks and p.suffix.lower() in exts:
                        if any(sig in sample for sig in signatures):
                            detected_frameworks.add(fw_name)
            except OSError:
                pass

    return DiscoveryInventory(
        root_path=str(root),
        total_files=total_files,
        supported_files=supported_files,
        skipped_files=skipped_files,
        excluded_files=excluded_count,
        language_counts=dict(language_counter),
        primary_language=primary_language,
        detected_frameworks=sorted(detected_frameworks),
        package_managers=sorted(package_managers),
        entry_points=sorted(entry_points)[:10],
        test_directories=sorted(test_dirs),
        config_files=config_files[:20],
        ci_cd_files=ci_cd_files[:10],
        docker_files=docker_files[:10],
        unsupported_extensions=sorted(set(unsupported_exts))[:20],
    )

