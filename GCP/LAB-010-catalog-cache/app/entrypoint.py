import os
import sys


def main():
    role = os.environ.get("APP_ROLE", "public")
    if role == "migrate":
        from app.migrate import main as migrate

        migrate()
        return
    if role not in {"public", "admin"}:
        raise SystemExit("APP_ROLE must be public, admin, or migrate")
    port = os.environ.get("PORT", "8080")
    os.execvp("gunicorn", [
        "gunicorn",
        "--bind", f"0.0.0.0:{port}",
        "--workers", "1",
        "--threads", "20",
        "--timeout", "30",
        "app.wsgi:app",
    ])


if __name__ == "__main__":
    main()
