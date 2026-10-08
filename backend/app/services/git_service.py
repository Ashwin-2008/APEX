"""Git repository SHA synchronization service.

Provides Git SHA detection, comparison, and commit transition tracking
for project monitoring and incremental analysis.
"""
from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class GitCommitInfo:
    """Information about a Git commit."""
    sha: str
    message: str
    author_date: str
    committer_date: str
    
    def to_dict(self) -> dict:
        return {
            "sha": self.sha,
            "message": self.message,
            "author_date": self.author_date,
            "committer_date": self.committer_date
        }


@dataclass 
class GitTransition:
    """Represents a transition between Git commits."""
    previous_sha: Optional[str]
    current_sha: str
    changed_files: list[str]
    commit_info: Optional[GitCommitInfo]
    branch: str
    
    def to_dict(self) -> dict:
        return {
            "previous_sha": self.previous_sha,
            "current_sha": self.current_sha,
            "changed_files": self.changed_files,
            "commit_info": self.commit_info.to_dict() if self.commit_info else None,
            "branch": self.branch
        }


def get_current_sha(repo_path: str) -> Optional[str]:
    """Get the current Git commit SHA for a repository."""
    try:
        result = subprocess.check_output(
            ["git", "-C", repo_path, "rev-parse", "HEAD"],
            text=True,
            stderr=subprocess.DEVNULL,
            timeout=30
        )
        return result.strip()
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError):
        return None


def get_branch(repo_path: str) -> Optional[str]:
    """Get the current branch for a repository."""
    try:
        result = subprocess.check_output(
            ["git", "-C", repo_path, "rev-parse", "--abbrev-ref", "HEAD"],
            text=True,
            stderr=subprocess.DEVNULL,
            timeout=30
        )
        branch = result.strip()
        return branch if branch else "HEAD"  # Handle detached HEAD
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError):
        return None


def get_commit_info(repo_path: str, sha: str) -> Optional[GitCommitInfo]:
    """Get detailed information about a specific commit."""
    try:
        result = subprocess.check_output(
            ["git", "-C", repo_path, "show", "-s", "--format=%H|%aI|%cI|%s", sha],
            text=True,
            stderr=subprocess.DEVNULL,
            timeout=30
        )
        parts = result.strip().split("|", 3)
        if len(parts) >= 4:
            return GitCommitInfo(
                sha=parts[0],
                author_date=parts[1],
                committer_date=parts[2], 
                message=parts[3]
            )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError):
        pass
    return None


def get_changed_files_between_shas(repo_path: str, previous_sha: str, current_sha: str) -> list[str]:
    """Get list of files changed between two Git commits."""
    try:
        result = subprocess.check_output(
            ["git", "-C", repo_path, "diff", "--name-only", previous_sha, current_sha],
            text=True,
            stderr=subprocess.DEVNULL,
            timeout=30
        )
        return [f.strip() for f in result.splitlines() if f.strip()]
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError):
        return []


def get_changed_files_since_commit(repo_path: str, sha: str) -> list[str]:
    """Get list of files changed since a specific commit (working tree changes)."""
    try:
        result = subprocess.check_output(
            ["git", "-C", repo_path, "diff", "--name-only", sha],
            text=True,
            stderr=subprocess.DEVNULL,
            timeout=30
        )
        return [f.strip() for f in result.splitlines() if f.strip()]
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError):
        return []


def detect_commit_transition(repo_path: str, previous_sha: Optional[str]) -> Optional[GitTransition]:
    """Detect if there's been a Git commit transition and return transition info."""
    current_sha = get_current_sha(repo_path)
    if current_sha is None:
        return None
    
    branch = get_branch(repo_path) or "unknown"
    
    if previous_sha == current_sha:
        return None
    
    if previous_sha is None:
        # First time seeing this repo, get all changed files from root
        changed_files = get_all_tracked_files(repo_path)
        commit_info = get_commit_info(repo_path, current_sha)
        return GitTransition(
            previous_sha=previous_sha,
            current_sha=current_sha,
            changed_files=changed_files,
            commit_info=commit_info,
            branch=branch
        )
    
    # Get files changed between the two commits
    changed_files = get_changed_files_between_shas(repo_path, previous_sha, current_sha)
    
    # If no files from git diff (might be untracked changes), also check working tree
    if not changed_files:
        changed_files = get_changed_files_since_commit(repo_path, previous_sha)
    
    commit_info = get_commit_info(repo_path, current_sha)
    
    return GitTransition(
        previous_sha=previous_sha,
        current_sha=current_sha,
        changed_files=changed_files,
        commit_info=commit_info,
        branch=branch
    )


def get_all_tracked_files(repo_path: str) -> list[str]:
    """Get all tracked files in a Git repository."""
    try:
        result = subprocess.check_output(
            ["git", "-C", repo_path, "ls-files"],
            text=True,
            stderr=subprocess.DEVNULL,
            timeout=30
        )
        return [f.strip() for f in result.splitlines() if f.strip()]
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError):
        return []


def is_git_repository(repo_path: str) -> bool:
    """Check if a path is a Git repository."""
    try:
        result = subprocess.check_output(
            ["git", "-C", repo_path, "rev-parse", "--is-inside-work-tree"],
            text=True,
            stderr=subprocess.DEVNULL,
            timeout=30
        )
        return result.strip() == "true"
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError):
        return False