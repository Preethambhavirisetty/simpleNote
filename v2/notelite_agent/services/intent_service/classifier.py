"""Intent classifier: sentence-transformer embeddings + LogisticRegression.

Uses all-mpnet-base-v2 to embed queries, then trains a LogisticRegression
head that learns decision boundaries between intents.

Usage — training:
    cd notelite_agent
    python -m services.intent_service.classifier          # train + evaluate
    python -m services.intent_service.classifier --eval   # evaluate only
    python -m services.intent_service.classifier --retrain # retrain with corrections

Usage — inference (imported by QueryPlanner):
    from services.intent_service.classifier import IntentClassifier
    clf = IntentClassifier.load()
    label, confidence = clf.predict("find the note about taxes")
"""

from __future__ import annotations

import json
import os
import pickle
import time
from collections import Counter
from pathlib import Path

import numpy as np
import structlog
from sentence_transformers import SentenceTransformer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import classification_report, confusion_matrix
from sklearn.model_selection import train_test_split

log = structlog.get_logger()

_DIR = Path(__file__).parent
_EXAMPLES_PATH = _DIR / "examples.json"
_TEST_PATH = _DIR / "test.examples.json"
_MODEL_DIR = _DIR / "model"
_LOW_CONF_PATH = _DIR / "low_confidence_queries.jsonl"

LABEL2ID: dict[str, int] = {
    "semantic": 0,
    "locate_note": 1,
    "list_notes": 2,
    "keyword_count": 3,
    "temporal": 4,
    "presence_check": 5,
    "compare_notes": 6,
    "corpus_stats": 7,
    "conversation_meta": 8,
    "clarify_intent": 9,
}
ID2LABEL: dict[int, str] = {v: k for k, v in LABEL2ID.items()}

BASE_MODEL = "all-mpnet-base-v2"

CONFIDENCE_THRESHOLD = 0.45

VALID_INTENTS = frozenset(LABEL2ID.keys())
INTENT_COLLECTION = f"{os.getenv('QDRANT_COLLECTION', 'knowledge')}_intents"

# ── Data collection ──────────────────────────────────────────────────────


def _load_seed_examples() -> list[dict]:
    """Load hand-curated examples from examples.json."""
    with open(_EXAMPLES_PATH) as f:
        data: dict[str, list[str]] = json.load(f)
    rows = []
    for intent, texts in data.items():
        if intent not in VALID_INTENTS:
            continue
        for text in texts:
            rows.append({"text": text, "label": intent, "source": "seed"})
    return rows


def _load_qdrant_exemplars() -> list[dict]:
    """Pull all exemplars from the Qdrant intents collection."""
    qdrant_url = os.getenv("QDRANT_URL")
    if not qdrant_url:
        log.info("classifier.qdrant_skipped", reason="missing_qdrant_url")
        return []

    try:
        from qdrant_client import QdrantClient

        client = QdrantClient(url=qdrant_url)
        if not client.collection_exists(INTENT_COLLECTION):
            log.warning("classifier.no_qdrant_collection", collection=INTENT_COLLECTION)
            client.close()
            return []

        rows = []
        offset = None
        while True:
            result, offset = client.scroll(
                collection_name=INTENT_COLLECTION,
                limit=256,
                offset=offset,
                with_payload=True,
                with_vectors=False,
            )
            for point in result:
                intent = point.payload.get("intent", "")
                text = point.payload.get("text", "")
                source = point.payload.get("source", "qdrant")
                if intent in VALID_INTENTS and text.strip():
                    rows.append({"text": text, "label": intent, "source": source})
            if offset is None:
                break

        client.close()
        log.info("classifier.qdrant_loaded", count=len(rows))
        return rows
    except Exception:
        log.warning("classifier.qdrant_unavailable", exc_info=True)
        return []


