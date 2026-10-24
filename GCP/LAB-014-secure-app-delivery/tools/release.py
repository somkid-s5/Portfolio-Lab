from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from typing import Any


class ReleaseError(RuntimeError):
    pass


def _commit_candidates(build: dict[str, Any]) -> set[str]:
    values: set[str] = set()
    for root_name in ("sourceProvenance", "source_provenance", "source"):
        root = build.get(root_name, {})
        if not isinstance(root, dict):
            continue
        for key in ("resolvedRepoSource", "resolved_repo_source", "resolvedConnectedRepository", "resolved_connected_repository", "resolvedGitSource", "resolved_git_source", "repoSource", "repo_source", "connectedRepository", "connected_repository", "gitSource", "git_source"):
            source = root.get(key, {})
            if isinstance(source, dict):
                for field in ("commitSha", "commit_sha", "revision", "sha"):
                    value = source.get(field)
                    if isinstance(value, str) and value:
                        values.add(value.lower())
    substitutions = build.get("substitutions", {})
    if isinstance(substitutions, dict):
        for field in ("COMMIT_SHA", "REVISION_ID"):
            value = substitutions.get(field)
            if isinstance(value, str) and value:
                values.add(value.lower())
    return values


def _build_trigger_id(build: dict[str, Any]) -> str:
    return str(build.get("buildTriggerId") or build.get("build_trigger_id") or "")


def verify_build_record(
    build: dict[str, Any],
    *,
    project_id: str,
    trigger_id: str,
    commit_sha: str,
    builder_email: str,
    region: str,
) -> dict[str, str]:
    if _build_trigger_id(build) != trigger_id:
        raise ReleaseError("Cloud Build record came from an unexpected trigger")
    if commit_sha.lower() not in _commit_candidates(build):
        raise ReleaseError("Cloud Build source revision does not match the GitHub commit")
    if build.get("status") != "SUCCESS":
        raise ReleaseError(f"matching Cloud Build ended with status {build.get('status', 'UNKNOWN')}")
    expected_service_account = f"projects/{project_id}/serviceAccounts/{builder_email}"
    if build.get("serviceAccount") != expected_service_account:
        raise ReleaseError("Cloud Build runtime service account does not match the dedicated builder identity")

    image_base = f"{region}-docker.pkg.dev/{project_id}/lab014-apps/shipping-quote-api"
    results = build.get("results", {})
    images = results.get("images", []) if isinstance(results, dict) else []
    matches = [
        item for item in images
        if isinstance(item, dict) and str(item.get("name", "")).split("@", 1)[0].rsplit(":", 1)[0] == image_base
    ]
    digests = {str(item.get("digest", "")) for item in matches}
    if len(digests) != 1:
        raise ReleaseError("successful build did not produce exactly one Lab 14 image digest")
    digest = next(iter(digests))
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
        raise ReleaseError("Cloud Build returned an invalid image digest")
    build_id = str(build.get("id", ""))
    if not re.fullmatch(r"[A-Za-z0-9-]{8,80}", build_id):
        raise ReleaseError("Cloud Build record omitted a valid build ID")
    return {
        "build_id": build_id,
        "commit_sha": commit_sha.lower(),
        "digest": digest,
        "image_uri": f"{image_base}@{digest}",
    }


def _run_gcloud(project_id: str, region: str, trigger_id: str) -> list[dict[str, Any]]:
    command = [
        "gcloud", "builds", "list",
        f"--project={project_id}",
        f"--region={region}",
        f"--filter=trigger_id={trigger_id}",
        "--sort-by=~create_time",
        "--limit=100",
        "--format=json",
    ]
    try:
        result = subprocess.run(command, check=True, capture_output=True, text=True, timeout=30)
        payload = json.loads(result.stdout)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        raise ReleaseError(f"Cloud Build lookup failed: {type(exc).__name__}") from exc
    except json.JSONDecodeError as exc:
        raise ReleaseError("Cloud Build lookup returned invalid JSON") from exc
    if not isinstance(payload, list):
        raise ReleaseError("Cloud Build lookup did not return a list")
    return [item for item in payload if isinstance(item, dict)]


def wait_for_verified_build(
    *,
    project_id: str,
    region: str,
    trigger_id: str,
    commit_sha: str,
    builder_email: str,
    max_wait_seconds: int = 720,
    poll_seconds: int = 10,
) -> dict[str, str]:
    if not re.fullmatch(r"[0-9a-fA-F]{40}", commit_sha):
        raise ReleaseError("expected commit must be a full 40-character Git SHA")
    if not trigger_id or not re.fullmatch(r"[A-Za-z0-9-]{6,80}", trigger_id):
        raise ReleaseError("Cloud Build trigger ID is missing or malformed")
    if not 1 <= max_wait_seconds <= 1200 or not 1 <= poll_seconds <= 30:
        raise ReleaseError("Cloud Build wait and poll intervals are outside the allowed bounds")
    deadline = time.monotonic() + max_wait_seconds
    while True:
        builds = _run_gcloud(project_id, region, trigger_id)
        matches = [
            item for item in builds
            if _build_trigger_id(item) == trigger_id
            and commit_sha.lower() in _commit_candidates(item)
        ]
        if len(matches) > 1:
            raise ReleaseError("more than one build matches this trigger and commit; refusing to guess")
        if matches:
            status = str(matches[0].get("status", "UNKNOWN"))
            if status == "SUCCESS":
                return verify_build_record(
                    matches[0],
                    project_id=project_id,
                    trigger_id=trigger_id,
                    commit_sha=commit_sha,
                    builder_email=builder_email,
                    region=region,
                )
            if status not in {"QUEUED", "WORKING", "PENDING"}:
                raise ReleaseError(f"matching Cloud Build ended with status {status}")
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise ReleaseError("timed out waiting for a successful build of this exact commit")
        time.sleep(min(poll_seconds, remaining))


def _write_github_outputs(result: dict[str, str]) -> None:
    output_path = os.environ.get("GITHUB_OUTPUT")
    if output_path:
        with open(output_path, "a", encoding="utf-8") as output:
            for key in ("build_id", "commit_sha", "digest", "image_uri"):
                output.write(f"{key}={result[key]}\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Wait for and validate the exact Lab 14 Cloud Build result.")
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--region", required=True)
    parser.add_argument("--trigger-id", required=True)
    parser.add_argument("--commit-sha", required=True)
    parser.add_argument("--builder-email", required=True)
    parser.add_argument("--max-wait-seconds", type=int, default=720)
    parser.add_argument("--poll-seconds", type=int, default=10)
    args = parser.parse_args(argv)
    try:
        result = wait_for_verified_build(
            project_id=args.project_id,
            region=args.region,
            trigger_id=args.trigger_id,
            commit_sha=args.commit_sha,
            builder_email=args.builder_email,
            max_wait_seconds=args.max_wait_seconds,
            poll_seconds=args.poll_seconds,
        )
    except ReleaseError as exc:
        print(json.dumps({"result": "fail", "reason": str(exc)}), file=sys.stderr)
        return 1
    _write_github_outputs(result)
    print(json.dumps({"result": "verified", **result}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
