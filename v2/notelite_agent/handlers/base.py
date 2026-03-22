from abc import ABC, abstractmethod


class DBHandler(ABC):
    @abstractmethod
    def connect(self, embedder, persist_directory):
        """Connect to an existing persisted store."""

    @abstractmethod
    def upsert(self, documents, doc_id, persist_directory):
        """Ingest documents into the store."""

    @abstractmethod
    def search(self, query, k, filter=None):
        """Run similarity search, return list of Documents."""

    @abstractmethod
    def count(self, filter=None):
        """Return total document count."""

    @abstractmethod
    def get_all_documents(self, filter=None):
        """Return all stored Documents for BM25 indexing."""

    def delete(self, filter=None):
        """Delete documents matching filter."""
        raise NotImplementedError("Delete operation not implemented for this handler.")

    def close(self):
        """Clean up resources. Override if the backend needs explicit teardown."""
