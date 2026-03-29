from abc import ABC, abstractmethod


class DBHandler(ABC):
    @abstractmethod
    def connect(self, embedder, persist_directory):
        """Connect to an existing persisted store."""

    @abstractmethod
    def upsert(self, summary_doc, chunk_docs, doc_id, persist_directory):
        """Ingest a summary document and chunk documents into the store."""

    @abstractmethod
    def search(self, query, k, filter=None, doc_ids=None):
        """Run similarity search on chunks, return list of Documents."""

    def search_summaries(self, query, k, filter=None):
        """Search document summaries, return list of (Document, score) tuples."""
        raise NotImplementedError

    @abstractmethod
    def count(self, filter=None):
        """Return total document count."""

    @abstractmethod
    def get_all_documents(self, filter=None):
        """Return all stored chunk Documents for BM25 indexing."""

    def delete(self, filter=None):
        """Delete documents matching filter from all collections."""
        raise NotImplementedError("Delete operation not implemented for this handler.")

    def close(self):
        """Clean up resources. Override if the backend needs explicit teardown."""
