"""Celery application. Pipeline tasks register here from M1 onward."""

import os

from celery import Celery

celery = Celery(
    "redthread",
    broker=os.environ.get("REDIS_URL", "redis://redis:6379/0"),
    backend=os.environ.get("REDIS_URL", "redis://redis:6379/0"),
)

celery.conf.update(
    task_acks_late=True,
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
)
