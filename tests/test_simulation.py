from fastapi.testclient import TestClient

from backend.main import app
from backend.simulation.executor import Simulator
from backend.workflow.loader import load_workflow

client = TestClient(app)

def test_simulation_waits_for_approval():
    ir = load_workflow("examples/showcase-workflow.json")
    result = Simulator().run(ir, {"approved": False})
    assert result.status == "waiting"
    assert any(event.status == "waiting" for event in result.events)

def test_simulation_succeeds_with_approval():
    ir = load_workflow("examples/showcase-workflow.json")
    result = Simulator().run(ir, {"approved": True})
    assert result.status == "passed"
    assert result.output["issues_created"] == 3
    assert result.side_effects

def test_simulation_api_accepts_workflow():
    workflow = load_workflow("examples/showcase-workflow.json").model_dump(mode="json")
    response = client.post(
        "/api/v1/projects/demo/simulate",
        json={"workflow": workflow, "input_data": {"approved": True}},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "passed"
