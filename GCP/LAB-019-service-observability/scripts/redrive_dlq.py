#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import sys

from google.cloud import pubsub_v1


def main() -> int:
    parser = argparse.ArgumentParser(description="Republish a bounded number of Lab 19 DLQ messages.")
    parser.add_argument("--project", required=True)
    parser.add_argument("--max-messages", type=int, default=20)
    parser.add_argument("--subscription", default="lab19-task-dlq-reader")
    parser.add_argument("--topic", default="lab19-tasks")
    args = parser.parse_args()

    if not (1 <= args.max_messages <= 50):
        parser.error("--max-messages must be between 1 and 50.")
    if args.subscription != "lab19-task-dlq-reader" or args.topic != "lab19-tasks":
        parser.error("This tool only accepts the fixed Lab 19 DLQ subscription and task topic.")

    subscriber = pubsub_v1.SubscriberClient()
    publisher = pubsub_v1.PublisherClient()
    subscription_path = subscriber.subscription_path(args.project, args.subscription)
    topic_path = publisher.topic_path(args.project, args.topic)

    response = subscriber.pull(
        request={"subscription": subscription_path, "max_messages": args.max_messages},
        timeout=30,
    )
    if not response.received_messages:
        print("redriven=0 dlq_empty=true")
        return 0

    ack_ids = []
    redriven = 0
    for received in response.received_messages:
        attributes = dict(received.message.attributes)
        attributes["lab19-redrive-utc"] = datetime.now(timezone.utc).isoformat()
        future = publisher.publish(topic_path, received.message.data, **attributes)
        future.result(timeout=30)
        ack_ids.append(received.ack_id)
        redriven += 1

    if ack_ids:
        subscriber.acknowledge(request={"subscription": subscription_path, "ack_ids": ack_ids})
    print(f"redriven={redriven} acknowledged_after_publish=true")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"DLQ redrive failed; messages were not acknowledged unless publish succeeded: {exc}", file=sys.stderr)
        raise SystemExit(2)
