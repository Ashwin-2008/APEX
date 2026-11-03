"""Dynamic Analysis Engine: isolated execution sandbox, test runner, and runtime validation.

Implements containerized ephemeral Docker sandboxes with:
- Non-root user execution (1000:1000)
- Read-only source mounting (:ro)
- Network disabled (--network none)
- Resource limits (CPU 1.0, Memory 512m, PIDs limit 50)
- Restricted tmpfs filesystem (/tmp)
- Credential and environment scrubbing
- Automatic cleanup (--rm)
- Strict prevention of silent host execution fallbacks in production
"""
from __future__ import annotations

import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.services.analyzers.base import AnalyzerOutput, AnalyzerStatus, FindingItem

DEFAULT_TIMEOUT_SECONDS = 30
MAX_OUTPUT_BYTES = 50_000


def is_docker_available() -> bool:
    """Check if the Docker CLI is installed and the Docker daemon is responsive."""
    if not shutil.which("docker"):
        return False
    try:
        res = subprocess.run(
            ["docker", "info", "--format", "{{.ServerVersion}}"],
            capture_output=True,
            text=True,
            timeout=3,
        )
        return res.returncode == 0
    except (subprocess.TimeoutExpired, OSError, Exception):
        return False


def build_docker_sandbox_command(
    root: Path,
    command: list[str],
    image: str = "python:3.11-slim",
) -> list[str]:
    """Construct ephemeral, non-root, network-isolated Docker container invocation.
    
    Guarantees:
    - --rm: container is destroyed immediately upon completion
    - --network none: total network isolation
    - --user 1000:1000: non-root privileges
    - -v <root>:/workspace:ro: source code is strictly read-only
    - --tmpfs /tmp:rw,noexec,nosuid,size=64m: restricted scratch space
    - --memory 512m: memory limit
    - --cpus 1.0: CPU compute quota
    - --pids-limit 50: fork-bomb and thread exhaustion protection
    - No /var/run/docker.sock mounted
    """
    return [
        "docker",
        "run",
        "--rm",
        "--network",
        "none",
        "--user",
        "1000:1000",
        "-v",
        f"{str(root)}:/workspace:ro",
        "--tmpfs",
        "/tmp:rw,noexec,nosuid,size=64m",
        "--memory",
        "512m",
        "--cpus",
        "1.0",
        "--pids-limit",
        "50",
        "-w",
        "/workspace",
        image,
        *command,
    ]


