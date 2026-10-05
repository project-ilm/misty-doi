"""Zenodo deposit client — automation-first, env-keyed, retrying.

This is the working flow from the original ``zenodo_publish.sh`` generalized:
create deposition -> PUT file(s) to the bucket -> PUT metadata -> POST publish.

Credentials come from the ``ZENODO_TOKEN`` environment variable by default
(``--token`` overrides). The sandbox host is selected by ``ZENODO_SANDBOX`` or
``sandbox=True``. Nothing is stored; the token lives only for the process.
"""

from __future__ import annotations

import os
import re
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
        # An explicit override exists so the flow can be exercised against a
        # local stand-in. Live Zenodo is never contacted by the test suite:
        # minting is irreversible, and a test that mints cannot be re-run.
        override = os.environ.get("ZENODO_API_BASE")
        self.base = override or (SANDBOX_API if self.sandbox else PROD_API)
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

    # -- versioning -------------------------------------------------------- #
    def get_deposition(self, dep_id: int) -> Dict[str, Any]:
        return self._check(
            self._request("GET", f"{self.base}/deposit/depositions/{dep_id}"),
            f"get deposition {dep_id}",
        ).json()

    def get_by_url(self, url: str) -> Dict[str, Any]:
        return self._check(self._request("GET", url), f"get {url}").json()

    def list_depositions(self, size: int = 100, all_versions: bool = True,
                         max_pages: int = 50) -> list:
        """Every deposition the token can see, paginated.

        ``all_versions`` matters: without it Zenodo hides superseded versions,
        which is exactly the history an audit needs to see.
        """
        out: list = []
        for page in range(1, max_pages + 1):
            params = {"page": page, "size": size, "sort": "mostrecent"}
            if all_versions:
                params["all_versions"] = "true"
            resp = self._check(
                self._request("GET", f"{self.base}/deposit/depositions", params=params),
                f"list depositions page {page}",
            )
            batch = resp.json()
            if not batch:
                break
            out.extend(batch)
            if len(batch) < size:
                break
        return out

    def new_version(self, dep_id: int) -> Dict[str, Any]:
        """Open (or reopen) the new-version draft of a PUBLISHED deposition.

        ``publish`` always mints a brand-new concept DOI; ``newversion`` keeps the
        concept DOI and adds a version DOI beneath it. Using the wrong one is
        unrecoverable without Zenodo support.

        Zenodo documents that this action answers with the PARENT record and puts
        the draft under ``links.latest_draft``; some deployments answer with the
        draft itself. Both are accepted, because both are unambiguous: the draft
        is either named by the link or is the body. Anything else is refused.
        Returns the draft, already fetched.
        """
        resp = self._check(
            self._request(
                "POST",
                f"{self.base}/deposit/depositions/{dep_id}/actions/newversion",
            ),
            f"new version of {dep_id}",
        )
        body = resp.json()
        draft_url = (body.get("links", {}) or {}).get("latest_draft")
        if draft_url:
            draft = self.get_by_url(draft_url)
        elif body.get("id") is not None and int(body["id"]) != int(dep_id) \
                and not body.get("submitted"):
            draft = body
        else:
            raise ZenodoError(
                f"Zenodo accepted newversion for {dep_id} but named no draft "
                "(no links.latest_draft and the body is not a draft); refusing to guess"
            )
        if draft.get("submitted") or draft.get("state") == "done":
            raise ZenodoError(f"the version draft {draft.get('id')} is already published; "
                              "refusing to modify a published record as if it were a draft")
        want = body.get("conceptrecid") or draft.get("conceptrecid")
        if want is not None and str(draft.get("conceptrecid")) != str(want):
            raise ZenodoError(f"the draft {draft.get('id')} belongs to concept "
                              f"{draft.get('conceptrecid')}, not {want}; refusing")
        return draft

    def edit(self, dep_id: int) -> Dict[str, Any]:
        """Unlock a PUBLISHED deposition's metadata for correction. Files stay locked."""
        return self._check(
            self._request("POST", f"{self.base}/deposit/depositions/{dep_id}/actions/edit"),
            f"edit {dep_id}",
        ).json()

    def lineage(self, concept: str) -> Tuple[Optional[Dict[str, Any]], list]:
        """(the latest PUBLISHED version of a concept, its unpublished drafts).

        The latest is the published deposition with the highest id under the
        concept: Zenodo allots ids in creation order and only the latest version
        may be versioned again.
        """
        deps = [d for d in self.list_depositions(all_versions=True)
                if str(d.get("conceptrecid") or "") == str(concept)]
        published = [d for d in deps if d.get("submitted") or d.get("state") == "done"]
        drafts = [d for d in deps if not (d.get("submitted") or d.get("state") == "done")]
        latest = max(published, key=lambda d: int(d.get("id", 0))) if published else None
        return latest, drafts

    def delete_file(self, dep_id: int, file_id: str) -> None:
        self._check(
            self._request(
                "DELETE", f"{self.base}/deposit/depositions/{dep_id}/files/{file_id}"
            ),
            f"delete file {file_id}",
        )

    def clear_files(self, dep_id: int) -> int:
        """Remove every file inherited by a new-version draft.

        A newversion draft arrives carrying the previous version's files. If you
        upload replacements without clearing, the record ends up with both, and
        the old ones are indistinguishable from the new to anyone downloading.
        """
        dep = self.get_deposition(dep_id)
        removed = 0
        for f in dep.get("files", []) or []:
            fid = f.get("id") or f.get("file_id")
            if fid:
                self.delete_file(dep_id, fid)
                removed += 1
        return removed

    def discard_draft(self, dep_id: int) -> None:
        """Throw away an unpublished draft — the only safe undo there is."""
        self._check(
            self._request(
                "POST", f"{self.base}/deposit/depositions/{dep_id}/actions/discard"
            ),
            f"discard draft {dep_id}",
        )


def concept_id(value: Any) -> str:
    """A concept given as a DOI, a DOI URL, 'zenodo.N' or N, as the bare record id."""
    v = str(value).strip().rstrip("/")
    m = re.search(r"(\d+)$", v)
    if not m:
        raise ValueError(f"not a Zenodo concept DOI or record id: {value}")
    return m.group(1)
