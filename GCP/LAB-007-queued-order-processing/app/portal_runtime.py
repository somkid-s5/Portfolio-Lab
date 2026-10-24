"""Serving Portal factory; no bootstrap/DB admin identity is loaded here."""
import atexit
import os
import re

from auth_config import read_auth
from database import build_database
from orders import Orders
from outbox import Outbox
from replay import Replay
from portal_http import create_app


def build_portal():
    if (os.environ.get("AUTH_FILE")!="/secrets/auth/auth.json" or
            not re.fullmatch(r"[1-9][0-9]{0,9}",os.environ.get("AUTH_SECRET_VERSION",""))):
        raise ValueError("fixed_numeric_auth_mount_required")
    auth=read_auth("/secrets/auth/auth.json")
    database=build_database("portal")
    try:
        orders=Orders(database.connect)
        outbox=Outbox(database.connect)
        app=create_app(orders,outbox,auth,database_health=orders.health,replay=Replay(database.connect))
    except BaseException:
        database.close()
        raise
    app.extensions["lab007_database"]=database
    atexit.register(database.close)
    return app
