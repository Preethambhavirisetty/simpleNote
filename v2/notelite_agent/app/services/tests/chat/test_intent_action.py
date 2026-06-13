from pydantic import TypeAdapter

from app.services.chat.actions.controller import RetrievalActionController
from app.services.chat.actions.schema import IntentActionRequest, IntentPayload
from app.services.chat.actions.services import RetrievalActionServices
from app.services.chat.intent_classification import IntentResult
from app.services.ingestion.actions.schema import PipelineActionRequest


def test_pipeline_action_schema_accepts_retrieval_intent():
    request = TypeAdapter(PipelineActionRequest).validate_python({
        "action_name": "retrieval.intent",
        "payload": {"query": "compare January with March"},
    })

    assert isinstance(request, IntentActionRequest)
    assert request.payload.query == "compare January with March"


def test_intent_action_returns_complete_classifier_diagnostics(monkeypatch):
    monkeypatch.setattr(
        "app.services.chat.actions.services.classify_intent",
        lambda query: IntentResult(
            intent="search",
            confidence=0.42,
            raw_intent="lookup",
            used_fallback=True,
            reason="low_confidence",
        ),
    )

    result = RetrievalActionServices(vector_store=None).intent(IntentPayload(query="ambiguous"))

    assert result == {
        "intent": "search",
        "confidence": 0.42,
        "raw_intent": "lookup",
        "used_fallback": True,
        "reason": "low_confidence",
    }


def test_retrieval_action_controller_dispatches_intent_without_vector_store(monkeypatch):
    monkeypatch.setattr(
        "app.services.chat.actions.services.classify_intent",
        lambda query: IntentResult(intent="comparison", confidence=0.96, raw_intent="comparison"),
    )

    controller = RetrievalActionController(vector_store=None)
    result = controller.run("retrieval.intent", IntentPayload(query="compare the two plans"))

    assert result["intent"] == "comparison"
    assert result["used_fallback"] is False
    assert result["reason"] == "classified"
