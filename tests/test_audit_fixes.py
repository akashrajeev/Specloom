from fastapi.testclient import TestClient

from backend.main import app

client = TestClient(app)

SUPPORT = (
    "Build a support triage system that receives customer requests, classifies the issue, "
    "drafts a helpful response, and requires human approval before handling urgent cases."
)
RESEARCH = (
    "Build a research system that finds recent AI developments from configured sources, checks "
    "relevance, requires human approval, and creates GitHub issues only after approval."
)


def _build(project_id: str, goal: str):
    return client.post(f"/api/v1/projects/{project_id}/build", json={"goal": goal})


def test_capability_goal_does_not_crash_validation():
    response = _build(
        "audit-capability-goal",
        "Monitor competitor pricing pages daily and email me a weekly summary of price changes",
    )
    assert response.status_code != 500
    assert response.status_code in {200, 422}


def test_support_demo_builds_in_its_own_project():
    response = _build("audit-support-demo", SUPPORT)
    assert response.status_code == 200, response.text
    assert response.json()["workflow"]["id"] == "support-triage-generated"


def test_second_goal_drops_first_goal_planner_requirements():
    project_id = "audit-goal-switch"
    assert _build(project_id, "Create a webcrawler").status_code == 200
    response = _build(project_id, SUPPORT)
    assert response.status_code == 200, response.text
    context = client.get(f"/api/v1/projects/{project_id}/context").json()["graph"]
    planner_sources = [s for s in context["sources"] if s["id"].startswith("src_planner_")]
    assert len(planner_sources) == 1
    statements = " ".join(item["statement"] for item in context["requirements"]).lower()
    assert "webcrawler" not in statements


def test_only_one_version_is_active():
    project_id = "audit-single-active"
    assert _build(project_id, SUPPORT).status_code == 200
    assert _build(project_id, SUPPORT).status_code == 200
    versions = client.get(f"/api/v1/projects/{project_id}/versions").json()["versions"]
    assert len(versions) >= 2
    assert sum(1 for item in versions if item["active"]) == 1
    assert versions[-1]["active"] is True


def test_projects_can_be_listed():
    assert _build("audit-list-me", RESEARCH).status_code == 200
    body = client.get("/api/v1/projects").json()
    ids = [item["project_id"] for item in body["projects"]]
    assert "audit-list-me" in ids
    listed = next(item for item in body["projects"] if item["project_id"] == "audit-list-me")
    assert listed["name"] and listed["node_count"] > 0


def test_duplicate_node_name_is_rejected():
    project_id = "audit-dup-node"
    assert _build(project_id, SUPPORT).status_code == 200
    response = client.post(
        f"/api/v1/projects/{project_id}/nodes",
        json={"type": "agent", "name": "Classify"},
    )
    assert response.status_code == 409
