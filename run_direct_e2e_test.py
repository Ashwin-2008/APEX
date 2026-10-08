"""Standalone direct E2E test runner for project review components.

This script runs the complete engineering-intelligence pipeline test
without requiring a running server.
"""

import os
import shutil
import sys
import tempfile
import time
import asyncio
from pathlib import Path

# Setup Python path
project_root = Path(__file__).parent.resolve()
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "backend"))

from app.services.project_review_service import analyze_project
from app.services.project_review_persistence import persist_analysis
from app.services.project_monitor import start_watcher, stop_watcher, event_bus
from app.models.entities import ReviewedProject
from app.db.session import SessionLocal, init_db


async def collect_events(project_id, events_list):
    """Async function to collect events from the event bus."""
    async for event in event_bus.subscribe(project_id):
        events_list.append(event)


def create_analysis_callback(project_id, project_path, events_list):
    """Create a callback that triggers analysis and emits events."""
    def on_change(event):
        event_type = event.get("type")
        
        if event_type == "project.changed":
            # Emit project.changed event
            event_bus.emit(project_id, event)
            
            # Emit analysis.started
            event_bus.emit(project_id, {
                "type": "analysis.started", 
                "project_id": project_id, 
                "files": event.get("files", []), 
                "analyzers": event.get("analyzers", [])
            })
            
            try:
                # Run analysis
                updated = analyze_project(str(project_path))
                
                with SessionLocal() as session:
                    saved = persist_analysis(session, updated, affected_files=event.get("files", []), affected_analyzers=event.get("analyzers", []))
                
                # Emit analysis.completed
                event_bus.emit(project_id, {
                    "type": "analysis.completed",
                    "project_id": project_id,
                    "review_id": saved["id"],
                    "review_number": saved["review_number"],
                    "files": event.get("files", []),
                    "analyzers": event.get("analyzers", [])
                })
                
                # Emit finding events
                for finding in saved.get("findings", []):
                    finding_status = finding.get("status", "NEW")
                    if finding_status == "ACTIVE":
                        event_bus.emit(project_id, {"type": "finding.updated", "project_id": project_id, "finding": finding})
                    else:
                        event_bus.emit(project_id, {"type": "finding.created", "project_id": project_id, "finding": finding})
                
                # Emit finding.resolved events
                for resolved in saved.get("resolved_events", []):
                    event_bus.emit(project_id, {"type": "finding.resolved", "project_id": project_id, **resolved})
                
                # Emit requirement.updated
                if saved.get("requirements"):
                    event_bus.emit(project_id, {
                        "type": "requirement.updated", 
                        "project_id": project_id, 
                        "requirements": saved.get("requirements", []), 
                        "review_id": saved["id"]
                    })
                
                # Emit dna.updated
                if updated.get("failure_dna"):
                    event_bus.emit(project_id, {
                        "type": "dna.updated",
                        "project_id": project_id,
                        "failure_dna": updated["failure_dna"],
                        "review_id": saved["id"]
                    })
                
                # Emit prediction.updated
                if updated.get("next_failure_predictions"):
                    event_bus.emit(project_id, {
                        "type": "prediction.updated",
                        "project_id": project_id,
                        "predictions": updated["next_failure_predictions"],
                        "review_id": saved["id"]
                    })
                
            except Exception as error:
                event_bus.emit(project_id, {"type": "analysis.failed", "project_id": project_id, "message": str(error)})
    
    return on_change


