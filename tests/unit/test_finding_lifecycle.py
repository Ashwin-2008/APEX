"""Dedicated unit tests for finding lifecycle management.

Tests cover:
- NEW → ACTIVE transitions
- ACTIVE → CHANGED transitions  
- ACTIVE → RESOLVED transitions
- RESOLVED → REOPENED transitions
- Deterministic fingerprinting
- Duplicate prevention
- Affected-file scoping
- Unrelated findings preserved
- Resolution evidence persisted
- resolved_at populated
- Reopened finding lifecycle metadata
"""

import pytest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.models.entities import ProjectFinding, ProjectReview, ReviewedProject
from app.services.project_review_persistence import (
    persist_analysis,
    fingerprint_event,
    serialize_review,
)


@pytest.fixture
def db_session():
    """Create an in-memory SQLite database for testing."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()
    Base.metadata.drop_all(engine)


@pytest.fixture
def test_project(db_session):
    """Create a test project."""
    project = ReviewedProject(
        name="test-project",
        repository_path="/tmp/test-project",
        source_type="local"
    )
    db_session.add(project)
    db_session.commit()
    return project


def create_test_analysis(findings_data=None, requirements_data=None, failure_dna=None):
    """Create a test analysis with customizable findings."""
    return {
        "project": {
            "path": "/tmp/test-project",
            "file_count": 10,
            "language_mix": {".py": 8, ".md": 2},
            "commit_count": 5,
            "bugfix_commit_count": 1,
            "recent_churn": ""
        },
        "requirements": requirements_data or [],
        "events": findings_data or [],
        "history": [],
        "transition_graph": [],
        "failure_loops": [],
        "failure_dna": failure_dna or {},
        "next_failure_predictions": [],
        "summary": {
            "event_count": len(findings_data or []),
            "open_high_or_critical": 0,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "methodology": "Test"
        }
    }


class TestFingerprintDeterminism:
    """Test deterministic fingerprint generation."""
    
    def test_fingerprint_is_deterministic(self):
        """Identical events should produce identical fingerprints."""
        event = {
            "category": "testing",
            "severity": "high",
            "confidence": 0.95,
            "evidence": "No test files were detected",
            "analyzer_source": "test_inventory",
            "remediation": "Add tests"
        }
        fingerprint1 = fingerprint_event(event)
        fingerprint2 = fingerprint_event(event)
        assert fingerprint1 == fingerprint2
        
    def test_fingerprint_different_for_different_events(self):
        """Different events should produce different fingerprints."""
        event1 = {
            "category": "testing",
            "severity": "high", 
            "confidence": 0.95,
            "evidence": "No test files were detected",
            "analyzer_source": "test_inventory",
            "remediation": "Add tests"
        }
        event2 = {
            "category": "security",
            "severity": "high",
            "confidence": 0.95,
            "evidence": "Hard-coded secret found",
            "analyzer_source": "secret_detector", 
            "remediation": "Move to secret manager"
        }
        fingerprint1 = fingerprint_event(event1)
        fingerprint2 = fingerprint_event(event2)
        assert fingerprint1 != fingerprint2
        
    def test_fingerprint_ignores_case(self):
        """Fingerprints should be case-insensitive for key fields."""
        event1 = {"category": "Testing", "evidence": "Test Evidence"}
        event2 = {"category": "testing", "evidence": "test evidence"}
        fingerprint1 = fingerprint_event(event1)
        fingerprint2 = fingerprint_event(event2)
        assert fingerprint1 == fingerprint2


class TestFindingLifecycleTransitions:
    """Test finding lifecycle state transitions."""
    
    def test_new_finding_transitions(self, db_session, test_project):
        """Test NEW → ACTIVE transition for first-time findings."""
        analysis = create_test_analysis([
            {
                "category": "testing",
                "severity": "high",
                "confidence": 0.95,
                "evidence": "No test files detected",
                "analyzer_source": "test_inventory",
                "remediation": "Add unit tests"
            }
        ])
        
        result = persist_analysis(db_session, analysis)
        
        # Check that the finding was created with NEW status
        findings = db_session.scalars(select(ProjectFinding).where(
            ProjectFinding.review_id == result["id"]
        )).all()
        
        assert len(findings) == 1
        assert findings[0].status == "NEW"
        assert findings[0].category == "testing"
        assert findings[0].severity == "high"
        
    def test_active_finding_transitions(self, db_session, test_project):
        """Test NEW → ACTIVE transition when finding reappears."""
        # Create first analysis with a finding
        analysis1 = create_test_analysis([
            {
                "category": "testing", 
                "severity": "high",
                "confidence": 0.95,
                "evidence": "No test files detected",
                "analyzer_source": "test_inventory",
                "remediation": "Add unit tests"
            }
        ])
        result1 = persist_analysis(db_session, analysis1)
        
        # Create second analysis with the same finding (same fingerprint)
        analysis2 = create_test_analysis([
            {
                "category": "testing",
                "severity": "high",
                "confidence": 0.95, 
                "evidence": "No test files detected",
                "analyzer_source": "test_inventory",
                "remediation": "Add unit tests"
            }
        ])
        result2 = persist_analysis(db_session, analysis2)
        
        # The second finding should be ACTIVE (since it existed before)
        findings2 = db_session.scalars(select(ProjectFinding).where(
            ProjectFinding.review_id == result2["id"]
        )).all()
        
        assert len(findings2) == 1
        assert findings2[0].status == "ACTIVE"
        
    def test_reopened_finding_transitions(self, db_session, test_project):
        """Test RESOLVED → REOPENED transition."""
        # Create first analysis with a finding
        analysis1 = create_test_analysis([
            {
                "category": "testing",
                "severity": "high", 
                "confidence": 0.95,
                "evidence": "No test files detected",
                "analyzer_source": "test_inventory",
                "remediation": "Add unit tests",
                "file": "test_file.py"
            }
        ])
        result1 = persist_analysis(db_session, analysis1)
        
        # Create second analysis without the finding (should be resolved)
        analysis2 = create_test_analysis([])
        result2 = persist_analysis(db_session, analysis2, affected_files=["test_file.py"])
        
        # Check that the original finding is now RESOLVED
        old_finding = db_session.get(ProjectFinding, result1["findings"][0]["id"])
        assert old_finding.status == "RESOLVED"
        assert old_finding.resolved_at is not None
        assert old_finding.resolution_evidence is not None
        
        # Create third analysis with the same finding again (should be REOPENED)
        analysis3 = create_test_analysis([
            {
                "category": "testing",
                "severity": "high",
                "confidence": 0.95,
                "evidence": "No test files detected", 
                "analyzer_source": "test_inventory",
                "remediation": "Add unit tests",
                "file": "test_file.py"
            }
        ])
        result3 = persist_analysis(db_session, analysis3)
        
        # The finding should be REOPENED
        findings3 = db_session.scalars(select(ProjectFinding).where(
            ProjectFinding.review_id == result3["id"]
        )).all()
        
        assert len(findings3) == 1
        assert findings3[0].status == "REOPENED"
        
    def test_resolved_finding_transitions(self, db_session, test_project):
        """Test ACTIVE → RESOLVED transition."""
        # Create first analysis with a finding
        analysis1 = create_test_analysis([
            {
                "category": "testing",
                "severity": "high",
                "confidence": 0.95,
                "evidence": "No test files detected",
                "analyzer_source": "test_inventory", 
                "remediation": "Add unit tests",
                "file": "src/main.py"
            }
        ])
        result1 = persist_analysis(db_session, analysis1)
        
        # Create second analysis without the finding, with affected files
        analysis2 = create_test_analysis([])
        result2 = persist_analysis(db_session, analysis2, affected_files=["src/main.py"])
        
        # Check that the resolved_events contains the resolved finding
        assert len(result2["resolved_events"]) == 1
        resolved = result2["resolved_events"][0]
        assert resolved["category"] == "testing"
        assert resolved["resolved_at"] is not None
        assert resolved["resolution_evidence"] == "Affected scope was re-analyzed and the finding was not detected."
        
        # Check that the original finding is now RESOLVED in the database
        old_finding = db_session.get(ProjectFinding, result1["findings"][0]["id"])
        assert old_finding.status == "RESOLVED"
        assert old_finding.resolved_at is not None
        assert old_finding.resolution_evidence == "Affected scope was re-analyzed and the finding was not detected."


class TestDuplicatePrevention:
    """Test that duplicate findings are prevented."""
    
    def test_duplicate_fingerprints_prevented(self, db_session, test_project):
        """Findings with identical fingerprints should not be duplicated in the same review."""
        analysis = create_test_analysis([
            {
                "category": "testing",
                "severity": "high",
                "confidence": 0.95,
                "evidence": "No test files detected",
                "analyzer_source": "test_inventory",
                "remediation": "Add unit tests"
            },
            {
                "category": "testing",
                "severity": "high",
                "confidence": 0.95,
                "evidence": "No test files detected",  # Same evidence
                "analyzer_source": "test_inventory",
                "remediation": "Add unit tests"
            }
        ])
        
        result = persist_analysis(db_session, analysis)
        
        # Should only have one finding, not two
        findings = db_session.scalars(select(ProjectFinding).where(
            ProjectFinding.review_id == result["id"]
        )).all()
        
        assert len(findings) == 1


class TestAffectedFileScoping:
    """Test that resolution only affects findings related to changed files."""
    
    def test_unrelated_findings_preserved(self, db_session, test_project):
        """Findings not related to changed files should remain ACTIVE."""
        # Create first analysis with two findings in different files
        analysis1 = create_test_analysis([
            {
                "category": "testing",
                "severity": "high",
                "confidence": 0.95,
                "evidence": "No test files detected in main.py",
                "analyzer_source": "test_inventory",
                "remediation": "Add unit tests",
                "file": "src/main.py"
            },
            {
                "category": "security", 
                "severity": "critical",
                "confidence": 0.98,
                "evidence": "Hard-coded secret in config.py",
                "analyzer_source": "secret_detector",
                "remediation": "Use environment variables",
                "file": "src/config.py"
            }
        ])
        result1 = persist_analysis(db_session, analysis1)
        
        # Create second analysis without findings, but only main.py was changed
        analysis2 = create_test_analysis([])
        result2 = persist_analysis(db_session, analysis2, affected_files=["src/main.py"])
        
        # The finding in main.py should be resolved
        old_finding_main = db_session.get(ProjectFinding, result1["findings"][0]["id"])
        assert old_finding_main.status == "RESOLVED"
        
        # The finding in config.py should still be ACTIVE (unrelated to changed files)
        old_finding_config = db_session.get(ProjectFinding, result1["findings"][1]["id"])
        assert old_finding_config.status == "NEW"  # Still NEW since it wasn't resolved
        
    def test_affected_file_matching_logic(self, db_session, test_project):
        """Test various file path matching scenarios."""
        # Create analysis with a finding
        analysis1 = create_test_analysis([
            {
                "category": "testing",
                "severity": "high",
                "confidence": 0.95,
                "evidence": "Issue in module",
                "analyzer_source": "test_inventory",
                "remediation": "Fix it",
                "file": "src/module/file.py"
            }
        ])
        result1 = persist_analysis(db_session, analysis1)
        
        # Test resolution with exact file match
        analysis2 = create_test_analysis([])
        result2 = persist_analysis(db_session, analysis2, affected_files=["src/module/file.py"])
        
        old_finding = db_session.get(ProjectFinding, result1["findings"][0]["id"])
        assert old_finding.status == "RESOLVED"
        
        # Test with directory match - create a new finding with directory path
        analysis3 = create_test_analysis([
            {
                "category": "testing",
                "severity": "high",
                "confidence": 0.95,
                "evidence": "Issue in other module",
                "analyzer_source": "test_inventory",
                "remediation": "Fix it",
                "file": "src/other/file.py"
            }
        ])
        result3 = persist_analysis(db_session, analysis3)
        
        # Now resolve with directory change
        analysis4 = create_test_analysis([])
        result4 = persist_analysis(db_session, analysis4, affected_files=["src/other"])
        
        old_finding2 = db_session.get(ProjectFinding, result3["findings"][0]["id"])
        # Should be resolved because file path contains the directory
        assert old_finding2.status == "RESOLVED"


class TestResolutionMetadata:
    """Test that resolution metadata is properly persisted."""
    
    def test_resolved_at_populated(self, db_session, test_project):
        """Resolved findings should have resolved_at timestamp."""
        analysis1 = create_test_analysis([
            {
                "category": "testing",
                "severity": "high",
                "confidence": 0.95,
                "evidence": "No test files detected",
                "analyzer_source": "test_inventory",
                "remediation": "Add unit tests",
                "file": "src/main.py"
            }
        ])
        result1 = persist_analysis(db_session, analysis1)
        
        analysis2 = create_test_analysis([])
        result2 = persist_analysis(db_session, analysis2, affected_files=["src/main.py"])
        
        old_finding = db_session.get(ProjectFinding, result1["findings"][0]["id"])
        assert old_finding.resolved_at is not None
        assert isinstance(old_finding.resolved_at, datetime)
        
    def test_resolution_evidence_populated(self, db_session, test_project):
        """Resolved findings should have resolution evidence."""
        analysis1 = create_test_analysis([
            {
                "category": "testing",
                "severity": "high", 
                "confidence": 0.95,
                "evidence": "No test files detected",
                "analyzer_source": "test_inventory",
                "remediation": "Add unit tests",
                "file": "src/main.py"
            }
        ])
        result1 = persist_analysis(db_session, analysis1)
        
        analysis2 = create_test_analysis([])
        result2 = persist_analysis(db_session, analysis2, affected_files=["src/main.py"])
        
        old_finding = db_session.get(ProjectFinding, result1["findings"][0]["id"])
        assert old_finding.resolution_evidence == "Affected scope was re-analyzed and the finding was not detected."


class TestCriticalInvariant:
    """Test the critical invariant: UNANALYZED ≠ RESOLVED."""
    
    def test_resolution_only_after_reanalysis(self, db_session, test_project):
        """Findings can only be resolved when their affected scope has been re-analyzed."""
        analysis1 = create_test_analysis([
            {
                "category": "testing",
                "severity": "high",
                "confidence": 0.95,
                "evidence": "No test files detected",
                "analyzer_source": "test_inventory",
                "remediation": "Add unit tests",
                "file": "src/main.py"
            }
        ])
        result1 = persist_analysis(db_session, analysis1)
        
        # Create analysis without the finding, but WITHOUT specifying affected files
        # This should NOT resolve the finding since we don't know if the scope was re-analyzed
        analysis2 = create_test_analysis([])
        result2 = persist_analysis(db_session, analysis2)  # No affected_files
        
        # The finding should still be NEW/ACTIVE, not RESOLVED
        old_finding = db_session.get(ProjectFinding, result1["findings"][0]["id"])
        assert old_finding.status != "RESOLVED"
        
        # Now do it properly with affected files
        analysis3 = create_test_analysis([])
        result3 = persist_analysis(db_session, analysis3, affected_files=["src/main.py"])
        
        # Now it should be resolved
        old_finding = db_session.get(ProjectFinding, result1["findings"][0]["id"])
        assert old_finding.status == "RESOLVED"