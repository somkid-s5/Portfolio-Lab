"""Render the checked-in Kubernetes template with a project, image digest and named IP."""
from __future__ import annotations

import argparse
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "manifests" / "platform.yaml"
PROJECT_RE = re.compile(r"^[a-z][a-z0-9-]{4,28}[a-z0-9]$")
RESOURCE_RE = re.compile(r"^[a-z][a-z0-9-]{0,61}[a-z0-9]$")
IMAGE_RE = re.compile(r"^[a-z0-9.-]+-docker\.pkg\.dev/[a-z0-9._/-]+@sha256:[0-9a-f]{64}$")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True)
    parser.add_argument("--image-uri", required=True, help="Artifact Registry URI pinned by sha256 digest")
    parser.add_argument("--gateway-ip-name", required=True, help="name of the reserved regional address")
    parser.add_argument("--output", default=str(ROOT / "manifests" / "build" / "platform.yaml"))
    args = parser.parse_args()
    if not PROJECT_RE.fullmatch(args.project):
        parser.error("--project must be a lowercase Google Cloud project ID")
    if not IMAGE_RE.fullmatch(args.image_uri):
        parser.error("--image-uri must be an Artifact Registry image URI ending in @sha256:<64 lowercase hex>")
    if not RESOURCE_RE.fullmatch(args.gateway_ip_name):
        parser.error("--gateway-ip-name must be a lowercase Google Cloud resource name")

    content = TEMPLATE.read_text(encoding="utf-8")
    rendered = content.replace("__PROJECT_ID__", args.project)
    rendered = rendered.replace("__IMAGE_URI__", args.image_uri)
    rendered = rendered.replace("__GATEWAY_IP_NAME__", args.gateway_ip_name)
    leftovers = re.findall(r"__[A-Z0-9_]+__", rendered)
    if leftovers:
        raise SystemExit(f"Unresolved template values: {', '.join(sorted(set(leftovers)))}")
    output = Path(args.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(rendered, encoding="utf-8")
    print(f"Rendered {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
