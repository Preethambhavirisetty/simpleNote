from types import SimpleNamespace

from app.services.ingestion.storage.vector_store import QdrantVectorStore


class FakeClient:
    def __init__(self, points):
        self.points = points
        self.scroll_filters = []

    def scroll(self, *, scroll_filter, **kwargs):
        self.scroll_filters.append(scroll_filter)
        return self.points, None


def store_with_points(points):
    store = QdrantVectorStore.__new__(QdrantVectorStore)
    store.client = FakeClient(points)
    return store


def point(content="Neighbor content"):
    return SimpleNamespace(
        id="point-id",
        payload={
            "doc_id": "doc",
            "chunk_id": "1",
            "content": content,
            "metadata": {
                "prev_chunk_id": "0",
                "next_chunk_id": "2",
            },
        },
    )


def test_fetch_neighbor_uses_canonical_top_level_identity():
    store = store_with_points([point()])

    neighbor = store.fetch_neighbor("doc", "1")

    assert neighbor is not None
    assert neighbor.text == "Neighbor content"
    assert neighbor.metadata["doc_id"] == "doc"
    assert neighbor.metadata["chunk_id"] == "1"
    assert len(store.client.scroll_filters) == 1
    assert [condition.key for condition in store.client.scroll_filters[0].must] == [
        "doc_id",
        "chunk_id",
    ]


def test_fetch_neighbor_returns_none_when_canonical_identity_is_missing():
    store = store_with_points([])

    assert store.fetch_neighbor("doc", "1") is None
