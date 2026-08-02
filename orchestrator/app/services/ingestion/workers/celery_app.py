from celery import Celery
from celery.signals import worker_process_init

from app.logger import setup_logging

from app.core.config import (
    CELERY_RESULT_BACKEND,
    CONVERSATION_QUEUE,
    INGESTION_QUEUE,
    INGESTION_TASK_STRING,
    INGEST_SOFT_TIME_LIMIT,
    INGEST_TIME_LIMIT,
    MESSAGE_BROKER_URL,
    RECONCILE_INTERVAL_SECONDS,
)

CONVERSATION_TASK = "tasks.persist_message"
RECONCILE_TASK = "tasks.reconcile_index"

celery_app = Celery(
    "tasks",
    broker=MESSAGE_BROKER_URL,
    backend=CELERY_RESULT_BACKEND,
)

celery_app.conf.update(
    result_backend=CELERY_RESULT_BACKEND,
    task_track_started=True,
    result_expires=3600,
    task_default_queue=INGESTION_QUEUE,
    task_send_sent_event=True,
    broker_connection_retry_on_startup=True,
    # Results stay on: GET /api/ingest/status/{job_id} polls AsyncResult.
    task_ignore_result=False,
    # Every stage of every task here is a blocking HTTP call. Without a limit,
    # one hung socket holds a worker slot forever and logs nothing - the queue
    # shows tasks "received" and ingestion has silently stopped. The soft limit
    # raises inside the task so it can log and retry; the hard limit kills the
    # process as a backstop and, with acks_late + reject_on_worker_lost, the
    # message is redelivered rather than lost.
    task_soft_time_limit=INGEST_SOFT_TIME_LIMIT,
    task_time_limit=INGEST_TIME_LIMIT,
    task_reject_on_worker_lost=True,
    # Off, and load-bearing: structlog prints JSON to sys.stdout, and celery's
    # stdout redirection replaces the pool children's stdout with a
    # LoggingProxy whose recursion guard then swallows every line the task
    # body logs. That made completed work indistinguishable from a hang -
    # tasks showed "received" and nothing else, ever.
    worker_redirect_stdouts=False,
    # Long tasks: let each worker child take one message at a time instead of
    # prefetching four and starving its sibling while they wait behind a slow
    # note.
    worker_prefetch_multiplier=1,
    task_routes={
        INGESTION_TASK_STRING: {"queue": INGESTION_QUEUE},
        CONVERSATION_TASK: {"queue": CONVERSATION_QUEUE},
        RECONCILE_TASK: {"queue": INGESTION_QUEUE},
    },
    imports=(
        "app.services.ingestion.workers.ingestion_tasks",
        "app.services.ingestion.workers.reconciliation",
    ),
    # Driven by the embedded beat (-B) in the single agent-celery worker; if the
    # worker is ever scaled out, move beat to a dedicated process so the schedule
    # isn't duplicated.
    beat_schedule={
        "reconcile-index": {
            "task": RECONCILE_TASK,
            "schedule": RECONCILE_INTERVAL_SECONDS,
        },
    },
)


@worker_process_init.connect
def configure_worker_logging(**_kwargs) -> None:
    setup_logging(service="agent-celery")
