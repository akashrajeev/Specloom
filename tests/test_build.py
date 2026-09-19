from fastapi.testclient import TestClient

from backend.main import app

client = TestClient(app)

def test_build_returns_valid_workflow_and_execution_plan():
    response = client.post(
        "/api/v1/projects/build-demo/build",
        json={"goal": "Find new AI research every morning."},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["workflow"]["name"] == "ResearchHunter"
    assert body["execution_plan"]["ordered_nodes"][0]["type"] == "trigger"
    assert body["execution_plan"]["ordered_nodes"][-1]["type"] == "output"


def test_build_can_resolve_context_gap():
    project_id = "gap-resolution-demo"
    blocked = client.post(
        f"/api/v1/projects/{project_id}/build",
        json={"goal": "Find relevant research and report it."},
    )
    assert blocked.status_code == 200
    assert blocked.json()["ready"] is False
    assert blocked.json()["gaps"]

    answered = client.post(
        f"/api/v1/projects/{project_id}/build",
        json={
            "goal": "Find relevant research and report it.",
            "gap_answers": {
                blocked.json()["gaps"][0]["id"]: "Use the configured project domains and reject unrelated results."
            },
        },
    )
    assert answered.status_code == 200
    assert answered.json()["ready"] is True
    assert answered.json()["workflow"]
