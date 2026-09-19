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
    assert body["system_planner_mode"] == "deterministic"
    assert body["system_ir"]["acceptance_criteria"]
    assert body["execution_plan"]["ordered_nodes"][0]["type"] == "trigger"
    assert body["execution_plan"]["ordered_nodes"][-1]["type"] == "output"
    assert body["artifact_status"]["count"] >= 5
    assert body["artifacts"]


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
    assert answered.json()["artifact_status"]["count"] >= 5


def test_build_synthesizes_missing_external_capability_but_preserves_safety_gate():
    project_id = "capability-synthesis-demo"
    response = client.post(
        f"/api/v1/projects/{project_id}/build",
        json={"goal": "Every morning send a summary to my email inbox."},
    )
    assert response.status_code == 200
    body = response.json()
    synthesized = body["synthesized_capabilities"]
    assert any(
        item["kind"] == "synthesized"
        and "email" in item["id"]
        for item in synthesized
    )
    assert body["ready"] is False
    assert any(gap["category"] == "safety" for gap in body["gaps"])


def test_build_includes_compiler_proof_obligations_for_context():
    project_id = "proof-obligations-demo"
    context = client.post(
        f"/api/v1/projects/{project_id}/context/text",
        json={
            "name": "requirements",
            "content": (
                "The system must preserve the audit trail.\n"
                "The system must not publish externally without approval."
            ),
        },
    )
    assert context.status_code == 200

    response = client.post(
        f"/api/v1/projects/{project_id}/build",
        json={
            "goal": "Process the supplied records and prepare a controlled report for an operator.",
        },
    )
    assert response.status_code == 200
    tests = response.json()["workflow"]["tests"]
    assert any("coverage-req_" in test["id"] for test in tests)
    assert any("coverage-con_" in test["id"] for test in tests)


def test_generated_proof_suite_covers_control_flow():
    from backend.evaluation.testgen import augment_with_generated_tests
    from backend.workflow.models import WorkflowIR
    from backend.context.models import ContextGraph

    workflow = WorkflowIR.model_validate(
        {
            "ir_version": "0.1",
            "id": "proof-flow",
            "name": "Proof flow",
            "trigger": {
                "id": "start",
                "type": "trigger",
                "name": "Start",
                "config": {"mode": "manual"},
            },
            "nodes": [
                {
                    "id": "condition",
                    "type": "condition",
                    "name": "Decision",
                    "config": {"expression": "approved", "branches": ["yes", "no"]},
                },
                {
                    "id": "loop",
                    "type": "loop",
                    "name": "Loop",
                    "config": {"collection": "items", "body": "body", "max_iterations": 3},
                },
                {
                    "id": "body",
                    "type": "agent",
                    "name": "Body",
                    "config": {"role": "Process", "output_mode": "structured"},
                },
                {
                    "id": "parallel",
                    "type": "parallel",
                    "name": "Parallel",
                    "config": {"branches": ["left", "right"]},
                },
                {
                    "id": "left",
                    "type": "agent",
                    "name": "Left",
                    "config": {"role": "Left", "output_mode": "structured"},
                },
                {
                    "id": "right",
                    "type": "agent",
                    "name": "Right",
                    "config": {"role": "Right", "output_mode": "structured"},
                },
                {
                    "id": "out",
                    "type": "output",
                    "name": "Return",
                    "config": {"mode": "return"},
                },
            ],
            "edges": [
                {"from": "start", "to": "condition"},
                {"from": "condition", "to": "loop", "condition": "true"},
                {"from": "condition", "to": "parallel", "condition": "false"},
                {"from": "loop", "to": "parallel"},
                {"from": "parallel", "to": "out"},
                {"from": "left", "to": "out"},
                {"from": "right", "to": "out"},
            ],
            "variables": [],
            "policies": [],
            "tests": [],
        }
    )

    generated = augment_with_generated_tests(workflow, ContextGraph())
    ids = {str(test["id"]) for test in generated.tests}
    assert "control-condition-condition" in ids
    assert "control-loop-loop" in ids
    assert "control-parallel-parallel" in ids
    assert "terminal-output-out" in ids


def test_build_runs_semantic_review_when_enabled(monkeypatch):
    import backend.api.build as build_api

    class FakeReviewer:
        def review(self, **kwargs):
            from backend.agents.reviewer import ArchitectureReview
            assert kwargs["goal"] == "Find new AI research every morning."
            return ArchitectureReview(
                status="passed",
                summary="Semantic review passed.",
                findings=[],
            )

    monkeypatch.setenv("SPECL00M_REVIEW_MODE", "bedrock")
    monkeypatch.setattr(build_api, "BedrockArchitectureReviewer", FakeReviewer)

    response = client.post(
        "/api/v1/projects/review-integration-demo/build",
        json={"goal": "Find new AI research every morning."},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["review_mode"] == "bedrock"
    assert body["review"]["status"] == "passed"


def test_generated_artifacts_are_retrievable():
    project_id = "artifact-api-demo"
    response = client.post(
        f"/api/v1/projects/{project_id}/build",
        json={"goal": "Find new AI research every morning."},
    )
    assert response.status_code == 200

    listed = client.get(f"/api/v1/projects/{project_id}/artifacts")
    assert listed.status_code == 200
    body = listed.json()
    assert body["count"] >= 5

    generated = client.get(
        f"/api/v1/projects/{project_id}/artifacts/generated/spec/system-spec.json"
    )
    assert generated.status_code == 200
    artifact = generated.json()
    assert artifact["sha256"]
    assert '"version": "0.1"' in artifact["content"]
