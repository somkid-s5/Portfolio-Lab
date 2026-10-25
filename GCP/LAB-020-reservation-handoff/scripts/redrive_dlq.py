"""Republish at most five report messages, acking only after publish."""
import argparse
import json

from google.cloud import pubsub_v1


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", required=True)
    parser.add_argument("--subscription", required=True)
    parser.add_argument("--topic", required=True)
    parser.add_argument("--max-messages", type=int, default=1)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if not 1 <= args.max_messages <= 5:
        parser.error("--max-messages must be between 1 and 5")
    subscriber = pubsub_v1.SubscriberClient()
    publisher = pubsub_v1.PublisherClient()
    subscription_path = subscriber.subscription_path(args.project, args.subscription)
    topic_path = publisher.topic_path(args.project, args.topic)
    response = subscriber.pull(
        request={"subscription": subscription_path, "max_messages": args.max_messages}, timeout=10
    )
    if not response.received_messages:
        print("redrive_status=empty"); return
    ack_ids = []
    for item in response.received_messages:
        try:
            payload = json.loads(item.message.data)
        except (TypeError, ValueError):
            print("redrive_status=blocked reason=invalid_json"); continue
        if not isinstance(payload, dict) or payload.get("schema_version") != 1:
            print("redrive_status=blocked reason=unsupported_schema"); continue
        print("candidate report_id=" + str(payload.get("report_id", "unknown")) +
              " message_id=" + item.message.message_id)
        if args.dry_run:
            continue
        publisher.publish(topic_path, data=item.message.data).result(timeout=10)
        ack_ids.append(item.ack_id)
    if ack_ids:
        subscriber.acknowledge(request={"subscription": subscription_path, "ack_ids": ack_ids})
    print("redrive_status=published_and_acked count=" + str(len(ack_ids)))


if __name__ == "__main__":
    main()
