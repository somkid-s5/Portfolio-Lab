"""Cloud Run WSGI entrypoint for the private Cloud Tasks target."""
from google.cloud import firestore
from google.cloud import secretmanager

from app.ledger import FirestoreLedger
from app.runtime_config import load_partner_endpoints, load_project_id
from app.secret_manager import SecretVersionReader
from app.worker import DeliveryWorker
from app.worker_api import create_worker_app


_PROJECT = load_project_id()
_SECRET_READER = SecretVersionReader(secretmanager.SecretManagerServiceClient())
_WORKER = DeliveryWorker(
    ledger=FirestoreLedger(firestore.Client(project=_PROJECT)),
    partner_endpoints=load_partner_endpoints(),
    secret_provider=_SECRET_READER,
)
app = create_worker_app(worker=_WORKER)
