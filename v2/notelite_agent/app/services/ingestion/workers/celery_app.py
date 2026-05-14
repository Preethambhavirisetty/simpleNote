from celery import Celery

from app.core.config import (
    CELERY_RESULT_BACKEND,
    CONVERSATION_QUEUE,
    INGESTION_QUEUE,
    INGESTION_TASK_STRING,
    MESSAGE_BROKER_URL,
)

CONVERSATION_TASK = "tasks.persist_message"

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
    },
    imports=("app.services.ingestion.workers.ingestion_tasks",),
)
