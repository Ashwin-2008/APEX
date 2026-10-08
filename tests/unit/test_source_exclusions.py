"""Virtual environments and other non-source trees are not project source.

The analyzers must still report real secrets found in project source files, but
installed-package and generated directories (venv, node_modules, caches, build
output) are never scanned, so their files cannot become evidence.
"""

from pathlib import Path

from app.services.project_review_service import analyze_project

SECRET = 'API_KEY = "sk-live-0123456789abcdef"'

IGNORED_TREES = {
    "venv/lib/site-packages/vendor.py",
    "Venv/lib/site-packages/upper_vendor.py",
    ".venv/lib/site-packages/vendor.py",
    "node_modules/dep/index.py",
    "__pycache__/cached.py",
    "dist/bundle.py",
    "build/artifact.py",
    "coverage/report.py",
    "cache/tmp.py",
    ".git/hooks/pre.py",
}


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_secret_in_project_source_is_detected(tmp_path: Path):
    write(tmp_path / "app.py", SECRET)

    result = analyze_project(str(tmp_path))

    security = [event for event in result["events"] if event["category"] == "security"]
    assert len(security) == 1
    assert "app.py:1" in security[0]["evidence"]
    assert security[0]["analyzer_source"] == "secret_detector"
    assert result["project"]["file_count"] == 1


def test_installed_package_and_generated_directories_are_ignored(tmp_path: Path):
    write(tmp_path / "src" / "main.py", SECRET)
    for relative in IGNORED_TREES:
        write(tmp_path / Path(relative), SECRET)

    result = analyze_project(str(tmp_path))

    evidence = " ".join(event["evidence"] for event in result["events"])
    assert "main.py:1" in evidence
    for relative in IGNORED_TREES:
        assert Path(relative).name not in evidence
    assert result["project"]["file_count"] == 1
    assert "venv" not in evidence


def test_ignored_directories_do_not_hide_genuine_source_findings(tmp_path: Path):
    write(tmp_path / "venv/lib/site-packages/vendor.py", SECRET)
    write(tmp_path / "services" / "auth.py", SECRET)
    write(tmp_path / "tests" / "test_login.py", SECRET)

    result = analyze_project(str(tmp_path))

    security = [event for event in result["events"] if event["category"] == "security"]
    assert len(security) == 1
    assert "auth.py:1" in security[0]["evidence"]
    assert "test_login.py:1" in security[0]["evidence"]
    assert "vendor.py" not in security[0]["evidence"]
    assert result["project"]["file_count"] == 2
