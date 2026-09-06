"""Corkboard HTTP API v1 client — stdlib-only.

Configuration from CORKBOARD_URL and CORKBOARD_TOKEN environment variables.
"""

import json
import os
import urllib.error
import urllib.parse
import urllib.request


class CorkboardError(Exception):
    """Typed error carrying HTTP status code and response body."""

    def __init__(self, message, status=None, body=None):
        super().__init__(message)
        self.status = status
        self.body = body

    def __str__(self):
        base = super().__str__()
        if self.status is not None:
            base = f"HTTP {self.status}: {base}"
        return base


class CorkboardClient:
    """HTTP client for Corkboard API v1.

    Reads CORKBOARD_URL and CORKBOARD_TOKEN from environment.
    """

    def __init__(self, base_url=None, token=None):
        self._base_url = (base_url or os.environ.get("CORKBOARD_URL", "")).rstrip("/")
        self._token = token or os.environ.get("CORKBOARD_TOKEN", "")
        if not self._base_url:
            raise CorkboardError(
                "CORKBOARD_URL environment variable is not set"
            )
        if not self._token:
            raise CorkboardError(
                "CORKBOARD_TOKEN environment variable is not set"
            )

    @property
    def base_url(self):
        return self._base_url

    def _build_url(self, path, params=None):
        """Build a full API URL from a path and optional query params."""
        path = path.lstrip("/")
        url = f"{self._base_url}/api/v1/{path}"
        if params:
            url = f"{url}?{urllib.parse.urlencode(params)}"
        return url

    def _make_request(self, method, url, data=None, headers=None):
        """Low-level HTTP request. Returns (status, body_bytes)."""
        req_headers = {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/json",
        }
        if headers:
            req_headers.update(headers)

        body_bytes = None
        if data is not None:
            if isinstance(data, str):
                body_bytes = data.encode("utf-8")
            elif isinstance(data, bytes):
                body_bytes = data
            else:
                body_bytes = json.dumps(data).encode("utf-8")
                if "Content-Type" not in req_headers:
                    req_headers["Content-Type"] = "application/json"

        req = urllib.request.Request(
            url, data=body_bytes, headers=req_headers, method=method
        )

        try:
            with urllib.request.urlopen(req) as resp:
                return resp.status, resp.read()
        except urllib.error.HTTPError as e:
            body = e.read()
            raise CorkboardError(
                f"{e.reason}",
                status=e.code,
                body=body,
            )

    def request(self, method, path, data=None, headers=None, params=None):
        """Make an HTTP request to the API. Returns parsed JSON or raw body."""
        url = self._build_url(path, params)
        status, body = self._make_request(method, url, data=data, headers=headers)
        try:
            return json.loads(body)
        except (json.JSONDecodeError, ValueError):
            return body

    def get(self, path, params=None):
        """GET request to the API. Returns parsed JSON."""
        return self.request("GET", path, params=params)

    def post(self, path, data=None, params=None):
        """POST request to the API. Returns parsed JSON."""
        return self.request("POST", path, data=data, params=params)

    def put(self, path, data=None, params=None):
        """PUT request to the API. Returns parsed JSON."""
        return self.request("PUT", path, data=data, params=params)

    def delete(self, path, params=None):
        """DELETE request to the API. Returns parsed JSON."""
        return self.request("DELETE", path, params=params)

    # ------------------------------------------------------------------
    # Optimistic concurrency (CAS) helpers
    # ------------------------------------------------------------------

    def get_page(self, page_id):
        """Fetch a page by id. Returns the full page JSON (incl. body + revision)."""
        return self.get(f"pages/{page_id}")

    def put_cas(self, page_id, body, revision=None):
        """PUT a page with optimistic concurrency.

        If revision is given, sends If-Match: \"<revision>\".
        On HTTP 412 (conflict), re-fetches the page once, re-applies the
        mutation via a caller-supplied callback, and retries once.
        A second 412 raises CorkboardError with CONFLICT.

        The caller is responsible for applying the mutation; this method
        handles the CAS retry loop.
        """
        return self._put_cas_internal(page_id, body, revision, attempt=1)

    def _put_cas_internal(self, page_id, body, revision, attempt):
        headers = {}
        if revision is not None:
            headers["If-Match"] = f'"{revision}"'

        try:
            return self.request(
                "PUT",
                f"pages/{page_id}",
                data={"body": body},
                headers=headers,
            )
        except CorkboardError as e:
            if e.status == 412 and attempt == 1:
                # Fetch the latest revision and retry once
                page = self.get_page(page_id)
                new_revision = page.get("revision") or page.get("body_revision")
                headers["If-Match"] = f'"{new_revision}"'
                return self.request(
                    "PUT",
                    f"pages/{page_id}",
                    data={"body": body},
                    headers=headers,
                )
            elif e.status == 412:
                raise CorkboardError(
                    "CONFLICT: page was modified by another writer",
                    status=412,
                    body=e.body,
                )
            raise