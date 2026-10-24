"""Gunicorn application target for the private coordinator Cloud Run service."""
from app.runtime import create_app_from_env

app = create_app_from_env()
