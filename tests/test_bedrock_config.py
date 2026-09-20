from backend.bedrock_config import resolve_bedrock_model


def test_nova_lite_uses_apac_inference_profile(monkeypatch):
    monkeypatch.setenv("AWS_REGION", "ap-south-1")
    monkeypatch.delenv("SPECL00M_BEDROCK_MODEL_ID", raising=False)
    assert resolve_bedrock_model() == "apac.amazon.nova-pro-v1:0"
    assert resolve_bedrock_model("amazon.nova-lite-v1:0") == "apac.amazon.nova-lite-v1:0"
    assert resolve_bedrock_model("amazon.nova-micro-v1:0") == "apac.amazon.nova-micro-v1:0"
    assert resolve_bedrock_model("amazon.nova-pro-v1:0") == "apac.amazon.nova-pro-v1:0"


def test_explicit_non_legacy_model_is_preserved(monkeypatch):
    monkeypatch.setenv("AWS_REGION", "ap-south-1")
    assert resolve_bedrock_model("some.other.model") == "some.other.model"