def _load_low_confidence_corrections() -> list[dict]:
    """Load manually-corrected low-confidence queries (JSONL)."""
    if not _LOW_CONF_PATH.exists():
        return []
    rows = []
    with open(_LOW_CONF_PATH) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            if obj.get("label") in VALID_INTENTS and obj.get("text", "").strip():
                rows.append({
                    "text": obj["text"],
                    "label": obj["label"],
                    "source": "correction",
                })
    log.info("classifier.corrections_loaded", count=len(rows))
    return rows


def collect_training_data() -> list[dict]:
    """Gather training data from all sources, deduplicated by text."""
    seed = _load_seed_examples()
    qdrant = _load_qdrant_exemplars()
    corrections = _load_low_confidence_corrections()

    seen: set[str] = set()
    merged: list[dict] = []
    for row in corrections + seed + qdrant:
        key = row["text"].strip().lower()
        if key not in seen:
            seen.add(key)
            merged.append(row)

    log.info(
        "classifier.data_collected",
        total=len(merged),
        breakdown=dict(Counter(r["label"] for r in merged)),
    )
    return merged

# ── Training ─────────────────────────────────────────────────────────────


def train(
    data: list[dict],
    output_dir: str | Path | None = None,
    test_size: float = 0.2,
) -> tuple[LogisticRegression, SentenceTransformer]:
    """Embed all texts, train LogisticRegression, save artifacts."""
    output_dir = Path(output_dir or _MODEL_DIR)
    output_dir.mkdir(parents=True, exist_ok=True)

    texts = [d["text"] for d in data]
    labels = np.array([LABEL2ID[d["label"]] for d in data])

    train_idx, val_idx = train_test_split(
        np.arange(len(texts)),
        test_size=test_size,
        stratify=labels,
        random_state=42,
    )

    print(f"  Train: {len(train_idx)}, Val: {len(val_idx)}")

    encoder = SentenceTransformer(BASE_MODEL)

    print("  Encoding training texts...")
    all_embeddings = encoder.encode(texts, show_progress_bar=True, batch_size=64)

    train_X, train_y = all_embeddings[train_idx], labels[train_idx]
    val_X, val_y = all_embeddings[val_idx], labels[val_idx]

    clf = LogisticRegression(
        max_iter=1000,
        C=5.0,
        solver="lbfgs",
        class_weight="balanced",
    )
    print("  Fitting classifier...")
    clf.fit(train_X, train_y)

    val_pred = clf.predict(val_X)
    val_acc = (val_pred == val_y).mean()
    print(f"  Validation accuracy: {val_acc:.1%}")

    label_names = list(LABEL2ID.keys())
    print("\n  Validation Classification Report:\n")
    print(classification_report(
        val_y, val_pred,
        target_names=label_names,
        zero_division=0,
    ))

    with open(output_dir / "classifier.pkl", "wb") as f:
        pickle.dump({"clf": clf, "label2id": LABEL2ID, "id2label": ID2LABEL}, f)

    (output_dir / "base_model.txt").write_text(BASE_MODEL)

    log.info("classifier.saved", path=str(output_dir), val_acc=round(val_acc, 4))
    return clf, encoder


# ── Evaluation ───────────────────────────────────────────────────────────


