"""Does the cross-encoder rank playbooks better than embeddings?

The two are not interchangeable. A bi-encoder maps question and playbook into
one space independently, so it separates them by topic - and every playbook
here is about notes. A cross-encoder reads both together, which is the only way
"find my notes about X" and "what do my notes say about X" can score
differently.

    .venv/bin/python -m tests.rank_eval
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from integrations.embedder import embeddings_available  # noqa: E402
from integrations.reranker import rerank, reranker_available  # noqa: E402
from services.playbook import PlaybookService  # noqa: E402

# The same held-out questions used for the runtime's selector eval, labelled
# with the playbook that should win. None appear in any playbook's examples.
CASES: list[tuple[str, str]] = [
    ("What conclusion did I reach about the caching layer?", "notes_qa"),
    ("According to my notes, who owns the billing service?", "notes_qa"),
    ("What are the tradeoffs I wrote down for Kafka vs SQS?", "notes_qa"),
    ("What budget number did I record for the offsite?", "notes_qa"),
    ("Based on my notes, what is the deployment procedure?", "notes_qa"),
    ("Tell me what I know about the customer churn analysis.", "notes_qa"),
    ("Did I talk about food?", "notes_qa"),
    ("Locate any note that talks about the security audit.", "search_notes"),
    ("Which of my notes reference the payments API?", "search_notes"),
    ("Show me everything in the Archive folder.", "search_notes"),
    ("I need the note where I kept the wifi password.", "search_notes"),
    ("Search for notes mentioning Kubernetes.", "search_notes"),
    ("Give me my folder list.", "search_notes"),
    ("What tags do I have set up?", "search_notes"),
    ("find me the notes where i wrote about food", "search_notes"),
    ("What notes did I create in the last three days?", "note_timeline"),
    ("Show me everything I captured during January.", "note_timeline"),
    ("Which note did I touch most recently?", "note_timeline"),
    ("Walk me through my notes chronologically.", "note_timeline"),
    ("Summarize my week based on my notes.", "note_timeline"),
    ("Make a new note titled Grocery List.", "direct_tool"),
    ("Put the budget note in the Finance folder.", "direct_tool"),
    ("Get rid of the note about the cancelled trip.", "direct_tool"),
    ("Rename my Personal folder to Life Admin.", "direct_tool"),
    ("Attach the important tag to my roadmap note.", "direct_tool"),
    ("Can you make this email sound friendlier?", "direct_llm"),
    ("What is the difference between a mutex and a semaphore?", "direct_llm"),
    ("Write a haiku about deadlines.", "direct_llm"),
    ("Thanks!", "direct_llm"),
    ("How does TCP handshaking work?", "direct_llm"),
]


def main() -> None:
    service = PlaybookService()
    playbooks = {p.playbook_id: p for p in service.list_playbooks()}
    ids = list(playbooks)
    print(f"{len(CASES)} questions over {len(ids)} playbooks")
    print(f"reranker={reranker_available()}  embeddings={embeddings_available()}\n")

    documents = [service._rerank_text(playbooks[i]) for i in ids]

    for label, ranker in (("embeddings", _embedding_ranker(service)), ("reranker", _rerank_ranker(ids, documents))):
        hits = [0] * 4
        margins: list[float] = []
        latencies: list[float] = []
        misses: list[tuple[str, str, list[str]]] = []

        for question, expected in CASES:
            started = time.perf_counter()
            ranked = ranker(question)
            latencies.append(time.perf_counter() - started)
            order = [playbook_id for playbook_id, _ in ranked]
            if len(ranked) > 1:
                margins.append(ranked[0][1] - ranked[1][1])
            for k in range(1, 4):
                if expected in order[:k]:
                    hits[k] += 1
            if order[:1] != [expected]:
                misses.append((question, expected, order[:2]))

        total = len(CASES)
        latencies.sort()
        margins.sort()
        print(
            f"{label:12} top-1 {hits[1] / total:>4.0%}  top-2 {hits[2] / total:>4.0%}  "
            f"top-3 {hits[3] / total:>4.0%}  median margin {margins[len(margins) // 2]:>6.2f}  "
            f"median {latencies[len(latencies) // 2] * 1000:>4.0f}ms"
        )
        for question, expected, got in misses:
            print(f"    miss: {question[:52]:54} want {expected:14} got {got}")
        print()


def _embedding_ranker(service: PlaybookService):
    def rank(question: str):
        return service._by_embedding(question, 5)
    return rank


def _rerank_ranker(ids: list[str], documents: list[str]):
    def rank(question: str):
        return [(ids[item.index], item.score) for item in rerank(question, documents)]
    return rank


if __name__ == "__main__":
    main()
