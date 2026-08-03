from llama_index.core import Document

from app.services.chat import reranker


class FakePoolClient:
    """Stands in for the module's shared httpx client."""

    def __init__(self, results):
        self._results = results

    def post(self, *args, **kwargs):
        return FakeResponse(self._results)


class FakeResponse:
    def __init__(self, results):
        self._results = results

    def raise_for_status(self):
        return None

    def json(self):
        return {"results": self._results}


def chunks():
    return [
        (Document(text="first"), 0.03),
        (Document(text="second"), 0.02),
        (Document(text="third"), 0.01),
    ]


def test_reranker_accepts_score_field_and_filters_irrelevant_results(monkeypatch):
    monkeypatch.setattr(reranker, "RERANKER_API_BASE", "http://reranker")
    monkeypatch.setattr(reranker, "RERANKER_MIN_RELEVANCE_SCORE", 0.0)
    monkeypatch.setattr(
        reranker,
        "_http_client",
        lambda: FakePoolClient([
            {"index": 1, "score": 4.2},
            {"index": 0, "score": -8.0},
        ]),
    )

    ranked = reranker.rerank("query", chunks(), top_k=3)

    assert [(document.text, score) for document, score in ranked] == [
        ("second", 4.2),
    ]


def test_reranker_accepts_relevance_score_field(monkeypatch):
    monkeypatch.setattr(reranker, "RERANKER_API_BASE", "http://reranker")
    monkeypatch.setattr(reranker, "RERANKER_MIN_RELEVANCE_SCORE", 0.0)
    monkeypatch.setattr(
        reranker,
        "_http_client",
        lambda: FakePoolClient([
            {"index": 2, "relevance_score": 0.8},
        ]),
    )

    ranked = reranker.rerank("query", chunks(), top_k=3)

    assert [(document.text, score) for document, score in ranked] == [
        ("third", 0.8),
    ]


def test_reranker_keeps_its_order_when_every_score_is_below_threshold(monkeypatch):
    """All-negative scores are normal for this model, not a signal of failure.

    ms-marco returns negative logits for correct matches - measured against the
    deployed model, the query "sourdough" scores its own starter log at -11.0
    and still ranks it first, and "baking" tops its list at -2.66. This test
    previously asserted a fallback to RRF order in that case, which threw away
    a correct ranking on every such query. The threshold may trim a tail, but
    it must never discard the reranker's ordering.
    """
    monkeypatch.setattr(reranker, "RERANKER_API_BASE", "http://reranker")
    monkeypatch.setattr(reranker, "RERANKER_MIN_RELEVANCE_SCORE", 0.0)
    monkeypatch.setattr(
        reranker,
        "_http_client",
        lambda: FakePoolClient([
            {"index": 2, "score": -5.0},
            {"index": 1, "score": -8.0},
        ]),
    )

    ranked = reranker.rerank("query", chunks(), top_k=2)

    assert [document.text for document, _score in ranked] == ["third", "second"]


def test_reranker_still_trims_a_tail_when_something_clears_the_threshold(monkeypatch):
    """The threshold keeps working when at least one candidate passes it."""
    monkeypatch.setattr(reranker, "RERANKER_API_BASE", "http://reranker")
    monkeypatch.setattr(reranker, "RERANKER_MIN_RELEVANCE_SCORE", 0.0)
    monkeypatch.setattr(
        reranker,
        "_http_client",
        lambda: FakePoolClient([
            {"index": 2, "score": 1.5},
            {"index": 1, "score": -8.0},
        ]),
    )

    ranked = reranker.rerank("query", chunks(), top_k=2)

    assert [document.text for document, _score in ranked] == ["third"]
