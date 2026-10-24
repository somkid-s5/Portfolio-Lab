"""Synchronous single-message GAPIC publish; no batching thread or future."""
import os
import re

from google.pubsub_v1.services.publisher import PublisherClient
from google.pubsub_v1.types import PublishRequest, PubsubMessage
from order_domain import event_bytes, parse_event

RPC_TIMEOUT = 5.0


class UnconfirmedPublish(RuntimeError):
    pass


def topic_for(project):
    if not isinstance(project,str) or not re.fullmatch(r"[a-z][a-z0-9-]{4,28}[a-z0-9]",project):
        raise ValueError("invalid_project")
    return f"projects/{project}/topics/lab007-orders"


class Publisher:
    def __init__(self, client, project):
        self.topic = topic_for(project)
        self.client = client

    def publish(self, payload):
        event = parse_event(payload)
        if payload != event_bytes(event.event_id,event.order_id,event.order_fingerprint):
            raise ValueError("noncanonical_event")
        request = PublishRequest(topic=self.topic,messages=[PubsubMessage(data=payload)])
        try:
            response = self.client.publish(request=request,retry=None,timeout=RPC_TIMEOUT)
            ids = list(response.message_ids)
        except Exception:
            # Unknown outcome can include a successful server-side publish.
            raise UnconfirmedPublish("publish_unconfirmed") from None
        if (len(ids) != 1 or not isinstance(ids[0],str) or
                not re.fullmatch(r"[A-Za-z0-9_-]{1,128}",ids[0])):
            raise UnconfirmedPublish("publish_unconfirmed")
        return ids[0]


def build_publisher(project):
    if any(os.environ.get(key) for key in (
            "PUBSUB_EMULATOR_HOST", "GOOGLE_APPLICATION_CREDENTIALS")):
        raise ValueError("attached_identity_required")
    topic_for(project)  # Validate before any ADC lookup/client construction.
    return Publisher(PublisherClient(),project)