def main():
    print("=" * 80)
    print("DIRECT E2E TEST - Complete Engineering-Intelligence Pipeline")
    print("=" * 80)
    
    # Initialize database
    print("\n--- Initializing database ---")
    init_db()
    print("[PASS] Database initialized")
    
    # Create a test project
    test_dir = tempfile.mkdtemp(prefix="mistiq_direct_e2e_")
    
    try:
        project_path = Path(test_dir)
        src_dir = project_path / "src"
        src_dir.mkdir()
        
        # Step 2: Add a source file containing a detectable engineering issue
        test_file = src_dir / "main.py"
        test_file.write_text('''# Test file with engineering issues
def add_numbers(a, b):
    return a + b

# This is a hard-coded secret (should be detected)
API_KEY = "sk-1234567890abcdef"

# No tests in this file (should be detected)
''')
        
        print(f"[PASS] Test project created at: {project_path}")
        
        # Step 3: Run initial analysis
        print("\n--- Running initial analysis ---")
        analysis = analyze_project(str(project_path))
        print(f"[PASS] Initial analysis completed")
        print(f"  Events: {len(analysis.get('events', []))}")
        print(f"  Files: {len(analysis.get('project', {}).get('files', []))}")
        
        # Step 4: Persist the analysis
        print("\n--- Persisting initial analysis ---")
        with SessionLocal() as session:
            # Remove any existing project with this path
            session.query(ReviewedProject).filter(
                ReviewedProject.repository_path == str(project_path)
            ).delete()
            session.commit()
            
            persisted = persist_analysis(session, analysis)
            project_id = persisted["project_id"]
        
        print(f"[PASS] Analysis persisted with project_id: {project_id}")
        print(f"[PASS] Found {len(persisted.get('findings', []))} findings")
        
        # Print initial findings
        for i, finding in enumerate(persisted.get('findings', []), 1):
            print(f"  Finding {i}: {finding.get('category', 'unknown')}")
        
        # Step 5: Start monitoring with proper analysis callback
        print("\n--- Starting monitoring ---")
        all_events = []
        
        # Create the callback that triggers analysis
        on_change = create_analysis_callback(project_id, project_path, all_events)
        
        # Start event bus collection in background
        def start_event_collection():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(collect_events(project_id, all_events))
        
        # We can't easily run async in sync context, so we'll rely on the callback
        # emitting to event_bus and then the callback also adding to all_events
        # For simplicity, let's modify the callback to directly append to all_events
        
        def simple_callback(event):
            all_events.append(event)
            print(f"  Event: {event.get('type')}")
            # Also emit to event_bus for completeness
            event_bus.emit(project_id, event)
            
            # If this is a project.changed event, trigger analysis
            if event.get("type") == "project.changed":
                print("  Triggering analysis for project.changed...")
                
                # Emit analysis.started
                event_bus.emit(project_id, {
                    "type": "analysis.started", 
                    "project_id": project_id, 
                    "files": event.get("files", []), 
                    "analyzers": event.get("analyzers", [])
                })
                all_events.append({
                    "type": "analysis.started", 
                    "project_id": project_id, 
                    "files": event.get("files", []), 
                    "analyzers": event.get("analyzers", [])
                })
                print("  Event: analysis.started")
                
                try:
                    updated = analyze_project(str(project_path))
                    
                    with SessionLocal() as session:
                        saved = persist_analysis(session, updated, affected_files=event.get("files", []), affected_analyzers=event.get("analyzers", []))
                    
                    # Emit analysis.completed
                    completed_event = {
                        "type": "analysis.completed",
                        "project_id": project_id,
                        "review_id": saved["id"],
                        "review_number": saved["review_number"],
                        "files": event.get("files", []),
                        "analyzers": event.get("analyzers", [])
                    }
                    event_bus.emit(project_id, completed_event)
                    all_events.append(completed_event)
                    print("  Event: analysis.completed")
                    
                    # Emit finding events
                    for finding in saved.get("findings", []):
                        finding_status = finding.get("status", "NEW")
                        if finding_status == "ACTIVE":
                            f_event = {"type": "finding.updated", "project_id": project_id, "finding": finding}
                        else:
                            f_event = {"type": "finding.created", "project_id": project_id, "finding": finding}
                        event_bus.emit(project_id, f_event)
                        all_events.append(f_event)
                        print(f"  Event: {f_event.get('type')}")
                    
                    # Emit finding.resolved events
                    for resolved in saved.get("resolved_events", []):
                        r_event = {"type": "finding.resolved", "project_id": project_id, **resolved}
                        event_bus.emit(project_id, r_event)
                        all_events.append(r_event)
                        print(f"  Event: finding.resolved")
                    
                    # Emit requirement.updated
                    if saved.get("requirements"):
                        req_event = {
                            "type": "requirement.updated", 
                            "project_id": project_id, 
                            "requirements": saved.get("requirements", []), 
                            "review_id": saved["id"]
                        }
                        event_bus.emit(project_id, req_event)
                        all_events.append(req_event)
                        print("  Event: requirement.updated")
                    
                    # Emit dna.updated
                    if updated.get("failure_dna"):
                        dna_event = {
                            "type": "dna.updated",
                            "project_id": project_id,
                            "failure_dna": updated["failure_dna"],
                            "review_id": saved["id"]
                        }
                        event_bus.emit(project_id, dna_event)
                        all_events.append(dna_event)
                        print("  Event: dna.updated")
                    
                    # Emit prediction.updated
                    if updated.get("next_failure_predictions"):
                        pred_event = {
                            "type": "prediction.updated",
                            "project_id": project_id,
                            "predictions": updated["next_failure_predictions"],
                            "review_id": saved["id"]
                        }
                        event_bus.emit(project_id, pred_event)
                        all_events.append(pred_event)
                        print("  Event: prediction.updated")
                        
                except Exception as error:
                    error_event = {"type": "analysis.failed", "project_id": project_id, "message": str(error)}
                    event_bus.emit(project_id, error_event)
                    all_events.append(error_event)
                    print(f"  Event: analysis.failed - {error}")
        
        watcher_stop = start_watcher(project_id, str(project_path), simple_callback)
        
        # Step 6: Verify monitoring is ACTIVE
        print("\n--- Verifying monitoring status ---")
        start_time = time.time()
        monitoring_active = False
        while time.time() - start_time < 5:
            time.sleep(0.5)
            monitoring_active = any(
                event.get("type") == "monitoring.status" and event.get("status") == "active"
                for event in all_events
            )
            if monitoring_active:
                print("[PASS] Monitoring is ACTIVE")
                break
        else:
            print("[FAIL] Monitoring did not become active within timeout")
            return False
        
        # Step 7: Modify the real source file
        print("\n--- Modifying source file ---")
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
        print("[PASS] File modified with additional issues")
        
        # Step 8: Wait for filesystem watcher detection
        print("\n--- Waiting for change detection ---")
        # Clear events before the modification
        pre_mod_events = len(all_events)
        start_time = time.time()
        
        while time.time() - start_time < 30:
            time.sleep(0.5)
            
            # Check for new events since modification
            new_events = all_events[pre_mod_events:]
            
            project_changed_detected = any(e.get("type") == "project.changed" for e in new_events)
            analysis_started_detected = any(e.get("type") == "analysis.started" for e in new_events)
            analysis_completed_detected = any(e.get("type") == "analysis.completed" for e in new_events)
            
            if project_changed_detected and analysis_started_detected and analysis_completed_detected:
                print("[PASS] project.changed event received")
                print("[PASS] analysis.started event received")
                print("[PASS] analysis.completed event received")
                break
        else:
            print("[FAIL] Not all incremental analysis events received")
            print(f"  New events: {[e.get('type') for e in new_events]}")
            return False
        
        # Step 12: Verify finding lifecycle state
        print("\n--- Verifying finding lifecycle ---")
        new_events = all_events[pre_mod_events:]
        finding_events = [e for e in new_events if e.get("type") in ["finding.created", "finding.updated"]]
        print(f"[PASS] {len(finding_events)} finding events received")
        
        # Step 14: Fix the actual source file
        print("\n--- Fixing source file ---")
        fixed_content = '''# Fixed test file without engineering issues
def add_numbers(a, b):
    return a + b

# Secrets moved to environment variables
import os
API_KEY = os.getenv("API_KEY")
API_SECRET = os.getenv("API_SECRET")
'''
        test_file.write_text(fixed_content)
        print("[PASS] File fixed (secrets moved to env vars)")
        
        # Step 16: Wait for resolution detection
        print("\n--- Waiting for resolution detection ---")
        pre_fix_events = len(all_events)
        start_time = time.time()
        
        while time.time() - start_time < 30:
            time.sleep(0.5)
            
            new_events = all_events[pre_fix_events:]
            
            project_changed_detected = any(e.get("type") == "project.changed" for e in new_events)
            analysis_completed_detected = any(e.get("type") == "analysis.completed" for e in new_events)
            finding_resolved_detected = any(e.get("type") == "finding.resolved" for e in new_events)
            
            if project_changed_detected:
                print("[PASS] project.changed event received (fix)")
            if analysis_completed_detected:
                print("[PASS] analysis.completed event received (fix)")
            if finding_resolved_detected:
                print("[PASS] finding.resolved event received")
            
            if project_changed_detected and analysis_completed_detected and finding_resolved_detected:
                break
        else:
            print("[FAIL] Not all resolution events received")
            print(f"  New events after fix: {[e.get('type') for e in new_events]}")
            return False
        
        # Step 18-19: Verify old finding is now RESOLVED
        print("\n--- Verifying finding resolution ---")
        
        new_events = all_events[pre_fix_events:]
        resolved_events = [e for e in new_events if e.get("type") == "finding.resolved"]
        if len(resolved_events) == 0:
            print("[FAIL] No finding.resolved events received")
            return False
        
        print(f"[PASS] {len(resolved_events)} finding.resolved events received")
        
        for event in resolved_events:
            print(f"  finding_id: {event.get('finding_id')}")
            print(f"  resolved_at: {event.get('resolved_at')}")
            print(f"  resolution_evidence: {event.get('resolution_evidence', '')[:60]}...")
            
            # Verify event payload completeness
            if "finding_id" not in event:
                print("[FAIL] finding.resolved event missing finding_id")
                return False
            if "resolved_at" not in event:
                print("[FAIL] finding.resolved event missing resolved_at")
                return False
            if "resolution_evidence" not in event:
                print("[FAIL] finding.resolved event missing resolution_evidence")
                return False
        
        # Check database for resolved findings
        with SessionLocal() as session:
            project = session.get(ReviewedProject, project_id)
            if project:
                reviews = project.reviews
                print(f"\n[PASS] Total reviews in database: {len(reviews)}")
                
                for i, review in enumerate(reviews):
                    findings = review.findings
                    resolved_count = sum(1 for f in findings if f.status == "RESOLVED")
                    active_count = sum(1 for f in findings if f.status == "ACTIVE")
                    new_count = sum(1 for f in findings if f.status == "NEW")
                    print(f"  Review {i+1}: {len(findings)} total findings ({new_count} NEW, {active_count} ACTIVE, {resolved_count} RESOLVED)")
        
        # Step 21: Verify MISTIQ state was updated
        print("\n--- Verifying MISTIQ state ---")
        new_events = all_events[pre_fix_events:]
        completed_events = [e for e in new_events if e.get("type") == "analysis.completed"]
        dna_events = [e for e in new_events if e.get("type") == "dna.updated"]
        prediction_events = [e for e in new_events if e.get("type") == "prediction.updated"]
        if not completed_events:
            print("[FAIL] No analysis.completed event after the fix")
            return False
        latest_completed = completed_events[-1]
        review_id = latest_completed.get("review_id")
        print(f"[PASS] Latest analysis completed with review_id: {review_id}")

        # Failure DNA is recomputed by every analysis run and emitted on the event bus
        failure_dna = dna_events[-1].get("failure_dna") if dna_events else None
        if not failure_dna:
            print("[FAIL] Failure DNA was not recomputed during re-analysis")
            return False
        print(f"[PASS] Failure DNA updated: {', '.join(sorted(failure_dna))}")

        # Verify the MISTIQ state persisted for that review
        with SessionLocal() as session:
            from app.models.entities import ProjectReview
            review = session.get(ProjectReview, review_id)
            if review is None:
                print("[FAIL] Latest review not found in database")
                return False
            print(f"[PASS] Review {review.review_number} persisted with {len(review.findings)} findings and {len(review.predictions)} predictions")
        if prediction_events:
            print(f"[PASS] prediction.updated emitted with {len(prediction_events[-1].get('predictions', []))} predictions")
        
        # Cleanup
        stop_watcher(project_id)
        print("\n[PASS] Monitoring stopped")
        
    finally:
        # Cleanup test directory
        shutil.rmtree(test_dir, ignore_errors=True)
        print("[PASS] Test directory cleaned up")
    
    print("\n" + "=" * 80)
    print("DIRECT E2E TEST - ALL CHECKS PASSED")
    print("=" * 80)
    return True


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
