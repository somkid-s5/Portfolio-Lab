import os

from app.factory import create_app

app = create_app(os.environ.get("APP_ROLE", "public"))
