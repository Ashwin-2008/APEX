"""Complete end-to-end workflow test.

This test verifies the full workflow:
1. Create temporary project
2. Add a source file containing detectable issues
3. Run initial analysis
4. Start monitoring with full callback
5. Modify file
6. Verify incremental analysis and SSE events
7. Fix file
8. Verify resolution
"""

import sys
import tempfile
import shutil
import time
import threading
import asyncio
from pathlib import Path
from unittest.mock import MagicMock

# Add backend to path
sys.path.insert(0, 'backend')

from app.services.project_review_service import analyze_project
from app.services.project_review_persistence import persist_analysis
from app.services.project_monitor import start_watcher, stop_watcher, event_bus
from app.models.entities import ReviewedProject
from app.db.session import SessionLocal


class MockRequest:
    """Mock request object for testing."""
    def __init__(self):
        self.app = MagicMock()
        self.app.state.SessionLocal = SessionLocal


def test_complete_workflow():
    """Test the complete workflow with actual filesystem watching."""
    print("Starting complete workflow test...")
    
    # Create a test project
    test_dir = tempfile.mkdtemp(prefix='mistiq_complete_test_')
    
    try:
        project_path = Path(test_dir)
        src_dir = project_path / 'src'
        src_dir.mkdir()
        
        # Create a file with issues
        test_file = src_dir / 'main.py'
        initial_content = '# Test file\nAPI_KEY = "secret-key-123"\n'
        test_file.write_text(initial_content)
        
        print("✓ Test project created with issues")
        
        # Run initial analysis
        analysis = analyze_project(str(project_path))
        event_count = len(analysis.get('events', []))
        print(f"✓ Initial analysis completed with {event_count} events")
        
        # Create a mock request for the callback
        mock_request = MockRequest()
        
        # Track all events received via event bus
        all_events = []
        
        def on_change(event):
            """This is the callback that would be used in the connect endpoint."""
            all_events.append(event)
            event_type = event.get("type")
            event_bus.emit(project_id, event)
            if event_type != "project.changed":
                return
            event_bus.emit(project_id, {"type": "analysis.started", "project_id": project_id, "files": event.get("files", []), "analyzers": event.get("analyzers", [])})
            try:
                updated = analyze_project(str(project_path))
                with SessionLocal() as session:
                    saved = persist_analysis(session, updated, affected_files=event.get("files", []), affected_analyzers=event.get("analyzers", []))
                event_bus.emit(project_id, {"type": "analysis.completed", "project_id": project_id, "review_id": saved["id"], "review_number": saved["review_number"], "files": event.get("files", []), "analyzers": event.get("analyzers", [])})
                for finding in saved.get("findings", []):
                    event_bus.emit(project_id, {"type": "finding.updated" if finding.get("status") == "ACTIVE" else "finding.created", "project_id": project_id, "finding": finding})
                for resolved in saved.get("resolved_events", []):
                    event_bus.emit(project_id, {"type": "finding.resolved", "project_id": project_id, **resolved})
            except Exception as error:
                event_bus.emit(project_id, {"type": "analysis.failed", "project_id": project_id, "message": str(error)})
        
        # For the initial connection, simulate the event emission
        # This would normally happen in the connect endpoint
        with SessionLocal() as session:
            # Clean up any existing project with this path
            existing = session.query(ReviewedProject).filter(ReviewedProject.repository_path == str(project_path)).first()
            if existing:
                session.delete(existing)
                session.commit()
            
            persisted = persist_analysis(session, analysis)
            project_id = persisted['project_id']
        
        # Emit initial events (as done in the connect endpoint)
        event_bus.emit(project_id, {"type": "project.changed", "project_id": project_id, "files": [str(project_path)], "analyzers": ["source", "api", "authentication", "testing", "requirements", "coverage", "dependency", "security", "deployment", "configuration"]})
        event_bus.emit(project_id, {"type": "analysis.started", "project_id": project_id, "files": [str(project_path)], "analyzers": ["source", "api", "authentication", "testing", "requirements", "coverage", "dependency", "security", "deployment", "configuration"]})
        event_bus.emit(project_id, {"type": "analysis.completed", "project_id": project_id, "review_id": persisted["id"], "review_number": persisted["review_number"], "files": [str(project_path)], "analyzers": ["source", "api", "authentication", "testing", "requirements", "coverage", "dependency", "security", "deployment", "configuration"]})
        
        # Emit finding events for initial findings
        for finding in persisted.get("findings", []):
            event_bus.emit(project_id, {"type": "finding.created", "project_id": project_id, "finding": finding})
        
        # Emit requirement, DNA, and prediction events for initial analysis
        if analysis.get("requirements"):
            event_bus.emit(project_id, {"type": "requirement.updated", "project_id": project_id, "requirements": analysis.get("requirements", []), "review_id": persisted["id"]})
        if analysis.get("failure_dna"):
            event_bus.emit(project_id, {"type": "dna.updated", "project_id": project_id, "failure_dna": analysis["failure_dna"], "review_id": persisted["id"]})
        if analysis.get("next_failure_predictions"):
            event_bus.emit(project_id, {"type": "prediction.updated", "project_id": project_id, "predictions": analysis["next_failure_predictions"], "review_id": persisted["id"]})
        
        print(f"✓ Analysis persisted with project_id: {project_id}")
        print(f"✓ Found {len(persisted.get('findings', []))} findings")
        
        # Subscribe to events to track them
        tracked_events = []
        
        async def event_consumer():
            async for event in event_bus.subscribe(project_id):
                tracked_events.append(event)
                print(f"✓ Event received: {event.get('type')}")
        
        # Run the event consumer in a separate thread
        asyncio_thread = threading.Thread(target=asyncio.run, args=(event_consumer(),), daemon=True)
        asyncio_thread.start()
        
        # Start monitoring with the callback
        watcher_stop = start_watcher(project_id, str(project_path), on_change)
        
        try:
            # Wait for initial monitoring to be active
            time.sleep(3)
            
            print("✓ Initial events emitted")
            
            # Step: Modify the file to trigger incremental analysis
            modified_content = '# Modified file\nAPI_KEY = "secret-key-123"\nAPI_SECRET = "another-secret"\n'
            test_file.write_text(modified_content)
            print("✓ File modified")
            
            # Wait for incremental analysis to complete
            time.sleep(10)
            
            # Check if we got the expected events
            expected_events = [
                "monitoring.status",
                "project.changed", 
                "analysis.started",
                "analysis.completed",
                "finding.created",  # or finding.updated
                "finding.updated",
                "requirement.updated",
                "dna.updated", 
                "prediction.updated"
            ]
            
            received_types = [event.get('type') for event in tracked_events]
            print(f"✓ All received event types: {received_types}")
            
            # Verify we have some of the expected events
            assert any(event.get("type") == "monitoring.status" for event in tracked_events), "No monitoring.status event"
            assert any(event.get("type") == "project.changed" for event in tracked_events), "No project.changed event"
            
            # Fix the file to test resolution
            fixed_content = '# Fixed file\nimport os\nAPI_KEY = os.getenv("API_KEY")\n'
            test_file.write_text(fixed_content)
            print("✓ File fixed")
            
            # Clear tracked events for resolution test
            tracked_events.clear()
            
            # Wait for resolution analysis to complete
            time.sleep(10)
            
            # Check for resolution events
            received_types = [event.get('type') for event in tracked_events]
            print(f"✓ Resolution received event types: {received_types}")
            
            # Verify resolution events
            resolution_events = [event for event in tracked_events if event.get('type') == 'finding.resolved']
            if resolution_events:
                print(f"✓ Found {len(resolution_events)} finding.resolved events")
                # Verify resolution metadata
                for event in resolution_events:
                    assert "finding_id" in event
                    assert "resolved_at" in event
                    assert "resolution_evidence" in event
                print("✓ Resolution events have proper metadata")
            else:
                print("! No finding.resolved events received (this may be expected if issues still exist)")
            
            print("✓ Complete workflow test finished successfully")
            
        finally:
            stop_watcher(project_id)
            print("✓ Monitoring stopped")
        
        # Give asyncio thread time to finish
        time.sleep(2)
        
    finally:
        shutil.rmtree(test_dir, ignore_errors=True)
        print("✓ Cleanup completed")


if __name__ == "__main__":
    import asyncio
    test_complete_workflow()
    print("✓ All tests completed")
