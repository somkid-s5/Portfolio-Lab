"""Cloud Run WSGI entrypoint for Cloud Scheduler's private target."""
from google.cloud import firestore, tasks_v2

from app.ledger import FirestoreLedger
from app.reconciler import OutboxReconciler
from app.reconciler_api import create_reconciler_app
from app.runtime_config import load_partner_queues, load_project_id
from app.task_queue import CloudTasksEnqueuer


_PROJECT = load_project_id()
_QUEUES = load_partner_queues()
_LEDGER = FirestoreLedger(firestore.Client(project=_PROJECT))
_ENQUEUER = CloudTasksEnqueuer(tasks_v2.CloudTasksClient())
_RECONCILER = OutboxReconciler(
    ledger=_LEDGER,
    enqueuer=_ENQUEUER,
    partner_queues=_QUEUES,
)
app = create_reconciler_app(reconciler=_RECONCILER)
