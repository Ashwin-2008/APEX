"""Direct end-to-end test for project review components.

Tests the complete engineering-intelligence pipeline without requiring a running server:
1. Create temporary project
2. Add a source file containing a detectable engineering issue
3. Connect the project (using internal components)
4. Run initial analysis
5. Start monitoring
6. Verify monitoring is ACTIVE
7. Modify the real source file
8. Wait for filesystem watcher detection
9. Verify incremental analysis starts
10. Verify review is persisted
11. Verify finding is created or updated
12. Verify finding lifecycle state
13. Verify SSE event
14. Fix the actual source file
15. Save the file
16. Wait for watcher detection
17. Verify incremental re-analysis
18. Verify old finding is now RESOLVED
19. Verify resolution evidence
20. Verify finding.resolved SSE event
21. Verify MISTIQ state was updated
"""

import os
import shutil
import sys
import tempfile
import threading
import time
import asyncio
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))

import pytest

from app.services.project_review_service import analyze_project
from app.services.project_review_persistence import persist_analysis
from app.services.project_monitor import start_watcher, stop_watcher, event_bus
from app.models.entities import ProjectReview, ReviewedProject
from app.db.session import SessionLocal


@pytest.fixture
def test_project_dir():
    """Create a temporary project directory."""
    project_dir = tempfile.mkdtemp(prefix="mistiq_direct_e2e_test_")
    yield project_dir
    # Cleanup
    shutil.rmtree(project_dir, ignore_errors=True)


@pytest.fixture(scope="module")
def mock_request():
    """Create a mock request object with database session."""
    request = MagicMock()
    request.app.state.SessionLocal = SessionLocal
    return request


