"""Restore a pinned Cloud Storage object generation with an explicit apply gate."""
import argparse

from google.api_core.exceptions import NotFound
from google.cloud import storage

MAX_BYTES = 5 * 1024 * 1024


def restore_generation(client, bucket_name, object_name, source_generation, apply=False):
    bucket = client.bucket(bucket_name)
    source = bucket.blob(object_name, generation=source_generation)
    source.reload()
    if source.size is None or source.size > MAX_BYTES:
        raise ValueError("source object must be no larger than 5 MiB")
    target = bucket.blob(object_name)
    try:
        target.reload()
        destination_generation = int(target.generation)
    except NotFound:
        destination_generation = 0
    print(
        "restore_plan bucket={} object={} source_generation={} "
        "current_generation={} bytes={}".format(
            bucket_name, object_name, source_generation, destination_generation, source.size
        )
    )
    if not apply:
        print("restore_status=dry_run")
        return None
    content = source.download_as_bytes()
    target.upload_from_string(
        content,
        content_type=source.content_type or "application/octet-stream",
        if_generation_match=destination_generation,
    )
    target.reload()
    print("restore_status=written new_generation={}".format(target.generation))
    return int(target.generation)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--bucket", required=True)
    parser.add_argument("--object", required=True)
    parser.add_argument("--source-generation", required=True, type=int)
    parser.add_argument("--apply", action="store_true", help="write a new generation; default is dry-run")
    args = parser.parse_args()
    if args.source_generation <= 0:
        parser.error("--source-generation must be positive")
    restore_generation(
        storage.Client(), args.bucket, args.object, args.source_generation, apply=args.apply
    )


if __name__ == "__main__":
    main()
