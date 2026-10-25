"""Secret Manager access through Application Default Credentials / Workload Identity."""
from __future__ import annotations

import os


def access_secret(secret_id: str, version: str = "latest") -> str:
    project_id = os.environ.get("GCP_PROJECT_ID", "").strip()
    if not project_id:
        raise RuntimeError("GCP_PROJECT_ID is required")
    if not secret_id or "/" in secret_id:
        raise ValueError("secret_id must be a Secret Manager ID")
    from google.cloud import secretmanager

    client = secretmanager.SecretManagerServiceClient()
    name = f"projects/{project_id}/secrets/{secret_id}/versions/{version}"
    response = client.access_secret_version(request={"name": name})
    return response.payload.data.decode("utf-8")


def check_secret_access(secret_id: str, version: str = "latest") -> bool:
    """Read one version without printing its payload; intended for the lab probe."""
    access_secret(secret_id, version)
    return True
