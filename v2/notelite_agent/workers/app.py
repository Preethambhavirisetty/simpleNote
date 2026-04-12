"""Celery application configuration.

Start the worker with:
    celery -A workers.app worker -Q ingestion,conversation -c 2 -l INFO
"""

from celery import Celery
from core.config import (
    INGESTION_TASK_STRING,
    MESSAGE_BROKER_URL,
    CELERY_RESULT_BACKEND,
    INGESTION_QUEUE,
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
        CONVERSATION_TASK: {"queue": INGESTION_QUEUE},
    },
)

celery_app.autodiscover_tasks(["workers"])
