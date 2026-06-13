"""Zenodo deposit client — automation-first, env-keyed, retrying.

This is the working flow from the original ``zenodo_publish.sh`` generalized:
create deposition -> PUT file(s) to the bucket -> PUT metadata -> POST publish.

Credentials come from the ``ZENODO_TOKEN`` environment variable by default
(``--token`` overrides). The sandbox host is selected by ``ZENODO_SANDBOX`` or
``sandbox=True``. Nothing is stored; the token lives only for the process.
"""

from __future__ import annotations

import os
import time
from typing import Any, Dict, Optional, Tuple

from .errors import ConfigError, ZenodoError

PROD_API = "https://zenodo.org/api"
SANDBOX_API = "https://sandbox.zenodo.org/api"
_TRUTHY = {"1", "true", "yes", "on"}


class ZenodoClient:
    def __init__(
        self,
        token: Optional[str] = None,
        sandbox: Optional[bool] = None,
        timeout: int = 120,
        retries: int = 3,
    ):
        self.token = token or os.environ.get("ZENODO_TOKEN")
        if not self.token:
            raise ConfigError(
                "no Zenodo token: export ZENODO_TOKEN=... (or pass --token)"
            )
        if sandbox is None:
            sandbox = os.environ.get("ZENODO_SANDBOX", "").lower() in _TRUTHY
        self.sandbox = bool(sandbox)
        self.base = SANDBOX_API if self.sandbox else PROD_API
        self.timeout = timeout
        self.retries = max(1, retries)

        try:
            import requests  # noqa: F401
        except ImportError as exc:
            raise ConfigError(
                "the `requests` package is required for publishing "
                "(`pip install requests`)"
            ) from exc
        import requests
        self._session = requests.Session()
        self._session.headers["Authorization"] = f"Bearer {self.token}"

    # -- low level --------------------------------------------------------- #
    def _request(self, method: str, url: str, **kw) -> Any:
        import requests
        kw.setdefault("timeout", self.timeout)
        last: Optional[Exception] = None
        for attempt in range(self.retries):
            try:
                resp = self._session.request(method, url, **kw)
            except requests.RequestException as exc:  # network-level
                last = exc
                time.sleep(2 ** attempt)
                continue
            if resp.status_code >= 500:  # transient server error -> retry
                last = ZenodoError(f"{resp.status_code} from Zenodo: {resp.text[:300]}")
                time.sleep(2 ** attempt)
                continue
            return resp
        raise ZenodoError(f"request to {url} failed after {self.retries} tries: {last}")

    @staticmethod
    def _check(resp, action: str):
        if resp.status_code >= 400:
            try:
                detail = resp.json()
            except Exception:
                detail = resp.text[:500]
            raise ZenodoError(f"{action} failed [{resp.status_code}]: {detail}")
        return resp

    # -- deposit API ------------------------------------------------------- #
    def create_deposition(self) -> Tuple[int, str, Dict[str, Any]]:
        resp = self._check(
            self._request(
                "POST", f"{self.base}/deposit/depositions",
                json={}, headers={"Content-Type": "application/json"},
            ),
            "create deposition",
        )
        data = resp.json()
        return data["id"], data["links"]["bucket"], data

    def upload_file(self, bucket: str, path: str, name: Optional[str] = None) -> Dict[str, Any]:
        name = name or os.path.basename(path)
        with open(path, "rb") as fh:  # streamed; constant memory
            resp = self._check(
                self._request("PUT", f"{bucket}/{name}", data=fh),
                f"upload {name}",
            )
        return resp.json()

    def set_metadata(self, dep_id: int, zenodo_metadata: Dict[str, Any]) -> Dict[str, Any]:
        resp = self._check(
            self._request(
                "PUT", f"{self.base}/deposit/depositions/{dep_id}",
                json={"metadata": zenodo_metadata},
                headers={"Content-Type": "application/json"},
            ),
            "set metadata",
        )
        return resp.json()

    def publish(self, dep_id: int) -> Dict[str, Any]:
        resp = self._check(
            self._request(
                "POST", f"{self.base}/deposit/depositions/{dep_id}/actions/publish"
            ),
            "publish",
        )
        return resp.json()
