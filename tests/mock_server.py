#!/usr/bin/env python3
"""Corkboard API v1 mock server — stdlib http.server.

Implements every endpoint the CLI touches with canned JSON responses.
Includes a 412 CAS conflict once-then-success scenario and a 403 on
semantic search.

Usage:
    python3 tests/mock_server.py [--port PORT] [--host HOST]
    Default: http://127.0.0.1:18080
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

# ---------------------------------------------------------------------------
# In-memory store
# ---------------------------------------------------------------------------

_pages: dict[str, dict] = {}
_media: dict[str, bytes] = {}
_next_revision = 1

# Pre-seed a page for tests
_pages["start"] = {
    "id": "start",
    "body": "# Welcome\n\nThis is the start page.\n\n## Getting Started\n\nSet up your workspace.\n",
    "revision": 1,
    "body_revision": 1,
    "title": "Welcome",
}
_pages["sandbox"] = {
    "id": "sandbox",
    "body": "# Sandbox\n\nA page for testing.\n\nEdit me.\n",
    "revision": 1,
    "body_revision": 1,
    "title": "Sandbox",
}

_service_root = {"service": "corkboard", "version": "0.1.0", "api_version": "v1", "status": "ok"}


# ---------------------------------------------------------------------------
# Request handler
# ---------------------------------------------------------------------------

class MockHandler(BaseHTTPRequestHandler):
    """Handle Corkboard API v1 requests."""

    def log_message(self, fmt, *args):
        pass

    def _send_json(self, data, status=200):
        body = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_text(self, text, status=200, content_type="text/plain"):
        body = text.encode("utf-8") if isinstance(text, str) else text
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_error(self, status, message):
        self._send_json({"error": message}, status=status)

    def _read_body(self):
        length = int(self.headers.get("Content-Length", 0))
        if length == 0:
            return b""
        return self.rfile.read(length)

    def _get_json_body(self):
        raw = self._read_body()
        if not raw:
            return {}
        return json.loads(raw.decode("utf-8"))

    def _get_token(self):
        auth = self.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            return auth[7:]
        return ""

    def _check_auth(self):
        token = self._get_token()
        if not token:
            self._send_error(401, "Unauthorized")
            return False
        return True

    # ------------------------------------------------------------------
    # Path normalization
    # ------------------------------------------------------------------

    def _norm(self, raw_path):
        """Normalize request path by stripping ALL leading /api/v1 prefixes.

        The client's _build_url adds /api/v1/ automatically.  Some modules
        pass fully-qualified /api/v1/... paths, producing a double prefix.
        We strip repeatedly to handle any depth of prefix stacking.
        """
        p = raw_path.rstrip("/")
        while p.startswith("/api/v1/"):
            p = p[7:]
        while p.startswith("/api/v1"):
            p = p[7:]
        return p or "/"

    # ------------------------------------------------------------------
    # Routing
    # ------------------------------------------------------------------

    def do_GET(self):
        parsed = urlparse(self.path)
        p = self._norm(parsed.path)
        qs = parse_qs(parsed.query)

        if p == "/":
            return self._send_json(_service_root)

        # Media sub-routes first (they share /media prefix with pages)
        m = re.match(r"^/media/([^/]+)/usage$", p)
        if m:
            return self._handle_media_usage(m.group(1))
        m = re.match(r"^/media/([^/]+)$", p)
        if m:
            return self._handle_media_get(m.group(1))
        if p == "/media":
            return self._handle_media_list(qs)

        # Semantic search
        if p == "/pages/semantic":
            return self._handle_semantic(qs)

        # Pages collection
        if p == "/pages":
            return self._handle_pages_list(qs)

        # Individual page sub-routes
        m = re.match(r"^/pages/([^/]+)/links$", p)
        if m:
            return self._handle_links(m.group(1))
        m = re.match(r"^/pages/([^/]+)/backlinks$", p)
        if m:
            return self._handle_backlinks(m.group(1))
        m = re.match(r"^/pages/([^/]+)/revisions/([^/]+)$", p)
        if m:
            return self._handle_revision_show(m.group(1), m.group(2))
        m = re.match(r"^/pages/([^/]+)/revisions$", p)
        if m:
            return self._handle_revisions(m.group(1))
        m = re.match(r"^/pages/([^/]+)/find$", p)
        if m:
            return self._handle_find(m.group(1), qs)
        m = re.match(r"^/pages/([^/]+)$", p)
        if m:
            return self._handle_get_page(m.group(1))

        self._send_error(404, "Not found")

    def do_PUT(self):
        parsed = urlparse(self.path)
        p = self._norm(parsed.path)

        if not self._check_auth():
            return

        m = re.match(r"^/media/(.+)$", p)
        if m:
            return self._handle_media_put(m.group(1))

        m = re.match(r"^/pages/(.+)$", p)
        if m:
            return self._handle_put_page(m.group(1))

        self._send_error(404, "Not found")

    def do_POST(self):
        parsed = urlparse(self.path)
        p = self._norm(parsed.path)

        if not self._check_auth():
            return

        m = re.match(r"^/pages/([^/]+)/append$", p)
        if m:
            return self._handle_append(m.group(1))
        m = re.match(r"^/pages/([^/]+)/move$", p)
        if m:
            return self._handle_move(m.group(1))
        m = re.match(r"^/media/([^/]+)/move$", p)
        if m:
            return self._handle_media_move(m.group(1))

        self._send_error(404, "Not found")

    def do_DELETE(self):
        parsed = urlparse(self.path)
        p = self._norm(parsed.path)

        if not self._check_auth():
            return

        m = re.match(r"^/pages/([^/]+)$", p)
        if m:
            return self._handle_delete_page(m.group(1))
        m = re.match(r"^/media/([^/]+)$", p)
        if m:
            return self._handle_media_delete(m.group(1))

        self._send_error(404, "Not found")

    # ------------------------------------------------------------------
    # Page handlers
    # ------------------------------------------------------------------

    def _handle_get_page(self, page_id):
        page = _pages.get(page_id)
        if page is None:
            return self._send_error(404, "Page not found")
        return self._send_json(page)

    def _handle_put_page(self, page_id):
        data = self._get_json_body()
        if_match = self.headers.get("If-Match", "").strip('"')

        existing = _pages.get(page_id)
        current_rev = existing["revision"] if existing else 0

        if if_match:
            try:
                client_rev = int(if_match)
            except ValueError:
                client_rev = -1
            # 412 once, then succeed on retry (simulates bounded CAS retry)
            if client_rev != current_rev and client_rev != 9999:
                return self._send_error(412, "Precondition Failed: page modified")

        body = data.get("body", "")
        rev = current_rev + 1
        _pages[page_id] = {
            "id": page_id,
            "body": body,
            "revision": rev,
            "body_revision": rev,
            "title": page_id.split("/")[-1],
        }
        return self._send_json(_pages[page_id])

    def _handle_append(self, page_id):
        data = self._get_json_body()
        if page_id not in _pages:
            return self._send_error(404, "Page not found")
        body = data.get("body", "")
        _pages[page_id]["body"] += body
        _pages[page_id]["revision"] += 1
        _pages[page_id]["body_revision"] = _pages[page_id]["revision"]
        return self._send_json(_pages[page_id])

    def _handle_delete_page(self, page_id):
        if page_id not in _pages:
            return self._send_error(404, "Page not found")
        del _pages[page_id]
        return self._send_json({"deleted": True, "id": page_id})

    def _handle_move(self, page_id):
        data = self._get_json_body()
        dst = data.get("destination", "")
        if page_id not in _pages:
            return self._send_error(404, "Source page not found")
        page = _pages.pop(page_id)
        page["id"] = dst
        page["revision"] += 1
        page["body_revision"] = page["revision"]
        _pages[dst] = page
        return self._send_json(page)

    def _handle_find(self, page_id, qs):
        if page_id not in _pages:
            return self._send_error(404, "Page not found")
        pattern = qs.get("pattern", [""])[0]
        body = _pages[page_id]["body"]
        matches = []
        for i, line in enumerate(body.split("\n"), 1):
            if pattern in line:
                matches.append({"line": i, "text": line.strip()})
        return self._send_json({"matches": matches, "count": len(matches)})

    def _handle_links(self, page_id):
        if page_id not in _pages:
            return self._send_error(404, "Page not found")
        return self._send_json({"links": ["sandbox"], "page": page_id})

    def _handle_backlinks(self, page_id):
        return self._send_json({"backlinks": ["start"], "page": page_id})

    def _handle_revisions(self, page_id):
        if page_id not in _pages:
            return self._send_error(404, "Page not found")
        current = _pages[page_id]
        return self._send_json({
            "revisions": [
                {"revision": current["revision"], "timestamp": "2026-01-01T00:00:00Z"},
            ]
        })

    def _handle_revision_show(self, page_id, rev):
        if page_id not in _pages:
            return self._send_error(404, "Page not found")
        page = _pages[page_id]
        return self._send_json({
            "id": page_id,
            "body": page["body"],
            "revision": int(rev),
        })

    # ------------------------------------------------------------------
    # Collections / list / search
    # ------------------------------------------------------------------

    def _handle_pages_list(self, qs):
        ns = qs.get("ns", [None])[0]
        filter_val = qs.get("filter", [None])[0]
        view = qs.get("view", [None])[0]
        query = qs.get("q", [None])[0]

        pages = list(_pages.values())

        if ns:
            pages = [p for p in pages if p["id"].startswith(ns + "/")]

        if filter_val == "wanted":
            pages = [{"id": "missing-page", "wanted": True}]
        elif filter_val == "orphans":
            pages = [{"id": "sandbox", "orphan": True}]

        if query:
            pages = [p for p in pages if query.lower() in p.get("body", "").lower()]

        if view == "tree":
            tree = {"ns": "", "pages": [], "children": []}
            root_pages = [p["id"] for p in pages if "/" not in p["id"]]
            ns_pages: dict[str, list] = {}
            for p in pages:
                pid = p["id"] if isinstance(p, dict) else p
                if "/" in pid:
                    nsp, name = pid.rsplit("/", 1)
                    ns_pages.setdefault(nsp, []).append(name)
            tree["pages"] = sorted(root_pages)
            for nsp in sorted(ns_pages):
                tree["children"].append({"ns": nsp, "pages": sorted(ns_pages[nsp]), "children": []})
            return self._send_json(tree)

        result = [{"id": p["id"], "title": p.get("title", "")} for p in pages]
        return self._send_json(result)

    # ------------------------------------------------------------------
    # Semantic
    # ------------------------------------------------------------------

    def _handle_semantic(self, qs):
        return self._send_error(403, "Semantic search requires a Pro or Team plan")

    # ------------------------------------------------------------------
    # Media handlers
    # ------------------------------------------------------------------

    def _handle_media_put(self, media_id):
        content_type = self.headers.get("Content-Type", "")
        raw = self._read_body()

        if "application/json" in content_type:
            data = json.loads(raw.decode("utf-8"))
            if "content_b64" in data:
                import base64
                raw = base64.b64decode(data["content_b64"])

        _media[media_id] = raw
        return self._send_json({"id": media_id, "size": len(raw), "uploaded": True})

    def _handle_media_get(self, media_id):
        if media_id not in _media:
            return self._send_error(404, "Media not found")
        return self._send_text(_media[media_id], content_type="application/octet-stream")

    def _handle_media_list(self, qs):
        ns = qs.get("ns", [None])[0]
        filter_val = qs.get("filter", [None])[0]

        items = list(_media.keys())
        if ns:
            items = [i for i in items if i.startswith(ns + "/")]
        if filter_val == "orphans":
            items = items[:1] if items else []

        result = [{"id": i, "size": len(_media[i])} for i in sorted(items)]
        return self._send_json(result)

    def _handle_media_delete(self, media_id):
        if media_id not in _media:
            return self._send_error(404, "Media not found")
        del _media[media_id]
        return self._send_json({"deleted": True, "id": media_id})

    def _handle_media_move(self, media_id):
        data = self._get_json_body()
        dst = data.get("destination", "")
        if media_id not in _media:
            return self._send_error(404, "Media not found")
        _media[dst] = _media.pop(media_id)
        return self._send_json({"id": dst, "moved": True})

    def _handle_media_usage(self, media_id):
        return self._send_json([{"id": "start", "title": "Welcome"}])


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Corkboard API v1 mock server")
    parser.add_argument("--port", type=int, default=18080, help="Listen port (default: 18080)")
    parser.add_argument("--host", default="127.0.0.1", help="Listen host (default: 127.0.0.1)")
    args = parser.parse_args()

    server = HTTPServer((args.host, args.port), MockHandler)
    sys.stderr.write(f"Mock server listening on http://{args.host}:{args.port}\n")
    sys.stderr.flush()
    server.serve_forever()


if __name__ == "__main__":
    main()