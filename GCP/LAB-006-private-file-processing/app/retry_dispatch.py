"""One bounded authenticated worker delivery. Unknown outcome must be reconciled."""
import json
import re
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


class RetryDispatcher:
    def __init__(self, worker_origin, token_supplier, *, opener=None):
        url = urlsplit(worker_origin)
        if (url.scheme != "https" or not url.hostname or
                not url.hostname.endswith(".run.app") or
                url.port not in (None, 443) or url.username or url.password or
                url.path not in ("", "/") or url.query or url.fragment):
            raise ValueError("expected_cloud_run_https_origin")
        self.origin = worker_origin.rstrip("/")
        self.token_supplier = token_supplier
        self.opener = opener or build_opener(ProxyHandler({}), NoRedirect())

    def __call__(self, job_id, epoch):
        if (not isinstance(job_id, str) or not re.fullmatch(r"[a-f0-9]{32}", job_id) or
                type(epoch) is not int or not 1 <= epoch <= 2):
            raise ValueError("invalid_retry_binding")
        token = self.token_supplier(self.origin)
        if not isinstance(token, str) or not token or any(c.isspace() for c in token):
            raise ValueError("invalid_identity_token")
        payload = json.dumps({"job_id": job_id, "epoch": epoch}).encode()
        request = Request(self.origin + "/events/retry", data=payload, method="POST",
                          headers={"Authorization": "Bearer " + token,
                                   "Content-Type": "application/json"})
        try:
            with self.opener.open(request, timeout=10) as response:
                return response.status == 204
        except HTTPError as exc:
            exc.close()
            return False
        except (OSError, URLError):
            return False
