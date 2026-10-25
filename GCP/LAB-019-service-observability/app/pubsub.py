from __future__ import annotations

import json
import os

from google.cloud import pubsub_v1


def publish_task(task_id: str) -> None:
    topic_name = os.environ["PUBSUB_TOPIC"]
    publisher = pubsub_v1.PublisherClient()
    future = publisher.publish(
        topic_name,
        json.dumps({"task_id": task_id}, separators=(",", ":")).encode("utf-8"),
    )
    future.result(timeout=15)
