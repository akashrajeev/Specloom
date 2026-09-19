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


def test_url_ingestion_blocks_private_addresses():
    import asyncio
    from backend.context.ingestion import IngestionError, ingest_url

    async def run():
        try:
            await ingest_url("http://127.0.0.1:8000/internal")
            assert False, "expected private-address rejection"
        except IngestionError:
            return

    asyncio.run(run())
