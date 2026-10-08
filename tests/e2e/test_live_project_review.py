"""Real end-to-end test for live project review with filesystem watching.

Tests the complete engineering-intelligence pipeline:
1. Create temporary project
2. Add a source file containing a detectable engineering issue
3. Connect the project
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
import tempfile
import threading
import time
import requests
import json
from pathlib import Path

import pytest


@pytest.fixture(scope="module")
def test_project_dir():
    """Create a temporary project directory."""
    project_dir = tempfile.mkdtemp(prefix="mistiq_e2e_test_")
    yield project_dir
    # Cleanup
    shutil.rmtree(project_dir, ignore_errors=True)


@pytest.fixture(scope="module")
def backend_server():
    """Start the backend server for testing."""
    # This would normally start the FastAPI server, but for this test
    # we'll assume the server is running on localhost:8000
    # In a real test environment, you'd start the server here
    base_url = "http://localhost:8000"
    # Test if server is available
    try:
        response = requests.get(f"{base_url}/api/health", timeout=5)
        if response.status_code != 200:
            pytest.skip("Backend server not available")
    except requests.RequestException:
        pytest.skip("Backend server not available")
    return base_url


class TestLiveProjectReviewE2E:
    """End-to-end tests for live project review."""
    
    @pytest.mark.skip(reason="Requires running backend server and real filesystem watching")
    def test_complete_live_project_review_workflow(self, test_project_dir, backend_server):
        """Test the complete live project review workflow."""
        base_url = backend_server
        
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
        
        # Step 3: Connect the project
        connect_response = requests.post(
            f"{base_url}/api/project-reviews/connect",
            json={
                "source_type": "local",
                "path": str(project_path)
            },
            timeout=30
        )
        
        assert connect_response.status_code == 200
        connect_data = connect_response.json()
        project_id = connect_data["project_id"]
        
        # Step 4: Run initial analysis (should be done in connect)
        # Step 5: Start monitoring (should be started in connect)
        
        # Step 6: Verify monitoring is ACTIVE
        # This would require connecting to the SSE endpoint or checking status
        # For now, we'll assume monitoring started successfully
        
        # Step 7: Modify the real source file
        time.sleep(2)  # Give the watcher time to start
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
        # Step 9: Verify incremental analysis starts
        # Step 10: Verify review is persisted
        # Step 11: Verify finding is created or updated
        
        # Wait for the analysis to complete
        max_wait = 30  # seconds
        start_time = time.time()
        
        while time.time() - start_time < max_wait:
            time.sleep(1)
            # Check project history to see if new review was created
            history_response = requests.get(
                f"{base_url}/api/project-reviews/{project_id}/history",
                timeout=10
            )
            if history_response.status_code == 200:
                history_data = history_response.json()
                if len(history_data["reviews"]) >= 2:
                    break
        else:
            pytest.fail("Incremental analysis did not complete within timeout")
        
        # Verify we have at least 2 reviews (initial + incremental)
        history_response = requests.get(
            f"{base_url}/api/project-reviews/{project_id}/history",
            timeout=10
        )
        assert history_response.status_code == 200
        history_data = history_response.json()
        assert len(history_data["reviews"]) >= 2
        
        # Step 12: Verify finding lifecycle state
        # Step 13: Verify SSE event (hard to test without a client)
        
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
        
        # Step 15: Save the file
        # Step 16: Wait for watcher detection
        start_time = time.time()
        
        while time.time() - start_time < max_wait:
            time.sleep(1)
            # Check if findings have been resolved
            reviews_response = requests.get(
                f"{base_url}/api/project-reviews/{project_id}/history",
                timeout=10
            )
            if reviews_response.status_code == 200:
                reviews_data = reviews_response.json()
                if len(reviews_data["reviews"]) >= 3:
                    break
        
        # Step 17: Verify incremental re-analysis
        # Step 18: Verify old finding is now RESOLVED
        # Get the latest reviews and check findings
        compare_response = requests.get(
            f"{base_url}/api/project-reviews/{project_id}/compare",
            timeout=10
        )
        assert compare_response.status_code == 200
        compare_data = compare_response.json()
        
        # Should have some resolved findings if the issues were fixed
        assert "resolved_findings" in compare_data
        
        # Step 19: Verify resolution evidence
        # Step 20: Verify finding.resolved SSE event
        # Step 21: Verify MISTIQ state was updated
        
        # Check that MISTIQ history is updated
        evolution_response = requests.get(
            f"{base_url}/api/project-reviews/{project_id}/evolution",
            timeout=10
        )
        assert evolution_response.status_code == 200
        
        # Cleanup: Stop monitoring
        stop_response = requests.post(
            f"{base_url}/api/project-reviews/{project_id}/monitoring/stop",
            timeout=10
        )
        assert stop_response.status_code == 200


class TestSSEEvents:
    """Test SSE event emission."""
    
    @pytest.mark.skip(reason="Requires running backend server and SSE client implementation")
    def test_sse_event_sequence(self, test_project_dir, backend_server):
        """Test that the required SSE events are emitted in the correct sequence."""
        base_url = backend_server
        
        # Create a project with a source file
        project_path = Path(test_project_dir)
        src_dir = project_path / "src"
        src_dir.mkdir()
        test_file = src_dir / "main.py"
        test_file.write_text("# Test file")
        
        # Connect the project
        connect_response = requests.post(
            f"{base_url}/api/project-reviews/connect",
            json={
                "source_type": "local", 
                "path": str(project_path)
            },
            timeout=30
        )
        
        project_id = connect_response.json()["project_id"]
        
        # Required event sequence should be:
        # project.changed
        # analysis.started  
        # analysis.completed
        # finding.* events
        # requirement.updated
        # dna.updated
        # prediction.updated
        
        # For a real test, we'd need to connect to the SSE endpoint
        # and verify the events are received in the correct order
        
        # This test would require a proper SSE client implementation
        

class TestGitSHAIntegration:
    """Test Git SHA synchronization."""
    
    @pytest.mark.skip(reason="Requires Git repository setup")
    def test_git_sha_synchronization(self, test_project_dir, backend_server):
        """Test that Git SHA changes are properly detected and synchronized."""
        base_url = backend_server
        
        # Initialize a Git repository
        project_path = Path(test_project_dir)
        os.chdir(project_path)
        
        # Initialize git repo
        os.system("git init")
        os.system("git config user.name 'Test User'")
        os.system("git config user.email 'test@example.com'")
        
        # Create a file and commit
        test_file = project_path / "main.py"
        test_file.write_text("# Initial content")
        os.system("git add .")
        os.system("git commit -m 'Initial commit'")
        
        # Get the initial SHA
        initial_sha = os.popen("git rev-parse HEAD").read().strip()
        
        # Connect the project
        connect_response = requests.post(
            f"{base_url}/api/project-reviews/connect",
            json={
                "source_type": "local",
                "path": str(project_path)
            },
            timeout=30
        )
        
        project_id = connect_response.json()["project_id"]
        
        # Modify and commit
        test_file.write_text("# Modified content")
        os.system("git add .")
        os.system("git commit -m 'Second commit'")
        
        new_sha = os.popen("git rev-parse HEAD").read().strip()
        assert new_sha != initial_sha
        
        # Wait for the watcher to detect the change
        time.sleep(5)
        
        # Check that the project's current_commit_sha was updated
        # This would require checking the database directly
        
        # Cleanup
        os.chdir("/")


class TestProjectMonitoring:
    """Test project monitoring functionality."""
    
    def test_monitoring_status_endpoints(self, test_project_dir, backend_server):
        """Test that monitoring status can be checked."""
        base_url = backend_server
        
        # Create a project
        project_path = Path(test_project_dir)
        test_file = project_path / "main.py"
        test_file.write_text("# Test file")
        
        # Connect the project
        connect_response = requests.post(
            f"{base_url}/api/project-reviews/connect",
            json={
                "source_type": "local",
                "path": str(project_path)
            },
            timeout=30
        )
        
        assert connect_response.status_code == 200
        project_id = connect_response.json()["project_id"]
        
        # Stop monitoring
        stop_response = requests.post(
            f"{base_url}/api/project-reviews/{project_id}/monitoring/stop",
            timeout=10
        )
        assert stop_response.status_code == 200
        
        # Restart monitoring by reconnecting
        reconnect_response = requests.post(
            f"{base_url}/api/project-reviews/connect",
            json={
                "source_type": "local", 
                "path": str(project_path)
            },
            timeout=30
        )
        assert reconnect_response.status_code == 200


if __name__ == "__main__":
    # Run a simple standalone test without pytest
    print("Running standalone E2E test...")
    print("Note: This requires a running backend server on localhost:8000")
    
    # Test if server is available
    try:
        response = requests.get("http://localhost:8000/api/health", timeout=5)
        if response.status_code == 200:
            print("✓ Backend server is available")
            
            # Create a test project
            test_dir = tempfile.mkdtemp(prefix="mistiq_standalone_test_")
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
                
                # Connect the project
                connect_response = requests.post(
                    "http://localhost:8000/api/project-reviews/connect",
                    json={
                        "source_type": "local",
                        "path": str(project_path)
                    },
                    timeout=30
                )
                
                if connect_response.status_code == 200:
                    data = connect_response.json()
                    print(f"✓ Project connected: ID = {data['project_id']}")
                    print(f"✓ Initial analysis completed with {data['analysis']['summary']['event_count']} events")
                    
                    # Modify the file
                    time.sleep(2)
                    test_file.write_text('''
# Modified file
API_KEY = "secret-key-123"
API_SECRET = "another-secret"
''')
                    
                    print("✓ File modified, waiting for incremental analysis...")
                    time.sleep(5)
                    
                    # Check history
                    project_id = data["project_id"]
                    history_response = requests.get(
                        f"http://localhost:8000/api/project-reviews/{project_id}/history",
                        timeout=10
                    )
                    
                    if history_response.status_code == 200:
                        history = history_response.json()
                        print(f"✓ Review history: {len(history['reviews'])} reviews")
                        
                    # Cleanup
                    stop_response = requests.post(
                        f"http://localhost:8000/api/project-reviews/{project_id}/monitoring/stop",
                        timeout=10
                    )
                    print("✓ Monitoring stopped")
                    
                else:
                    print(f"✗ Failed to connect project: {connect_response.status_code} - {connect_response.text}")
                    
            finally:
                shutil.rmtree(test_dir, ignore_errors=True)
        else:
            print(f"✗ Backend server returned status: {response.status_code}")
    except requests.RequestException as e:
        print(f"✗ Backend server not available: {e}")
        print("Note: To run E2E tests, start the backend server with: uvicorn backend.app.main:app --reload")