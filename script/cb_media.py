#!/usr/bin/env python3
"""Media commands for the Corkboard CLI.

Talks to the Corkboard HTTP API v1.  Stdlib-only.
Each command is a plain function taking (client, args).  The register hook
wires them into an argparse subparser.
"""

from __future__ import annotations

import base64
import mimetypes
import os
import sys


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _media_id(ns, name):
    """Build a media ID from namespace and name.

    Per the API contract, media ids use ``/`` as the namespace separator.
    """
    ns = ns or ""
    return f"{ns}/{name}" if ns else name


def _detect_content_type(filepath):
    """Guess the Content-Type for a file based on its extension."""
    ct, _ = mimetypes.guess_type(filepath)
    return ct or "application/octet-stream"


def _handle_http_error(err):
    """Print a uniform error message for HTTP errors."""
    body = getattr(err, "body", None)
    if body is None:
        msg = f"error: HTTP {err.status}"
    elif isinstance(body, bytes):
        msg = f"error: HTTP {err.status} — {body.decode('utf-8', errors='replace')[:200]}"
    else:
        msg = f"error: HTTP {err.status} — {str(body)[:200]}"
    print(msg, file=sys.stderr)
    raise SystemExit(1)


# ---------------------------------------------------------------------------
# CLI commands  (client, args) -> None
# ---------------------------------------------------------------------------

def cmd_media_upload(client, args):
    """Upload a media file.

    Tries raw binary PUT first (with Content-Type from file extension).
    If the API rejects the content type (400/415/422), falls back to
    JSON ``{"content_b64": "<base64>"}``.

    The working form is raw-binary for the v1 API; base64 is a fallback
    for older gateways.
    """
    filepath = args.file
    if not os.path.isfile(filepath):
        print(f"error: file not found: {filepath}", file=sys.stderr)
        raise SystemExit(1)

    with open(filepath, "rb") as f:
        raw_bytes = f.read()

    mid = _media_id(args.ns, args.name)
    content_type = _detect_content_type(filepath)

    # Attempt 1: raw binary PUT
    try:
        status, _body = client.request(
            "PUT",
            f"/api/v1/media/{mid}",
            data=raw_bytes,
            headers={"Content-Type": content_type},
        )
        if status < 400:
            print(mid)
            return
        if status not in (400, 415, 422):
            # Not a content-type rejection — raise
            from types import SimpleNamespace
            err = SimpleNamespace(status=status, body=_body)
            _handle_http_error(err)
    except Exception as e:
        if hasattr(e, "status"):
            if e.status not in (400, 415, 422):
                _handle_http_error(e)
        else:
            raise

    # Attempt 2: base64 JSON fallback
    b64 = base64.b64encode(raw_bytes).decode("ascii")
    try:
        status, _body = client.request(
            "PUT",
            f"/api/v1/media/{mid}",
            json_body={"content_b64": b64},
        )
    except Exception as e:
        if hasattr(e, "status"):
            _handle_http_error(e)
        raise

    if status >= 400:
        from types import SimpleNamespace
        err = SimpleNamespace(status=status, body=_body)
        _handle_http_error(err)

    print(mid)


def cmd_media_get(client, args):
    """Download a media file.

    Writes bytes to ``args.out`` (or stdout if ``-`` / not given).
    """
    try:
        status, data = client.request("GET", f"/api/v1/media/{args.id}")
    except Exception as e:
        if hasattr(e, "status"):
            _handle_http_error(e)
        raise

    if status >= 400:
        from types import SimpleNamespace
        err = SimpleNamespace(status=status, body=data)
        _handle_http_error(err)

    if args.out and args.out != "-":
        with open(args.out, "wb") as f:
            f.write(data if isinstance(data, bytes) else str(data).encode())
    else:
        sys.stdout.buffer.write(data if isinstance(data, bytes) else str(data).encode())


def cmd_media_list(client, args):
    """List media files, optionally filtered by namespace."""
    params = {}
    if args.ns:
        params["ns"] = args.ns
    try:
        data = client.get("/api/v1/media", **params)
    except Exception as e:
        if hasattr(e, "status"):
            _handle_http_error(e)
        raise

    if isinstance(data, list):
        for item in data:
            print(item.get("id", item) if isinstance(item, dict) else item)
    else:
        print(str(data))


