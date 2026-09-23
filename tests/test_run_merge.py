from backend.context.store import ContextStore


def test_stale_cache_does_not_erase_runs_from_other_containers():
    a, b = ContextStore(), ContextStore()
    shared = {}

    class Repo:
        def __init__(self, inner):
            self.inner = inner
        def __getattr__(self, name):
            return getattr(self.inner, name)
        def save(self, project):
            shared["runs"] = [dict(r) for r in project.runs]
        def get_runs(self, project_id):
            return [dict(r) for r in shared.get("runs", [])]

    a._repository = Repo(a._repository)
    b._repository = Repo(b._repository)
    a.get("p"); b.get("p")
    a.record_run("p", {"run_id": "r1", "created_at": "2026-01-01T00:00:00", "status": "running"})
    b.record_run("p", {"run_id": "r2", "created_at": "2026-01-01T00:01:00", "status": "running"})
    a.update_run("p", "r1", {"status": "completed"})
    ids = {r["run_id"]: r["status"] for r in shared["runs"]}
    assert ids == {"r1": "completed", "r2": "running"}
