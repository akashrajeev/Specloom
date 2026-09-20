from backend.storage.build_jobs import BuildJobRepository


def test_build_job_repository_memory_round_trip(monkeypatch):
    monkeypatch.delenv("SPECL00M_BUILD_JOBS_TABLE", raising=False)
    repo = BuildJobRepository()
    job = {
        "project_id": "p1",
        "run_id": "r1",
        "kind": "build_job",
        "status": "queued",
    }
    repo.put(job)
    assert repo.get("p1", "r1")["status"] == "queued"
    updated = repo.update("p1", "r1", status="running")
    assert updated["status"] == "running"
