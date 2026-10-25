"""Cloud Run application factories. No bootstrap/admin credentials in serving roles."""
import atexit
import os

from database import build_database
from dispatch import Dispatcher
from orders import Orders
from outbox import Outbox
from pubsub_publish import build_publisher
from queue_http import create_worker,create_dispatcher


def build_worker():
    database = build_database("worker")
    try:
        repository = Orders(database.connect)
        project = os.environ["GOOGLE_CLOUD_PROJECT"]
        fault_mode = os.environ.get("LAB007_WORKER_FAULT_MODE", "off")
        app = create_worker(repository,
            f"projects/{project}/subscriptions/lab007-orders-worker",
            database_health=repository.health, fault_mode=fault_mode)
    except BaseException:
        database.close()
        raise
    app.extensions["lab007_database"] = database
    atexit.register(database.close)
    return app


def build_dispatcher():
    database = build_database("dispatcher")
    publisher = None
    try:
        publisher = build_publisher(os.environ["GOOGLE_CLOUD_PROJECT"])
        outbox = Outbox(database.connect)
        app = create_dispatcher(Dispatcher(outbox,publisher),database_health=outbox.health)
    except BaseException:
        try:
            if publisher is not None:
                publisher.client.transport.close()
        finally:
            database.close()
        raise
    app.extensions["lab007_database"] = database
    app.extensions["lab007_publisher"] = publisher
    atexit.register(database.close)
    atexit.register(publisher.client.transport.close)
    return app