def cmd_media_delete(client, args):
    """Delete a media file."""
    try:
        status, _body = client.request("DELETE", f"/api/v1/media/{args.id}")
    except Exception as e:
        if hasattr(e, "status"):
            _handle_http_error(e)
        raise

    if status >= 400:
        from types import SimpleNamespace
        err = SimpleNamespace(status=status, body=_body)
        _handle_http_error(err)

    print(f"deleted {args.id}")


def cmd_media_move(client, args):
    """Move/rename a media file."""
    try:
        status, _body = client.request(
            "POST",
            f"/api/v1/media/{args.src}/move",
            json_body={"destination": args.dst},
        )
    except Exception as e:
        if hasattr(e, "status"):
            _handle_http_error(e)
        raise

    if status >= 400:
        from types import SimpleNamespace
        err = SimpleNamespace(status=status, body=_body)
        _handle_http_error(err)

    print(f"moved {args.src} → {args.dst}")


def cmd_media_orphans(client, args):
    """List unreferenced media files."""
    try:
        data = client.get("/api/v1/media", filter="orphans")
    except Exception as e:
        if hasattr(e, "status"):
            _handle_http_error(e)
        raise

    if isinstance(data, list):
        for item in data:
            print(item.get("id", item) if isinstance(item, dict) else item)
    else:
        print(str(data))


def cmd_media_usage(client, args):
    """Show which pages reference a media file."""
    try:
        data = client.get(f"/api/v1/media/{args.id}/usage")
    except Exception as e:
        if hasattr(e, "status"):
            _handle_http_error(e)
        raise

    if isinstance(data, list):
        for item in data:
            print(item.get("id", item) if isinstance(item, dict) else item)
    else:
        print(str(data))


# ---------------------------------------------------------------------------
# Argparse registration hook
# ---------------------------------------------------------------------------

def register_media(subparsers, client_factory):
    """Register all media sub-commands on the given subparsers object.

    ``client_factory`` is a callable that returns a client object.
    Each command receives ``(client, args)`` where ``client`` is the result
    of ``client_factory()``.
    """

    # media-upload <file> <ns> <name> [--no-overwrite]
    p_upload = subparsers.add_parser("media-upload",
                                     help="Upload a media file")
    p_upload.add_argument("file", help="Path to the file to upload")
    p_upload.add_argument("ns", help="Target namespace")
    p_upload.add_argument("name", help="Media name (leaf)")
    p_upload.add_argument("--no-overwrite", action="store_true",
                          help="Fail if the media id already exists")
    p_upload.set_defaults(func=lambda args: cmd_media_upload(client_factory(), args))

    # media-get <id> [-o OUT]
    p_get = subparsers.add_parser("media-get",
                                  help="Download a media file")
    p_get.add_argument("id", help="Media id (e.g. ns/file.png)")
    p_get.add_argument("-o", dest="out", default=None,
                       help="Output file path (default: stdout)")
    p_get.set_defaults(func=lambda args: cmd_media_get(client_factory(), args))

    # media-list [--ns N]
    p_list = subparsers.add_parser("media-list",
                                   help="List media files")
    p_list.add_argument("--ns", default=None, help="Namespace filter")
    p_list.set_defaults(func=lambda args: cmd_media_list(client_factory(), args))

    # media-delete <id>
    p_delete = subparsers.add_parser("media-delete",
                                     help="Delete a media file")
    p_delete.add_argument("id", help="Media id to delete")
    p_delete.set_defaults(func=lambda args: cmd_media_delete(client_factory(), args))

    # media-move <src> <dst>
    p_move = subparsers.add_parser("media-move",
                                   help="Move/rename a media file")
    p_move.add_argument("src", help="Source media id")
    p_move.add_argument("dst", help="Destination media id")
    p_move.set_defaults(func=lambda args: cmd_media_move(client_factory(), args))

    # media-orphans
    p_orphans = subparsers.add_parser("media-orphans",
                                      help="List unreferenced media files")
    p_orphans.set_defaults(func=lambda args: cmd_media_orphans(client_factory(), args))

    # media-usage <id>
    p_usage = subparsers.add_parser("media-usage",
                                    help="Show pages referencing a media file")
    p_usage.add_argument("id", help="Media id")
    p_usage.set_defaults(func=lambda args: cmd_media_usage(client_factory(), args))