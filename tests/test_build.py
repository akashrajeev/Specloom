from fastapi.testclient import TestClient

from backend.main import app

client = TestClient(app)

def test_build_returns_valid_workflow_and_execution_plan():
    response = client.post(
        "/api/v1/projects/build-demo/build",
        json={"goal": "Find relevant AI research every morning."},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["workflow"]["name"] == "ResearchHunter"
    assert body["execution_plan"]["ordered_nodes"][0]["type"] == "trigger"
    assert body["execution_plan"]["ordered_nodes"][-1]["type"] == "output"
