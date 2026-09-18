from fastapi.testclient import TestClient

from backend.main import app

client = TestClient(app)

def test_text_context_is_ingested_and_analyzed():
    response = client.post(
        "/api/v1/projects/test-context/context/text",
        json={
            "name": "rules.txt",
            "content": (
                "The system must verify sources.\n"
                "The system must not create a GitHub issue without approval."
            ),
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert len(body["graph"]["sources"]) == 1
    assert len(body["graph"]["requirements"]) == 1
    assert len(body["graph"]["constraints"]) == 1

def test_context_get_returns_graph():
    response = client.get("/api/v1/projects/test-context/context")
    assert response.status_code == 200
    assert response.json()["project_id"] == "test-context"
