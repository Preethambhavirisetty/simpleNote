from celery import Celery

from app.core.config import (
    CELERY_RESULT_BACKEND,
    INGESTION_QUEUE,
    INGESTION_TASK_STRING,
    MESSAGE_BROKER_URL,
)

# The backend only *produces* tasks (ingestion, handled by the notelite_agent
# worker); it runs no worker of its own.
celery_app = Celery("tasks", broker=MESSAGE_BROKER_URL, backend=CELERY_RESULT_BACKEND)

celery_app.conf.update(
    task_track_started=True,
    result_expires=3600,
    task_default_queue=INGESTION_QUEUE,
    task_send_sent_event=True,
    broker_connection_retry_on_startup=True,
    task_ignore_result=False,
    task_acks_late=True, # Acknowledge only after the task completes so a worker crash causes a requeue.
    task_reject_on_worker_lost=True,
    task_routes={
        # Handled by the notelite_agent worker
        INGESTION_TASK_STRING: {"queue": INGESTION_QUEUE},
    },
)