def run_dynamic_analysis(
    root_dir: str | Path,
    enabled: bool = False,
    command: list[str] | None = None,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
) -> AnalyzerOutput:
    """Execute dynamic validation in a restricted sandbox environment.

    In production mode or when APEX_SANDBOX_MODE='docker', enforces container execution
    and fails fast if Docker is unavailable without falling back to host execution.
    In local development mode (APEX_SANDBOX_MODE='local_dev'), executes via a stripped
    subprocess runner.
    """
    start_time = time.perf_counter()
    root = Path(root_dir).resolve()

    if not enabled:
        return AnalyzerOutput(
            analyzer_name="dynamic_analyzer",
            status=AnalyzerStatus.NOT_APPLICABLE,
            findings=[],
            metrics={
                "policy": "disabled",
                "explanation": "Dynamic execution is opt-in to safeguard production hosts from untrusted code.",
            },
            duration_ms=0.0,
        )

    is_production = settings.environment == "production"
    mode = settings.sandbox_mode
    exec_cmd = command or ["pytest", "--version"]

    # 1. Enforce production mode isolation constraints
    if is_production and mode != "docker":
        return AnalyzerOutput(
            analyzer_name="dynamic_analyzer",
            status=AnalyzerStatus.FAILED,
            findings=[
                FindingItem(
                    category="security",
                    severity="critical",
                    confidence=1.0,
                    evidence="Unsafe host execution is strictly forbidden in production mode. APEX_SANDBOX_MODE must be set to 'docker'.",
                    analyzer_source="dynamic_sandbox",
                    rule_id="DYN-PRODUCTION-POLICY-VIOLATION",
                    title="Production Sandbox Isolation Policy Violation",
                    remediation="Configure APEX_SANDBOX_MODE='docker' in production environment.",
                )
            ],
            metrics={"policy": "rejected", "mode": mode, "environment": "production"},
            duration_ms=0.0,
            error_message="Host execution is forbidden in production environment.",
        )

    # 2. Containerized Docker execution
    if mode == "docker" or is_production:
        if not is_docker_available():
            # In production or docker mode, NEVER silently fall back to host execution
            duration = (time.perf_counter() - start_time) * 1000
            return AnalyzerOutput(
                analyzer_name="dynamic_analyzer",
                status=AnalyzerStatus.FAILED,
                findings=[
                    FindingItem(
                        category="deployment",
                        severity="high",
                        confidence=1.0,
                        evidence="Dynamic analysis container sandbox is unavailable: Docker daemon is not running or accessible. Silent host fallback is blocked by security policy.",
                        analyzer_source="dynamic_sandbox",
                        rule_id="DYN-SANDBOX-UNAVAILABLE",
                        title="Dynamic Analysis Container Sandbox Unavailable",
                        remediation="Start the Docker daemon service or ensure docker socket permissions are granted to the APEX worker.",
                    )
                ],
                metrics={
                    "provider": "docker",
                    "docker_available": False,
                    "policy": "no_silent_host_fallback",
                },
                duration_ms=duration,
                error_message="Sandbox execution unavailable: Docker daemon is not running and host fallback is forbidden in secure mode.",
            )

        docker_cmd = build_docker_sandbox_command(
            root=root,
            command=exec_cmd,
            image=settings.sandbox_image,
        )
        safe_env = {"PATH": os.environ.get("PATH", "")}
        findings: list[FindingItem] = []
        status = AnalyzerStatus.COMPLETE
        error_msg: str | None = None
        output_text = ""

        try:
            proc = subprocess.run(
                docker_cmd,
                capture_output=True,
                text=True,
                env=safe_env,
                timeout=timeout_seconds,
            )
            output_text = (proc.stdout + "\n" + proc.stderr)[:MAX_OUTPUT_BYTES]
            if proc.returncode != 0:
                status = AnalyzerStatus.FAILED
                findings.append(
                    FindingItem(
                        category="testing",
                        severity="medium",
                        confidence=0.90,
                        evidence=f"Containerized execution '{' '.join(exec_cmd)}' failed with exit code {proc.returncode}:\n{output_text[:300]}",
                        analyzer_source="dynamic_sandbox",
                        rule_id="DYN-CONTAINER-TEST-FAILURE",
                        title="Dynamic Test Runner Execution Failure",
                        remediation="Inspect test runner errors in the container execution log.",
                    )
                )
        except subprocess.TimeoutExpired:
            status = AnalyzerStatus.FAILED
            error_msg = f"Container execution timed out after {timeout_seconds} seconds."
            findings.append(
                FindingItem(
                    category="performance",
                    severity="high",
                    confidence=0.95,
                    evidence=f"Dynamic analysis timed out after {timeout_seconds}s.",
                    analyzer_source="dynamic_sandbox",
                    rule_id="DYN-EXECUTION-TIMEOUT",
                    title="Dynamic Sandbox Execution Timed Out",
                    remediation="Optimize test suite execution time or increase the sandbox timeout setting.",
                )
            )
        except Exception as exc:
            status = AnalyzerStatus.FAILED
            error_msg = str(exc)

        duration = (time.perf_counter() - start_time) * 1000
        return AnalyzerOutput(
            analyzer_name="dynamic_analyzer",
            status=status,
            findings=findings,
            metrics={
                "provider": "docker",
                "image": settings.sandbox_image,
                "command": exec_cmd,
                "timeout_seconds": timeout_seconds,
                "output_preview": output_text[:500],
            },
            duration_ms=duration,
            error_message=error_msg,
        )

    # 3. Local Development Mode (allowed only when settings.environment != 'production')
    safe_env = {
        "PATH": os.environ.get("PATH", ""),
        "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""),
        "TEMP": os.environ.get("TEMP", ""),
        "TMP": os.environ.get("TMP", ""),
        "PYTHONPATH": str(root),
    }

    findings = []
    status = AnalyzerStatus.COMPLETE
    error_msg = None
    output_text = ""

    try:
        proc = subprocess.run(
            exec_cmd,
            cwd=str(root),
            env=safe_env,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
        output_text = (proc.stdout + "\n" + proc.stderr)[:MAX_OUTPUT_BYTES]
        if proc.returncode != 0:
            status = AnalyzerStatus.FAILED
            findings.append(
                FindingItem(
                    category="testing",
                    severity="medium",
                    confidence=0.90,
                    evidence=f"Dynamic test execution command '{' '.join(exec_cmd)}' failed with exit code {proc.returncode}:\n{output_text[:300]}",
                    analyzer_source="dynamic_sandbox",
                    rule_id="DYN-TEST-RUNNER-FAILURE",
                    title="Dynamic Test Runner Execution Failure",
                    remediation="Inspect test runner errors in the sandbox execution log.",
                )
            )
    except subprocess.TimeoutExpired:
        status = AnalyzerStatus.FAILED
        error_msg = f"Execution timed out after {timeout_seconds} seconds."
        findings.append(
            FindingItem(
                category="performance",
                severity="high",
                confidence=0.95,
                evidence=f"Dynamic analysis timed out after {timeout_seconds}s.",
                analyzer_source="dynamic_sandbox",
                rule_id="DYN-EXECUTION-TIMEOUT",
                title="Dynamic Sandbox Execution Timed Out",
                remediation="Optimize test suite execution time or increase the sandbox timeout setting.",
            )
        )
    except Exception as exc:
        status = AnalyzerStatus.FAILED
        error_msg = str(exc)

    duration = (time.perf_counter() - start_time) * 1000
    return AnalyzerOutput(
        analyzer_name="dynamic_analyzer",
        status=status,
        findings=findings,
        metrics={
            "provider": "local_dev",
            "command": exec_cmd,
            "timeout_seconds": timeout_seconds,
            "output_preview": output_text[:500],
        },
        duration_ms=duration,
        error_message=error_msg,
    )
