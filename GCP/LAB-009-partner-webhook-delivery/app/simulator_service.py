"""Cloud Run WSGI entrypoint for the synthetic public partner endpoint."""
from google.cloud import secretmanager
from google.cloud import storage

from app.receipt_store import CloudStorageReceiptStore
from app.runtime_config import load_simulator_settings
from app.secret_manager import SecretVersionReader
from app.simulator import PartnerSimulator
from app.simulator_api import create_simulator_app


_PARTNER_ID, _SECRET_VERSION, _RECEIPT_BUCKET, _FAULT_MODE = load_simulator_settings()
_SECRET = SecretVersionReader(secretmanager.SecretManagerServiceClient())(_SECRET_VERSION)
_STORE = CloudStorageReceiptStore(
    _RECEIPT_BUCKET,
    client=storage.Client(),
)
_SIMULATOR = PartnerSimulator(
    partner_id=_PARTNER_ID,
    secret=_SECRET,
    receipt_store=_STORE,
    fault_mode=_FAULT_MODE,
)
app = create_simulator_app(simulator=_SIMULATOR)
