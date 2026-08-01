from celery import Celery
from celery.signals import worker_process_init

from app.logger import setup_logging

from app.core.config import (
    CELERY_RESULT_BACKEND,
    CONVERSATION_QUEUE,
    INGESTION_QUEUE,
    INGESTION_TASK_STRING,
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
    task_ignore_result=False,
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
