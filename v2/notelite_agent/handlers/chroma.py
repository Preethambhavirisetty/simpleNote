from langchain_chroma import Chroma
from langchain_core.documents import Document
from handlers.base import DBHandler


class ChromaHandler(DBHandler):
    def __init__(self):
        self._store = None

    def connect(self, embedder, persist_directory):
        self._store = Chroma(
            embedding_function=embedder,
            persist_directory=persist_directory,
        )

    def load(self, documents, ids, embedder, persist_directory):
        self._store = Chroma.from_documents(
            documents=documents,
            ids=ids,
            embedding=embedder,
            persist_directory=persist_directory,
        )

    def search(self, query, k, filter=None):
        return self._store.similarity_search(query, k=k, filter=filter)

    def count(self):
        return self._store._collection.count()

    def get_all_documents(self):
        result = self._store.get(include=["documents", "metadatas"])
        return [
            Document(page_content=text, metadata=meta)
            for text, meta in zip(result["documents"], result["metadatas"])
        ]
