"""Celery application configuration.

Start the worker with:
    celery -A workers.app worker -Q ingestion,conversation -c 2 -l INFO
"""

from celery import Celery
from celery.signals import setup_logging as celery_setup_logging, worker_process_init
from core.config import (
    INGESTION_TASK_STRING,
    MESSAGE_BROKER_URL,
    CELERY_RESULT_BACKEND,
    INGESTION_QUEUE,
)
from logger import setup_logging


@celery_setup_logging.connect
def _on_celery_setup_logging(**kwargs):
    """Run our structlog config instead of Celery's default logging."""
    setup_logging(service="agent-celery")


@worker_process_init.connect
def _on_worker_process_init(**kwargs):
    """Re-init in each forked worker so the Loki pusher thread is alive."""
    setup_logging(service="agent-celery")

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