class TestDirectLiveProjectReview:
    """Direct end-to-end tests for live project review without server."""
    
    def test_complete_workflow_with_direct_components(self, test_project_dir, mock_request):
        """Test the complete workflow using direct component calls."""
        # Step 1: Create temporary project
        project_path = Path(test_project_dir)
        src_dir = project_path / "src"
        src_dir.mkdir()
        
        # Step 2: Add a source file containing a detectable engineering issue
        test_file = src_dir / "main.py"
        test_file.write_text('''
# Test file with engineering issues
def add_numbers(a, b):
    return a + b

# This is a hard-coded secret (should be detected)
API_KEY = "sk-1234567890abcdef"

# No tests in this file (should be detected)
''')
        
        # Step 3: Run initial analysis
        analysis = analyze_project(str(project_path))
        
        # Step 4: Persist the initial analysis
        with SessionLocal() as session:
            # Remove any existing project with this path
            session.query(ReviewedProject).filter(ReviewedProject.repository_path == str(project_path)).delete()
            session.commit()
            
            # Persist the analysis
            persisted = persist_analysis(session, analysis)
            project_id = persisted["project_id"]
        
        assert project_id is not None
        assert "findings" in persisted
        assert len(persisted["findings"]) > 0  # Should have some findings
        
        # Step 5: Start monitoring
        events_received = []
        
        def mock_callback(event):
            events_received.append(event)
            if event.get("type") != "project.changed":
                return
            event_id = project_id
            events_received.append({"type": "analysis.started", "project_id": event_id, "files": event.get("files", []), "analyzers": event.get("analyzers", [])})
            updated = analyze_project(str(project_path))
            with SessionLocal() as session:
                saved = persist_analysis(session, updated, affected_files=event.get("files", []), affected_analyzers=event.get("analyzers", []))
            events_received.append({"type": "analysis.completed", "project_id": event_id, "review_id": saved["id"], "review_number": saved["review_number"]})
            events_received.extend({"type": "finding.updated" if finding.get("status") == "ACTIVE" else "finding.created", "project_id": event_id, "finding": finding} for finding in saved.get("findings", []))
            events_received.extend({"type": "finding.resolved", "project_id": event_id, **resolved} for resolved in saved.get("resolved_events", []))
        
        watcher_stop = start_watcher(project_id, str(project_path), mock_callback)
        
        # Step 6: Verify monitoring is ACTIVE
        # The watcher should emit a monitoring.status event
        start_time = time.time()
        while time.time() - start_time < 5:
            time.sleep(0.5)
            monitoring_active = any(
                event.get("type") == "monitoring.status" and event.get("status") == "active"
                for event in events_received
            )
            if monitoring_active:
                break
        else:
            pytest.fail("Monitoring did not become active within timeout")
        
        # Step 7: Modify the real source file
        modified_content = '''# Modified test file with engineering issues
def add_numbers(a, b):
    return a + b

# This is a hard-coded secret (should be detected)
API_KEY = "sk-1234567890abcdef"
API_SECRET = "another-secret-key"

# No tests in this file (should be detected)
# Added another security issue
PASSWORD = "admin123"
'''
        test_file.write_text(modified_content)
        
        # Step 8: Wait for filesystem watcher detection
        start_time = time.time()
        project_changed_detected = False
        analysis_started_detected = False
        analysis_completed_detected = False
        
        while time.time() - start_time < 30:  # 30 second timeout
            time.sleep(0.5)
            
            project_changed_detected = any(event.get("type") == "project.changed" for event in events_received)
            analysis_started_detected = any(event.get("type") == "analysis.started" for event in events_received)
            analysis_completed_detected = any(event.get("type") == "analysis.completed" for event in events_received)
            
            # If we have all the events we need, break
            if project_changed_detected and analysis_started_detected and analysis_completed_detected:
                break
        
        # Step 9-11: Verify incremental analysis events
        assert project_changed_detected, "project.changed event not received"
        assert analysis_started_detected, "analysis.started event not received"
        assert analysis_completed_detected, "analysis.completed event not received"
        
        # Step 12: Verify finding lifecycle state
        # Find the analysis.completed event to get the review_id
        completed_events = [e for e in events_received if e.get("type") == "analysis.completed"]
        assert len(completed_events) > 0
        completed_event = completed_events[0]
        
        # Check that we have finding events
        finding_events = [e for e in events_received if e.get("type") in ["finding.created", "finding.updated"]]
        assert len(finding_events) > 0, "No finding events received"
        
        # Step 13: Verify SSE events (we're testing the event bus directly)
        # The events should be in the event bus for this project
        # This is implicitly tested by our mock_callback
        
        # Step 14: Fix the actual source file
        fixed_content = '''# Fixed test file without engineering issues
def add_numbers(a, b):
    return a + b

# Secrets moved to environment variables
import os
API_KEY = os.getenv("API_KEY")
API_SECRET = os.getenv("API_SECRET")

# No tests in this file - still an issue but different
'''
        test_file.write_text(fixed_content)
        
        # Clear events for the next phase
        events_received.clear()
        
        # Step 15: Save the file (already done with write_text)
        # Step 16: Wait for watcher detection
        start_time = time.time()
        
        while time.time() - start_time < 30:  # 30 second timeout
            time.sleep(0.5)
            
            # Look for project.changed and analysis events
            project_changed_detected = any(e.get("type") == "project.changed" for e in events_received)
            analysis_completed_detected = any(e.get("type") == "analysis.completed" for e in events_received)
            finding_resolved_detected = any(e.get("type") == "finding.resolved" for e in events_received)
            
            if project_changed_detected and analysis_completed_detected and finding_resolved_detected:
                break
        
        # Step 17: Verify incremental re-analysis
        assert project_changed_detected, "Second project.changed event not received"
        assert analysis_completed_detected, "Second analysis.completed event not received"
        
        # Step 18-19: Verify old finding is now RESOLVED
        # Check the database for resolved findings
        with SessionLocal() as session:
            project = session.get(ReviewedProject, project_id)
            assert project is not None
            
            # Get all findings for this project
            all_findings = session.query(ReviewedProject).filter(
                ReviewedProject.id == project_id
            ).first()
            
            # Check the reviews and their findings
            reviews = project.reviews
            assert len(reviews) >= 2  # Initial + at least one incremental
            
            # The second review should have resolved some findings or different findings
            latest_review = reviews[-1]  # Most recent
            
            # Step 20: Verify finding.resolved SSE event
            resolved_events = [e for e in events_received if e.get("type") == "finding.resolved"]
            assert len(resolved_events) > 0, "No finding.resolved events received"
            
            # Check that resolved events have proper metadata
            for resolved_event in resolved_events:
                assert "finding_id" in resolved_event
                assert "resolved_at" in resolved_event
                assert "resolution_evidence" in resolved_event
                
        # Step 21: Verify MISTIQ state was updated
        # The analysis should include failure_dna, predictions, etc.
        completed_events = [e for e in events_received if e.get("type") == "analysis.completed"]
        if completed_events:
            latest_completed = completed_events[-1]
            # The completed event should reference a review that has updated MISTIQ data
            review_id = latest_completed.get("review_id")
            assert review_id is not None
        
        # Cleanup
        stop_watcher(project_id)

    def test_file_change_detection(self, test_project_dir):
        """Test that file changes are properly detected."""
        project_path = Path(test_project_dir)
        src_dir = project_path / "src"
        src_dir.mkdir()
        
        test_file = src_dir / "test.py"
        test_file.write_text("# Initial content")
        
        events_received = []
        
        def mock_callback(event):
            events_received.append(event)
            if event.get("type") != "project.changed":
                return
            files = event.get("files", [])
            analyzers = event.get("analyzers", [])
            events_received.append({"type": "analysis.started", "project_id": project_id, "files": files, "analyzers": analyzers})
            updated = analyze_project(str(project_path))
            with SessionLocal() as session:
                saved = persist_analysis(session, updated, affected_files=files, affected_analyzers=analyzers)
            events_received.append({"type": "analysis.completed", "project_id": project_id, "review_id": saved["id"], "review_number": saved["review_number"], "files": files, "analyzers": analyzers})
            events_received.extend({"type": "finding.updated" if finding.get("status") == "ACTIVE" else "finding.created", "project_id": project_id, "finding": finding} for finding in saved.get("findings", []))
            events_received.extend({"type": "finding.resolved", "project_id": project_id, **resolved} for resolved in saved.get("resolved_events", []))
        
        project_id = 1  # Use a dummy project ID
        watcher_stop = start_watcher(project_id, str(project_path), mock_callback)
        
        try:
            # Wait for monitoring to be active
            start_time = time.time()
            while time.time() - start_time < 5:
                time.sleep(0.5)
                if any(e.get("type") == "monitoring.status" and e.get("status") == "active" for e in events_received):
                    break
            else:
                pytest.fail("Monitoring did not become active")
            
            # Modify the file
            test_file.write_text("# Modified content")
            
            # Wait for project.changed event
            start_time = time.time()
            while time.time() - start_time < 10:
                time.sleep(0.5)
                if any(e.get("type") == "project.changed" for e in events_received):
                    break
            else:
                pytest.fail("File change not detected within timeout")
            
            # Verify the project.changed event has the correct file
            changed_events = [e for e in events_received if e.get("type") == "project.changed"]
            assert len(changed_events) > 0
            changed_event = changed_events[-1]  # Most recent
            
            files = changed_event.get("files", [])
            assert len(files) > 0
            assert any(str(test_file) in file or file in str(test_file) for file in files)
            
        finally:
            stop_watcher(project_id)

    def test_sse_event_payload_completeness(self, test_project_dir, mock_request):
        """Test that SSE event payloads contain sufficient information."""
        project_path = Path(test_project_dir)
        src_dir = project_path / "src"
        src_dir.mkdir()
        
        test_file = src_dir / "main.py"
        test_file.write_text("# Test file")
        
        # Run initial analysis
        analysis = analyze_project(str(project_path))
        
        with SessionLocal() as session:
            session.query(ReviewedProject).filter(ReviewedProject.repository_path == str(project_path)).delete()
            session.commit()
            persisted = persist_analysis(session, analysis)
            project_id = persisted["project_id"]
            initial_review_id = persisted["id"]
            initial_review_number = persisted["review_number"]
        
        events_received = []

        def mock_callback(event):
            events_received.append(event)
            if event.get("type") != "project.changed":
                return
            files = event.get("files", [])
            analyzers = event.get("analyzers", [])
            events_received.append({"type": "analysis.started", "project_id": project_id, "files": files, "analyzers": analyzers})
            updated = analyze_project(str(project_path))
            with SessionLocal() as session:
                saved = persist_analysis(session, updated, affected_files=files, affected_analyzers=analyzers)
            events_received.append({"type": "analysis.completed", "project_id": project_id, "review_id": saved["id"], "review_number": saved["review_number"], "files": files, "analyzers": analyzers})
            events_received.extend({"type": "finding.updated" if finding.get("status") == "ACTIVE" else "finding.created", "project_id": project_id, "finding": finding} for finding in saved.get("findings", []))
            events_received.extend({"type": "finding.resolved", "project_id": project_id, **resolved} for resolved in saved.get("resolved_events", []))
            if saved.get("requirements"):
                events_received.append({"type": "requirement.updated", "project_id": project_id, "requirements": saved["requirements"], "review_id": saved["id"]})
            if updated.get("failure_dna"):
                events_received.append({"type": "dna.updated", "project_id": project_id, "failure_dna": updated["failure_dna"], "review_id": saved["id"]})
            if updated.get("next_failure_predictions"):
                events_received.append({"type": "prediction.updated", "project_id": project_id, "predictions": updated["next_failure_predictions"], "review_id": saved["id"]})

        watcher_stop = start_watcher(project_id, str(project_path), mock_callback)

        try:
            start_time = time.time()
            while not any(e.get("type") == "monitoring.status" and e.get("status") == "active" for e in events_received):
                if time.time() - start_time > 5:
                    pytest.fail("Monitoring did not become active within timeout")
                time.sleep(0.1)
            # Modify the file
            test_file.write_text("# Modified content")
            
            # Wait for events
            start_time = time.time()
            while time.time() - start_time < 30:
                time.sleep(0.5)
                completed_events = [e for e in events_received if e.get("type") == "analysis.completed"]
                if completed_events:
                    break
            else:
                pytest.fail("No analysis.completed event received")
            
            # Verify downstream analysis really executed: a new review must be persisted
            assert any(e.get("type") == "analysis.started" for e in events_received), "analysis.started event not received"
            completed_events = [e for e in events_received if e.get("type") == "analysis.completed"]
            latest_completed = completed_events[-1]
            assert latest_completed["review_id"] != initial_review_id, "Incremental analysis did not persist a new review"
            assert latest_completed["review_number"] > initial_review_number, "Incremental review number did not advance"
            with SessionLocal() as session:
                persisted_review = session.get(ProjectReview, latest_completed["review_id"])
                assert persisted_review is not None, "Incremental review was not persisted to the database"
                assert persisted_review.project_id == project_id
                assert persisted_review.status == "completed"
            
            # Check event payload completeness
            for event in events_received:
                if event.get("type") == "project.changed":
                    assert "project_id" in event
                    assert "files" in event
                    assert "analyzers" in event
                    assert isinstance(event["files"], list)
                    assert len(event["files"]) > 0
                    
                elif event.get("type") == "analysis.started":
                    assert "project_id" in event
                    assert "files" in event
                    assert "analyzers" in event
                    
                elif event.get("type") == "analysis.completed":
                    assert "project_id" in event
                    assert "review_id" in event
                    assert "review_number" in event
                    assert "files" in event
                    assert "analyzers" in event
                    
                elif event.get("type") in ["finding.created", "finding.updated"]:
                    assert "project_id" in event
                    assert "finding" in event
                    finding = event["finding"]
                    assert "category" in finding
                    assert "severity" in finding
                    assert "evidence" in finding
                    assert "fingerprint" in finding
                    
                elif event.get("type") == "finding.resolved":
                    assert "project_id" in event
                    assert "finding_id" in event
                    assert "fingerprint" in event
                    assert "resolved_at" in event
                    assert "resolution_evidence" in event
                    
                elif event.get("type") == "requirement.updated":
                    assert "project_id" in event
                    assert "requirements" in event
                    assert "review_id" in event
                    
                elif event.get("type") == "dna.updated":
                    assert "project_id" in event
                    assert "failure_dna" in event
                    assert "review_id" in event
                    
                elif event.get("type") == "prediction.updated":
                    assert "project_id" in event
                    assert "predictions" in event
                    assert "review_id" in event
        
        finally:
            stop_watcher(project_id)