def evaluate_on_test(
    clf: LogisticRegression,
    encoder: SentenceTransformer,
) -> dict:
    """Run the model against test.examples.json and print a full report."""
    if not _TEST_PATH.exists():
        log.warning("classifier.no_test_file")
        return {}

    with open(_TEST_PATH) as f:
        cases = json.load(f)

    queries = [c["query"] for c in cases]
    expected_labels = [c["expected_intent"] for c in cases]
    expected_ids = [LABEL2ID.get(e, -1) for e in expected_labels]

    t0 = time.perf_counter()
    embeddings = encoder.encode(queries, batch_size=64)
    probs = clf.predict_proba(embeddings)
    elapsed = time.perf_counter() - t0

    pred_ids = probs.argmax(axis=1)
    pred_labels = [ID2LABEL.get(int(p), "unknown") for p in pred_ids]
    confidences = [float(probs[i, pred_ids[i]]) for i in range(len(queries))]

    print(f"\n{'=' * 70}")
    print("INTENT CLASSIFIER — TEST SET EVALUATION")
    print(f"{'=' * 70}\n")

    passed = 0
    errors = []
    for i, case in enumerate(cases):
        ok = pred_labels[i] == expected_labels[i]
        if ok:
            passed += 1
        else:
            errors.append({
                "id": case.get("id", i),
                "query": case["query"],
                "expected": expected_labels[i],
                "predicted": pred_labels[i],
                "confidence": confidences[i],
                "difficulty": case.get("difficulty", ""),
            })
        status = "\033[92mPASS\033[0m" if ok else "\033[91mFAIL\033[0m"
        print(
            f"  {status}  {case['query'][:55]:<55}  "
            f"exp={expected_labels[i]:<18} got={pred_labels[i]:<18} "
            f"conf={confidences[i]:.2f}"
        )

    total = len(cases)
    pct = passed / total * 100 if total else 0
    avg_ms = elapsed / total * 1000 if total else 0

    print(f"\n{'─' * 70}")
    print(f"  Overall: {passed}/{total} ({pct:.1f}%)  avg: {avg_ms:.1f}ms/query  total: {elapsed:.2f}s")

    if errors:
        print(f"\n  Misclassifications ({len(errors)}):")
        for e in errors:
            print(f"    #{e['id']} \"{e['query'][:55]}\"")
            print(
                f"         expected {e['expected']} -> got {e['predicted']}  "
                f"[{e['difficulty']}] conf={e['confidence']:.2f}"
            )

    label_names = list(LABEL2ID.keys())
    valid_mask = [i for i, eid in enumerate(expected_ids) if eid >= 0]
    if valid_mask:
        filtered_expected = [expected_ids[i] for i in valid_mask]
        filtered_pred = [int(pred_ids[i]) for i in valid_mask]
        print(f"\n{'─' * 70}")
        print("  Classification Report:\n")
        print(classification_report(
            filtered_expected, filtered_pred,
            target_names=label_names, zero_division=0,
        ))
        print("  Confusion Matrix:\n")
        cm = confusion_matrix(
            filtered_expected, filtered_pred,
            labels=list(range(len(label_names))),
        )
        header = "  " + " ".join(f"{n[:6]:>6}" for n in label_names)
        print(header)
        for i, row in enumerate(cm):
            row_str = " ".join(f"{v:>6}" for v in row)
            print(f"  {row_str}  ← {label_names[i]}")

    print(f"\n{'=' * 70}\n")

    return {
        "total": total,
        "passed": passed,
        "accuracy_pct": round(pct, 1),
        "avg_ms": round(avg_ms, 1),
        "errors": errors,
    }


# ── Inference wrapper ────────────────────────────────────────────────────


class IntentClassifier:
    """Loads the saved encoder + sklearn classifier for inference."""

    _instance: IntentClassifier | None = None

    def __init__(self, model_dir: str | Path | None = None):
        model_dir = Path(model_dir or _MODEL_DIR)
        pkl_path = model_dir / "classifier.pkl"
        if not pkl_path.exists():
            raise FileNotFoundError(
                f"No trained model at {model_dir}. "
                "Run: python -m services.intent_service.classifier"
            )

        with open(pkl_path, "rb") as f:
            bundle = pickle.load(f)
        self._clf: LogisticRegression = bundle["clf"]

        base_model_path = model_dir / "base_model.txt"
        base_model = base_model_path.read_text().strip() if base_model_path.exists() else BASE_MODEL
        self._encoder = SentenceTransformer(base_model)

        log.info("classifier.loaded", path=str(model_dir))

    def predict(self, query: str) -> tuple[str, float]:
        """
        Return (intent_label, confidence) for a single query.
        - query -> embeddings via SF.encode([query])
        - probability scores for embeddings via LogisticRegression.predic_proba(embeddings)
        - intent predicate index for the maximum score via argmax
        - get the prediction score from that index
        - return its intent label and score
        """
        emb = self._encoder.encode([query])
        probs = self._clf.predict_proba(emb)[0]
        pred_idx = int(probs.argmax())
        confidence = float(probs[pred_idx])
        label = ID2LABEL.get(pred_idx, "semantic")
        return label, round(confidence, 4)

    def predict_batch(self, queries: list[str]) -> list[tuple[str, float]]:
        """Return [(intent_label, confidence), ...] for a batch."""
        embs = self._encoder.encode(queries, batch_size=64)
        all_probs = self._clf.predict_proba(embs)
        results = []
        for probs in all_probs:
            pred_idx = int(probs.argmax())
            confidence = float(probs[pred_idx])
            label = ID2LABEL.get(pred_idx, "semantic")
            results.append((label, round(confidence, 4)))
        return results

    @classmethod
    def load(cls, model_dir: str | Path | None = None) -> IntentClassifier:
        """Lazy singleton loader."""
        if cls._instance is None:
            cls._instance = cls(model_dir)
        return cls._instance


