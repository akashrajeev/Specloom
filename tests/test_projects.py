from fastapi.testclient import TestClient

from backend.main import app

client = TestClient(app)


def test_project_state_endpoint():
    response = client.get("/api/v1/projects/state-demo")
    assert response.status_code == 200
    body = response.json()
    assert body["project_id"] == "state-demo"
    assert body["workflow"] is None


def test_versions_can_activate():
    workflow = client.get("/api/v1/projects/researchhunter").json()["workflow"]
    versions = client.get("/api/v1/projects/researchhunter/versions")
    assert versions.status_code == 200
    assert versions.json()["versions"]

    activated = client.post("/api/v1/projects/researchhunter/versions/1/activate")
    assert activated.status_code == 200
    assert activated.json()["workflow"]["id"] == workflow["id"]


def test_deploy_check_exposes_product_readiness():
    response = client.get("/api/v1/projects/researchhunter/deploy/check")
    assert response.status_code == 200
    body = response.json()
    assert "ready" in body
    assert {item["id"] for item in body["checks"]} >= {"workflow", "tests", "persistence", "runtime", "public-url"}


def test_tool_mode_update_creates_version():
    project_id = "mode-demo"
    base = client.get("/api/v1/projects/researchhunter").json()["workflow"]
    response = client.patch(
        f"/api/v1/projects/{project_id}/nodes/github/mode",
        json={"mode": "sandbox"},
    )
    assert response.status_code == 200
