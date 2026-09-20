from fastapi.testclient import TestClient

from backend.main import app


client = TestClient(app)


def test_async_build_local_fallback(monkeypatch):
    import backend.api.build as build_api

    fake_result = {
        "ready": True,
        "workflow": {
            "id": "async-demo",
            "name": "Async demo",
            "trigger": {"id": "start", "type": "trigger", "name": "Start", "config": {"mode": "manual"}},
            "nodes": [
                {"id": "out", "type": "output", "name": "Return", "config": {"mode": "return"}},
            ],
            "edges": [{"from": "start", "to": "out"}],
        },
        "gaps": [],
    }
    monkeypatch.delenv("AWS_LAMBDA_FUNCTION_NAME", raising=False)
    monkeypatch.setattr(build_api, "build", lambda project_id, request: fake_result)

    response = client.post(
        "/api/v1/projects/async-build-demo/build/async",
        json={"goal": "Build a small async demonstration workflow."},
    )
    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "completed"

    status = client.get(
        f"/api/v1/projects/async-build-demo/build/jobs/{body['run_id']}"
    )
    assert status.status_code == 200
    assert status.json()["status"] == "completed"
    assert status.json()["build"]["ready"] is True
