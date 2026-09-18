from fastapi.testclient import TestClient

from backend.main import app

client = TestClient(app)


def test_project_state_endpoint():
    response = client.get("/api/v1/projects/state-demo")
    assert response.status_code == 200
    body = response.json()
    assert body["project_id"] == "state-demo"
    assert body["workflow"] is None