# ── Low-confidence retraining pipeline ───────────────────────────────────


def append_low_confidence(query: str, predicted: str, confidence: float):
    """Log a low-confidence prediction for later review and correction.

    Call this from the QueryPlanner whenever confidence < threshold.
    Writes to low_confidence_queries.jsonl for manual relabeling.
    """
    entry = {
        "text": query,
        "predicted": predicted,
        "confidence": confidence,
        "label": None,
        "timestamp": int(time.time()),
    }
    with open(_LOW_CONF_PATH, "a") as f:
        f.write(json.dumps(entry) + "\n")


def retrain_with_corrections(model_dir: str | Path | None = None):
    """Retrain incorporating corrected low-confidence queries.

    Workflow:
    1. In production, low-confidence queries are logged via append_low_confidence()
    2. Periodically, review low_confidence_queries.jsonl and fill in
       the "label" field for each entry (delete or leave null to skip)
    3. Run: python -m services.intent_service.classifier --retrain
    """
    corrections = _load_low_confidence_corrections()
    if not corrections:
        print("No corrections found in low_confidence_queries.jsonl.")
        print("Review the file, fill in 'label' fields, then re-run.")
        return

    print(f"Corrections loaded: {len(corrections)}")
    print(f"  Breakdown: {dict(Counter(c['label'] for c in corrections))}")

    print("\n=== Collecting full training data ===")
    data = collect_training_data()
    print(f"Total examples: {len(data)}")

    print("\n=== Training ===")
    clf, encoder = train(data, output_dir=model_dir)

    print("\n=== Evaluating on test.examples.json ===")
    evaluate_on_test(clf, encoder)


# ── CLI ──────────────────────────────────────────────────────────────────


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Intent classifier")
    parser.add_argument("--eval", action="store_true", help="Evaluate only")
    parser.add_argument("--retrain", action="store_true", help="Retrain with corrections")
    args = parser.parse_args()

    if args.retrain:
        retrain_with_corrections()
        return

    if args.eval:
        pkl_path = _MODEL_DIR / "classifier.pkl"
        if not pkl_path.exists():
            print(f"No model found at {pkl_path}. Train first.")
            return
        with open(pkl_path, "rb") as f:
            bundle = pickle.load(f)
        encoder = SentenceTransformer(BASE_MODEL)
        evaluate_on_test(bundle["clf"], encoder)
        return

    print("=== Collecting training data ===")
    data = collect_training_data()
    print(f"Total: {len(data)}")
    print(f"Per-intent: {dict(Counter(d['label'] for d in data))}")

    print("\n=== Training ===")
    clf, encoder = train(data)

    print("\n=== Evaluating on test.examples.json ===")
    evaluate_on_test(clf, encoder)


if __name__ == "__main__":
    # multiprocess 0.70.x ResourceTracker crashes on Python 3.12 shutdown — harmless
    try:
        import multiprocess.resource_tracker as _rt
        _rt.ResourceTracker.__del__ = lambda self: None
    except Exception:
        pass
    main()
