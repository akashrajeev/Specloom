from fastapi.testclient import TestClient


def test_phone_approval_demo_starts_a_run_on_the_prebuilt_workflow(monkeypatch):
    from backend.api import runtime as runtime_api
    from backend.context.store import store
    from backend.main import app

    started = []
    monkeypatch.setattr(runtime_api, "_run_and_record",
                        lambda pid, wf, data, trigger: started.append((pid, wf.id, trigger)) or {"run_id": "run_x", "status": "running"})
    response = TestClient(app).post("/api/v1/demo/phone-approval")
    assert response.status_code == 200
    body = response.json()
    assert body["project_id"] == "demo-price-watch" and body["run_id"] == "run_x"
    assert started == [("demo-price-watch", "demo_price_watch", "demo")]
    workflow = store.get("demo-price-watch").workflow
    assert workflow.trigger.config["mode"] == "manual"
    assert [n.type for n in workflow.nodes] == ["agent", "human_approval", "output"]
