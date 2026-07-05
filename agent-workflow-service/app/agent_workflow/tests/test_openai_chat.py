from __future__ import annotations

from app.agent_workflow.providers.openai_chat import normalize_inference_model


def test_normalize_inference_model_strips_provider_prefix():
    assert normalize_inference_model("the-inference/reasoner") == "reasoner"
    assert normalize_inference_model("reasoner") == "reasoner"
