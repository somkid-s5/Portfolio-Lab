"""Cloud Run WSGI entrypoint for the private Event API."""
from google.cloud import firestore, tasks_v2

from app.api import create_event_app
from app.ledger import FirestoreLedger
from app.runtime_config import load_partner_queues, load_project_id
from app.task_queue import CloudTasksEnqueuer


_PROJECT = load_project_id()
_QUEUES = load_partner_queues()
_LEDGER = FirestoreLedger(firestore.Client(project=_PROJECT))
_ENQUEUER = CloudTasksEnqueuer(tasks_v2.CloudTasksClient())
app = create_event_app(
    ledger=_LEDGER,
    enqueuer=_ENQUEUER,
    partner_queues=_QUEUES,
)
