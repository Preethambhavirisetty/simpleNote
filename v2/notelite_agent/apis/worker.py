import logging

from celery import Celery
from core.contracts import AccessContext
from core.config import (
    INGESTION_TASK_STRING,
    MESSAGE_BROKER_URL,
    CELERY_RESULT_BACKEND,
    INGESTION_QUEUE,
)
from core.pg import fetch_note_version
from core.schema import IngestionTaskPayload
from core.settings import init_llama_index_settings
from services.storage_service import VectorStore
from services.chunking_service import get_document_objects

log = logging.getLogger(__name__)


worker_app = Celery(
    "tasks",
    broker=MESSAGE_BROKER_URL,
    backend=CELERY_RESULT_BACKEND,
)
worker_app.conf.update(
    result_backend=CELERY_RESULT_BACKEND,
    task_track_started=True,
    result_expires=3600,
    task_default_queue=INGESTION_QUEUE,
    task_send_sent_event=True,
    broker_connection_retry_on_startup=True,
    task_ignore_result=False,
    task_routes={INGESTION_TASK_STRING: {"queue": INGESTION_QUEUE}},
)

# Initialize once per worker process on import.
init_llama_index_settings()


def _run_ingestion(data):
    # Defensive in case worker process hot-reloads.
    init_llama_index_settings()
    print("***************** data ingestion began! *****************")
    doc_id, summary_doc, chunk_docs = get_document_objects(data)
    access_context = AccessContext(
        user_id=data["user_id"],
        role=data["role"],
        tenant_id=data.get("tenant_id"),
    )
    with VectorStore() as db:
        db.upsert(
            summary_doc,
            chunk_docs,
            doc_id,
            access_context=access_context,
        )


def _run_delete(user_id, note_id, role="user", tenant_id=None):
    access_context = AccessContext(
        user_id=user_id,
        role=role,
        tenant_id=tenant_id,
    )
    with VectorStore() as db:
        db.delete_documents(
            access_context=access_context,
            filter={"user_id": user_id, "note_id": note_id},
        )


def _normalize_ingestion_payload(data=None, **kwargs) -> dict:
    """Validate and normalise raw task kwargs against the canonical IngestionTaskPayload schema.

    Accepts two call styles:
    1) Direct /ingest HTTP API  → ``data`` is already a validated dict (user_id key).
    2) Backend Celery dispatch  → kwargs spread from the backend payload dict (userid key).

    All field-name aliasing (userid → user_id, list role → str, action lowercase) is
    handled inside IngestionTaskPayload's @model_validator.  Any unrecognised extra
    fields are silently ignored (schema Config: extra="ignore").
    """
    raw: dict = {}
    if isinstance(data, dict) and data:
        raw = dict(data)
    if kwargs:
        raw.update(kwargs)

    return IngestionTaskPayload(**raw).model_dump()


def _is_stale(note_id: str, user_id: str, payload_version) -> bool:
    """Return True if the task carries an older version than what is in Postgres.

    Logic:
    - If payload carries no version (None / missing) → never stale, always ingest.
    - If the note row is gone for (note_id, user_id) → skip (deleted or wrong user).
    - If payload_version < db_version → stale, skip.

    Both note_id AND user_id are used so a mis-dispatched task is rejected here
    before it can reach the vector store's AccessContext check.
    """
    if payload_version is None:
        return False

    db_version = fetch_note_version(note_id, user_id)

    if db_version is None:
        log.info(
            "note %s not found in pg for user %s — skipping upsert task",
            note_id, user_id,
        )
        return True

    if int(payload_version) < db_version:
        log.info(
            "Stale ingestion task for note %s (payload v%s < db v%s) — skipping",
            note_id, payload_version, db_version,
        )
        return True

    return False


@worker_app.task(
    name=INGESTION_TASK_STRING,
    acks_late=True,
    bind=True,
    # Only retry transient I/O failures.  Programming errors (KeyError, ValueError,
    # TypeError, PermissionError, etc.) are bugs that retrying cannot fix — let
    # them surface immediately so they are visible in monitoring.
    autoretry_for=(ConnectionError, TimeoutError, OSError),
    max_retries=5,
    retry_backoff=True,
)
def ingest_in_background(self, data=None, **kwargs):
    payload = _normalize_ingestion_payload(data, **kwargs)
    action = payload["action"]          # guaranteed lowercase by schema
    note_id = payload["note_id"]
    user_id = payload["user_id"]

    if action == "delete":
        # Delete is always honoured regardless of version — the note is gone.
        _run_delete(
            user_id=user_id,
            note_id=note_id,
            role=payload["role"],
            tenant_id=payload["tenant_id"],
        )
        return {
            "message": f"delete completed for {user_id}:{note_id}",
            "action": "delete",
        }

    # ── Version guard ─────────────────────────────────────────────────────────
    if _is_stale(note_id, user_id, payload["version"]):
        return {
            "message": f"skipped stale task for note {note_id}",
            "action": "skip",
            "payload_version": payload["version"],
        }

    _run_ingestion(payload)
    return {
        "message": f"ingestion completed for {user_id}",
        "action": "upsert",
    }



