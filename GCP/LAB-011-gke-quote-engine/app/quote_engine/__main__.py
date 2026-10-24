"""CLI entrypoint for the API, worker, and IAM probe."""
from __future__ import annotations

import argparse
import logging
import os
import sys

from .secrets import check_secret_access
from .server import serve


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("api", "worker", "check-secret"))
    parser.add_argument("--secret-id", default="")
    parser.add_argument("--version", default="latest")
    args = parser.parse_args()
    logging.basicConfig(stream=sys.stdout, level=logging.INFO, format="%(message)s")
    if args.mode == "check-secret":
        if not args.secret_id:
            parser.error("--secret-id is required for check-secret")
        try:
            check_secret_access(args.secret_id, args.version)
        except Exception as exc:
            print(f"ACCESS_DENIED error_type={type(exc).__name__}")
            return 3
        print("ACCESS_ALLOWED payload=not-printed")
        return 0
    port = int(os.environ.get("PORT", "8080" if args.mode == "api" else "8081"))
    if not 1 <= port <= 65535:
        parser.error("PORT must be between 1 and 65535")
    serve(args.mode, "0.0.0.0", port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