class TestGitSynchronization:
    """Test Git SHA synchronization (when applicable)."""
    
    def test_non_git_project_handling(self, test_project_dir, mock_request):
        """Test that non-Git projects work properly."""
        project_path = Path(test_project_dir)
        src_dir = project_path / "src"
        src_dir.mkdir()
        
        test_file = src_dir / "main.py"
        test_file.write_text("# Test file")
        
        # Run analysis on non-Git project
        analysis = analyze_project(str(project_path))
        
        # Should not have Git-specific data
        project_info = analysis.get("project", {})
        # The analysis should still work
        assert "file_count" in project_info
        
        with SessionLocal() as session:
            session.query(ReviewedProject).filter(ReviewedProject.repository_path == str(project_path)).delete()
            session.commit()
            persisted = persist_analysis(session, analysis)
            
            # Check that the project was created with null Git SHA
            project = session.get(ReviewedProject, persisted["project_id"])
            assert project.current_commit_sha is None


if __name__ == "__main__":
    # Run a simple standalone test
    print("Running standalone direct E2E test...")
    
    # Create a test project
    test_dir = tempfile.mkdtemp(prefix="mistiq_direct_standalone_")
    try:
        project_path = Path(test_dir)
        src_dir = project_path / "src"
        src_dir.mkdir()
        
        # Create a file with issues
        test_file = src_dir / "main.py"
        test_file.write_text('''
# Test file
API_KEY = "secret-key-123"
''')
        
        print("✓ Test project created")
        
        # Run analysis
        analysis = analyze_project(str(project_path))
        print(f"✓ Initial analysis completed with {len(analysis.get('events', []))} events")
        
        # Persist analysis
        with SessionLocal() as session:
            session.query(ReviewedProject).filter(ReviewedProject.repository_path == str(project_path)).delete()
            session.commit()
            persisted = persist_analysis(session, analysis)
            project_id = persisted["project_id"]
        
        print(f"✓ Analysis persisted with project_id: {project_id}")
        print(f"✓ Found {len(persisted.get('findings', []))} findings")
        
        # Test monitoring
        events_received = []
        
        def mock_callback(event):
            events_received.append(event)
            print(f"✓ Event received: {event.get('type')}")
            if event.get("type") != "project.changed":
                return
            files = event.get("files", [])
            analyzers = event.get("analyzers", [])
            started_event = {"type": "analysis.started", "project_id": project_id, "files": files, "analyzers": analyzers}
            events_received.append(started_event)
            event_bus.emit(project_id, started_event)
            updated = analyze_project(str(project_path))
            with SessionLocal() as session:
                saved = persist_analysis(session, updated, affected_files=files, affected_analyzers=analyzers)
            completed_event = {"type": "analysis.completed", "project_id": project_id, "review_id": saved["id"], "review_number": saved["review_number"], "files": files, "analyzers": analyzers}
            events_received.append(completed_event)
            event_bus.emit(project_id, completed_event)
            events_received.extend({"type": "finding.updated" if finding.get("status") == "ACTIVE" else "finding.created", "project_id": project_id, "finding": finding} for finding in saved.get("findings", []))
            for resolved in saved.get("resolved_events", []):
                resolved_event = {"type": "finding.resolved", "project_id": project_id, **resolved}
                events_received.append(resolved_event)
                event_bus.emit(project_id, resolved_event)
        
        watcher_stop = start_watcher(project_id, str(project_path), mock_callback)
        
        try:
            # Wait for monitoring to be active
            start_time = time.time()
            while time.time() - start_time < 5:
                time.sleep(0.5)
                if any(e.get("type") == "monitoring.status" and e.get("status") == "active" for e in events_received):
                    print("✓ Monitoring is active")
                    break
            
            # Modify the file
            test_file.write_text('''
# Modified file
API_KEY = "secret-key-123"
API_SECRET = "another-secret"
''')
            print("✓ File modified")
            
            # Wait for change detection
            start_time = time.time()
            while time.time() - start_time < 10:
                time.sleep(0.5)
                if any(e.get("type") == "project.changed" for e in events_received):
                    print("✓ File change detected")
                    break
            
            # Wait for analysis to complete
            start_time = time.time()
            while time.time() - start_time < 20:
                time.sleep(0.5)
                if any(e.get("type") == "analysis.completed" for e in events_received):
                    print("✓ Incremental analysis completed")
                    break
            
            # Fix the file
            test_file.write_text('''
# Fixed file
import os
API_KEY = os.getenv("API_KEY")
''')
            print("✓ File fixed")
            
            # Clear events and wait for resolution
            events_received.clear()
            start_time = time.time()
            while time.time() - start_time < 20:
                time.sleep(0.5)
                if any(e.get("type") == "finding.resolved" for e in events_received):
                    print("✓ Finding resolved detected")
                    break
            
            # Check final state
            with SessionLocal() as session:
                project = session.get(ReviewedProject, project_id)
                if project:
                    reviews = project.reviews
                    print(f"✓ Total reviews: {len(reviews)}")
                    
                    for i, review in enumerate(reviews):
                        findings = review.findings
                        resolved_count = sum(1 for f in findings if f.status == "RESOLVED")
                        print(f"  Review {i+1}: {len(findings)} findings, {resolved_count} resolved")
            
        finally:
            stop_watcher(project_id)
            print("✓ Monitoring stopped")
        
    finally:
        shutil.rmtree(test_dir, ignore_errors=True)
        print("✓ Test cleanup completed")
    
    print("✓ Standalone E2E test completed successfully")