if __name__ == '__main__':
    text = """
The document/documents begins with the idea that the organization is always doing something, even when it is not doing very much at all. On paper, the system appears organized, but in practice the system is mostly a collection of activities, operations, processes, notes, reports, and discussions that are repeated in different forms throughout the day. During the day, the team talks about coordination, and at night the same team talks about coordination again, but with slightly different words, as if repetition itself were a strategy. The report about the work refers to the report as if the report were both the cause and the effect of the work.

In the first section, there is a mention of alignment, strategy, management, implementation, workflow, integration, and output. In the second section, those same terms appear again, but they are surrounded by words like thing, stuff, part, item, element, factor, aspect, and piece. The text keeps saying that one thing leads to another thing, that one activity influences another activity, and that one operation affects another operation, yet the exact relationship between these things is never fully explained. The result is a situation where the situation itself becomes the subject of the discussion.

The project team is described in several ways. Sometimes it is the operations team. Sometimes it is the management team. Sometimes it is the delivery team. Sometimes it is simply the team. Sometimes it is not even a team but a group, a unit, a collection, or a set of people working on the same thing. The document also refers to the organization, the company, the department, the office, and the group as though these were interchangeable, which makes entity extraction difficult. The organization wants better organization, the company wants better coordination, and the department wants better management, but all of these goals are expressed using the same generic language.

There are multiple references to the phase, the stage, the step, the process, the procedure, the cycle, and the sequence. Every phase contains a review, every review contains a note, every note contains a comment, every comment contains a remark, and every remark contains another reference to the same project. The implementation phase is mentioned alongside the planning phase, the analysis phase, the execution phase, the validation phase, and the closing phase, but each one seems to contain the same content repeated under a different heading. The document makes it look like there are many distinct stages when in reality there is very little variation.

The text also includes a long discussion of data, logs, records, outputs, results, metrics, values, and summaries. The data is said to support the report, but the report is also said to define the data. The logs are said to show the output, but the output is also said to confirm the logs. The metrics are said to measure performance, but performance is never clearly separated from activity, work, or output. This creates a loop in which every noun points back to another noun, and every conclusion points back to the original statement.

Sometimes the document switches to more abstract language. It talks about improvement, optimization, efficiency, quality, consistency, reliability, structure, clarity, and stability. These are repeated in different combinations, often with modifiers like better, more, less, stronger, clearer, faster, and simpler. The text claims that the workflow should be clearer, the operations should be smoother, the coordination should be stronger, the management should be better, and the integration should be tighter, but these claims are not backed by concrete detail. Instead, the document uses phrases like “the thing we need,” “the way forward,” “the right approach,” and “the better path,” which sound useful but do not add much semantic precision.

At several points, the document becomes circular. It says that the report should improve the report. It says that the summary should summarize the summary. It says that the review should review the review. It says that the process should process the process. It says that the system should stabilize the system. These statements are grammatically valid but semantically weak. They create a worst-case scenario for a keyword extractor because the same words appear in many contexts, often without clear importance or hierarchy.

The final section repeats the core themes one more time: team, report, work, process, system, output, management, operations, coordination, integration, workflow, phase, data, log, result, organization, and situation. The conclusion does not introduce new information; it only rephrases what has already been said. If a keyword extractor relies too heavily on frequency, it may surface the wrong terms. If it relies too heavily on shallow phrase matching, it may keep phrases that are merely repeated rather than truly meaningful. If it relies too heavily on surface form without normalization, it may treat plural and singular variants as unrelated terms even though they refer to the same concept.

In that sense, the document is designed to be difficult. It is long enough to create many candidate spans, repetitive enough to inflate common terms, abstract enough to blur semantic boundaries, and vague enough to make subphrase pruning uncertain. It includes multiple references to day and night, to the same idea expressed in different ways, to overlapping concepts like management and coordination, and to generic nouns like thing, stuff, part, piece, item, and element. A keyword extractor has to decide what matters most, even though the text keeps suggesting that almost everything matters equally. That is exactly what makes it a useful stress test.

u/TechGuru_99 • 4h ago • r/GadgetHeads
Just grabbed the new Pixel 8 Pro from the Google Store in Mountain View!
Has anyone tried comparing the Tensor G3 chip against the Apple A17 Pro? I’m heading to London next Tuesday for CES 2024 and want to know if the battery holds up on a 10-hour flight. I paid about $999 plus tax. Also, shoutout to Marques Brownlee for the solid review that convinced me to switch from my old Samsung S21.

"""
    import time
    start = time.time()
    # data = {
    #     "text": text,
    #     "user_id": "SAMPLEUSER01",
    #     "folder_id": "SAMPLESFOLDER01",
    #     "note_id": "SAMPLENOTE01",
    #     "role": "user",
    #     "tenant_id": "TENANT01",
    #     "folder_title": "SAMPLE FOLDER TITLE1",
    #     "note_title": "SAMPLE NOTE TITLE1",
    #     "description": "SAMPLE DESCRIPTION 1",
    #     "tags": [
    #         "tag1",
    #         "tag2"
    #     ]
    # }
    # _run_ingestion(data)
    with VectorStore() as client:
        results = client.retrieve_documents("how to move forward?", access_context=AccessContext("SAMPLEUSER01", "user", "TENANT01"))
        print(results, len(results))
    print("Total ingestion time: ", time.time() - start)

# {"text":"ncrete detail. Instead, the document uses phrases like “the thing we need,” “the way forward,” “the right approach,” and “the better path,” which sound useful but do not add much semantic precision.","keywords":["detail","precision","path","approach","document phrases","phrase"],"entities":[],"created_at":1774814908,"doc_quality":0.745,"is_high_quality":true,"metadata":{"doc_id":"SAMPLEUSER01-SAMPLESFOLDER01-SAMPLENOTE01","user_id":"SAMPLEUSER01","tenant_id":"TENANT01","folder_id":"SAMPLESFOLDER01","note_id":"SAMPLENOTE01","folder_title":"SAMPLE FOLDER TITLE1","note_title":"SAMPLE NOTE TITLE1","description":"SAMPLE DESCRIPTION 1","tags":"tag1,tag2","chunk_id":17,"parent_summary":"The text explores the challenges of aligning team tasks with document content, contrasted with excitement for the Pixel 8 Pro's technological advancements."}}
