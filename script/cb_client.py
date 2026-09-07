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


def build_body_payload(body, summary=None):
    """Build a page body write payload, including ``summary`` when provided.

    Shared by the CAS PUT path (put_cas) and the append path so the ``--sum``
    edit summary reaches the server's ``summary`` field (verified in
    PageController.validatePage + append, which accept an optional summary).
    """
    payload = {"body": body}
    if summary is not None:
        payload["summary"] = summary
    return payload


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

    def request(self, method, path, data=None, headers=None, params=None, raw=False):
        """Make an HTTP request to the API.

        Returns parsed JSON by default. When ``raw=True``, returns the raw
        response body bytes (used for binary downloads such as media-get).
        """
        url = self._build_url(path, params)
        status, body = self._make_request(method, url, data=data, headers=headers)
        if raw:
            return body
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

    def put_cas(self, page_id, body_or_mutate, revision=None, summary=None):
        """PUT a page with optimistic concurrency (CAS).

        ``body_or_mutate`` is either:

          - a ``str``: the full replacement body (replacement semantics — a
            concurrent change to the page does not alter the intent to replace
            the whole body), or
          - a callable ``f(fresh_body) -> str``: a mutation to (re-)apply to
            the current page body (used by edit/insert).

        On HTTP 412 the page is re-fetched ONCE and the write is re-applied
        against the fresh body:

          - callable: ``new_body = body_or_mutate(fresh_body)``
          - string:   the same body is re-sent (full replacement)

        A second 412 raises ``CorkboardError`` (status 412) with a CONFLICT
        message. ``summary``, when set, is sent as the page's edit summary.
        """
        return self._put_cas_internal(page_id, body_or_mutate, revision, summary, attempt=1)

    def _put_cas_internal(self, page_id, body_or_mutate, revision, summary, attempt):
        headers = {}
        body = body_or_mutate

        # A mutation callback needs the current body to derive the write;
        # fetch it now (and its revision, when the caller did not pin one).
        if callable(body_or_mutate):
            page = self.get_page(page_id)
            fresh_body = page.get("body", "")
            if revision is None:
                revision = page.get("revision") or page.get("body_revision")
            body = body_or_mutate(fresh_body)

        if revision is not None:
            headers["If-Match"] = f'"{revision}"'

        try:
            return self._put_page(page_id, body, summary, headers)
        except CorkboardError as e:
            if e.status != 412:
                raise
            if attempt >= 2:
                # Second 412 — a genuine conflict we will not resolve.
                raise CorkboardError(
                    "CONFLICT: page was modified by another writer",
                    status=412,
                    body=e.body,
                )
            # Re-fetch the page ONCE and re-apply against the fresh body.
            page = self.get_page(page_id)
            new_revision = page.get("revision") or page.get("body_revision")
            fresh_body = page.get("body", "")
            new_body = (
                body_or_mutate(fresh_body) if callable(body_or_mutate) else body
            )
            return self._put_cas_internal(
                page_id, new_body, new_revision, summary, attempt=attempt + 1
            )

    def _put_page(self, page_id, body, summary, headers):
        """PUT a page body with the given CAS headers and summary."""
        payload = build_body_payload(body, summary)
        return self.request("PUT", f"pages/{page_id}", data=payload, headers=headers)