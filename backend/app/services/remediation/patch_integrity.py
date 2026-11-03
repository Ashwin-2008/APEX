"""Cryptographic Patch Provenance & Stale Patch Detection for APEX 2.0.

Provides cryptographic verification of candidate code patches:
1. Provenance tracking: cryptographically binds patch to exact source SHA-256,
   repository revision, generator version, and verification state.
2. Stale patch detection: rejects patch application if underlying source file was
   modified on disk after patch generation.
3. Patch tampering detection: prevents applying patches whose diff or content
   was tampered with after verification.
"""
from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.services.remediation.patch_generator import CodePatch


def compute_content_sha256(content: str) -> str:
    """Computes standard hex SHA-256 digest for UTF-8 encoded text."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


@dataclass
class PatchProvenance:
    patch_id: str
    finding_id: str
    source_file: str
    original_source_sha256: str
    patched_source_sha256: str
    patch_content_sha256: str
    project_id: int | None = None
    repo_revision: str | None = None
    generator_version: str = "2.0-phase2d1"
    analyzer_version: str = "2.0"
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    verified_at: str | None = None
    verification_hash: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class PatchIntegrityService:
    """Manages patch provenance and ensures cryptographic integrity before disk application."""

    @classmethod
    def generate_provenance(
        cls,
        patch: CodePatch,
        original_code: str,
        patched_code: str,
        project_id: int | None = None,
        repo_revision: str | None = None,
    ) -> PatchProvenance:
        orig_hash = compute_content_sha256(original_code)
        patch_hash = compute_content_sha256(patched_code)
        diff_hash = compute_content_sha256(patch.unified_diff)

        return PatchProvenance(
            patch_id=patch.patch_id,
            finding_id=patch.finding_id,
            source_file=patch.file,
            original_source_sha256=orig_hash,
            patched_source_sha256=patch_hash,
            patch_content_sha256=diff_hash,
            project_id=project_id,
            repo_revision=repo_revision,
        )

    @classmethod
    def check_integrity(
        cls,
        provenance: PatchProvenance,
        patch: CodePatch,
        repo_root: Path,
    ) -> tuple[bool, str, str]:
        """Checks for tampering and stale source files.
        
        Returns:
            (is_valid, message, status_code)
            status_code in {'OK', 'STALE_PATCH', 'TAMPERED_PATCH', 'FILE_NOT_FOUND', 'TRAVERSAL_DETECTED'}
        """
        # 1. Path safety
        target_path = (repo_root / provenance.source_file).resolve()
        repo_root_res = repo_root.resolve()
        if not str(target_path).startswith(str(repo_root_res)):
            return False, "Target file path traverses outside repository root.", "TRAVERSAL_DETECTED"

        if not target_path.is_file():
            return False, f"Target file '{provenance.source_file}' does not exist on disk.", "FILE_NOT_FOUND"

        # 2. Tampering check on patch content
        current_diff_hash = compute_content_sha256(patch.unified_diff)
        if current_diff_hash != provenance.patch_content_sha256:
            return (
                False,
                f"Patch tampering detected: patch content hash '{current_diff_hash[:8]}' does not match verified provenance hash '{provenance.patch_content_sha256[:8]}'.",
                "TAMPERED_PATCH",
            )

        # 3. Stale patch check against current disk content
        try:
            current_source = target_path.read_text(encoding="utf-8", errors="ignore")
        except OSError as e:
            return False, f"Failed reading target source file: {e}", "FILE_NOT_FOUND"

        current_source_hash = compute_content_sha256(current_source)
        if current_source_hash != provenance.original_source_sha256:
            return (
                False,
                f"Stale patch detected: source file '{provenance.source_file}' has been modified since patch generation (expected {provenance.original_source_sha256[:8]}, found {current_source_hash[:8]}). Regeneration required.",
                "STALE_PATCH",
            )

        return True, "Patch cryptographic integrity verified.", "OK"

