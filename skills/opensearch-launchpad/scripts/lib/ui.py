"""Search Builder UI server for Agent Skills standalone path.

Serves the static React frontend and proxies search requests to OpenSearch.
Matches the MCP path's full-featured search UI with smart field detection,
semantic/hybrid search, agentic search, suggestions, and autocomplete.
"""

import json
import os
import re
import signal
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .client import create_client, can_connect, build_client, resolve_http_auth
from .search import (
    autocomplete,
    extract_index_field_specs,
    generate_suggestions,
    search_ui_search,
)

SEARCH_UI_HOST = os.getenv("SEARCH_UI_HOST", "127.0.0.1")
SEARCH_UI_PORT = int(os.getenv("SEARCH_UI_PORT", "8765"))

# Find UI static assets - look relative to repo root
_SCRIPT_DIR = Path(__file__).resolve().parent.parent
_REPO_ROOT = _SCRIPT_DIR.parent.parent.parent
SEARCH_UI_STATIC_DIR = _REPO_ROOT / "opensearch_orchestrator" / "ui" / "search_builder"

_CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
}

# Mutable state
_default_index = ""
_endpoint_override = {}  # {host, port, use_ssl, auth, aws_region, aws_service}


def _get_client():
    override = _endpoint_override
    if override.get("host"):
        from .client import create_remote_client
        return create_remote_client(
            endpoint=override["host"],
            port=override.get("port", 443),
            use_ssl=override.get("use_ssl", True),
            username=override.get("username", ""),
            password=override.get("password", ""),
            aws_region=override.get("aws_region", ""),
            aws_service=override.get("aws_service", ""),
        )
    return create_client()


def _resolve_asset(path: str) -> Path | None:
    if not SEARCH_UI_STATIC_DIR.exists():
        return None
    clean = path.lstrip("/") or "index.html"
    target = (SEARCH_UI_STATIC_DIR / clean).resolve()
    if target.is_file() and str(target).startswith(str(SEARCH_UI_STATIC_DIR)):
        return target
    return None


class _UIHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass  # Suppress request logging

    def _send_json(self, data: dict, status: int = 200):
        body = json.dumps(data, default=str, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)

        # Health check
        if parsed.path in ("/_health", "/api/health"):
            backend = _get_backend_info()
            self._send_json({
                "ok": True,
                "status": "running",
                "default_index": _default_index,
                "pid": os.getpid(),
                "backend_type": backend["backend_type"],
                "endpoint": backend["endpoint"],
                "connected": backend["connected"],
            })
            return

        # Config
        if parsed.path == "/api/config":
            backend = _get_backend_info()
            self._send_json({
                "default_index": _default_index,
                "backend_type": backend["backend_type"],
                "endpoint": backend["endpoint"],
                "connected": backend["connected"],
            })
            return

        # Suggestions
        if parsed.path == "/api/suggestions":
            index_name = (params.get("index") or [""])[0] or _default_index
            try:
                client = _get_client()
                suggestions = generate_suggestions(client, index_name, max_count=6)
                self._send_json({
                    "suggestions": suggestions,
                    "index": index_name,
                })
            except Exception as e:
                self._send_json({"suggestions": [], "index": index_name, "error": str(e)})
            return

        # Autocomplete
        if parsed.path == "/api/autocomplete":
            index_name = (params.get("index") or [""])[0] or _default_index
            prefix_text = (params.get("q") or [""])[0]
            field_name = (params.get("field") or [""])[0]
            try:
                ac_size = int((params.get("size") or ["8"])[0])
            except ValueError:
                ac_size = 8
            ac_size = max(1, min(ac_size, 20))
            try:
                client = _get_client()
                result = autocomplete(
                    client, index_name, prefix_text,
                    size=ac_size, preferred_field=field_name,
                )
                self._send_json(result)
            except Exception as e:
                self._send_json({
                    "index": index_name, "prefix": prefix_text,
                    "field": "", "options": [], "error": str(e),
                })
            return

        # Search API
        if parsed.path == "/api/search":
            self._handle_search(params)
            return

        # Static file
        asset = _resolve_asset(parsed.path)
        if asset is None:
            asset = _resolve_asset("/index.html")
        if asset is None:
            self.send_error(404)
            return

        content_type = _CONTENT_TYPES.get(asset.suffix, "application/octet-stream")
        body = asset.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/search":
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length)) if length else {}
            self._handle_search_post(body)
            return
        self.send_error(404)

    def _handle_search(self, params: dict):
        query = (params.get("q") or params.get("query") or [""])[0]
        index = (params.get("index") or [_default_index])[0] or _default_index
        search_intent = (params.get("intent") or [""])[0]
        field_hint = (params.get("field") or [""])[0]
        debug_param = (params.get("debug") or ["0"])[0].strip().lower()
        debug_mode = debug_param in {"1", "true", "yes", "on"}
        try:
            size = int((params.get("size") or ["20"])[0])
        except ValueError:
            size = 20
        size = max(1, min(size, 50))

        if not index:
            self._send_json({"error": "No index specified."}, 400)
            return

        try:
            client = _get_client()
            result = search_ui_search(
                client=client,
                index_name=index,
                query_text=query,
                size=size,
                debug=debug_mode,
                search_intent=search_intent,
                field_hint=field_hint,
            )
            self._send_json(result)
        except Exception as e:
            self._send_json({
                "error": str(e),
                "hits": [], "took_ms": 0,
                "query_mode": "", "capability": "",
                "used_semantic": False, "fallback_reason": "",
            }, status=500)

    def _handle_search_post(self, body: dict):
        index = body.pop("index", _default_index) or _default_index
        size = body.pop("size", 20)
        if not index:
            self._send_json({"error": "No index specified."}, 400)
            return
        try:
            client = _get_client()
            # If the POST body has a "query" key, treat as raw DSL pass-through
            if "query" in body:
                result = client.search(index=index, body=body, size=size)
                self._send_json(result)
            else:
                # Otherwise treat as a structured search request
                query_text = body.get("q", body.get("query_text", ""))
                debug = body.get("debug", False)
                result = search_ui_search(
                    client=client,
                    index_name=index,
                    query_text=query_text,
                    size=size,
                    debug=debug,
                )
                self._send_json(result)
        except Exception as e:
            self._send_json({"error": str(e)}, 500)


def _get_backend_info() -> dict:
    override = _endpoint_override
    if override.get("host"):
        endpoint = override["host"]
        backend_type = "aws" if override.get("aws_region") else "remote"
        try:
            client = _get_client()
            ok, _ = can_connect(client)
            connected = ok
        except Exception:
            connected = False
        return {"backend_type": backend_type, "endpoint": endpoint, "connected": connected}
    from .client import OPENSEARCH_HOST, OPENSEARCH_PORT
    endpoint = f"{OPENSEARCH_HOST}:{OPENSEARCH_PORT}"
    try:
        client = _get_client()
        ok, _ = can_connect(client)
        connected = ok
    except Exception:
        connected = False
    return {"backend_type": "local", "endpoint": endpoint, "connected": connected}


def launch_ui(index_name: str = "") -> str:
    global _default_index
    if index_name:
        _default_index = index_name

    if not SEARCH_UI_STATIC_DIR.exists():
        return (
            f"Error: Search UI static directory not found at {SEARCH_UI_STATIC_DIR}. "
            "Make sure you cloned the full opensearch-launchpad repository."
        )

    try:
        server = ThreadingHTTPServer((SEARCH_UI_HOST, SEARCH_UI_PORT), _UIHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        url = f"http://{SEARCH_UI_HOST}:{SEARCH_UI_PORT}"

        # Wait for ready
        import urllib.request
        for _ in range(20):
            try:
                urllib.request.urlopen(f"{url}/_health", timeout=1)
                break
            except Exception:
                time.sleep(0.25)

        msg = f"Search Builder UI started at: {url}"
        if _default_index:
            msg += f"\nDefault index: {_default_index}"
        return msg

    except OSError as e:
        if "Address already in use" in str(e):
            url = f"http://{SEARCH_UI_HOST}:{SEARCH_UI_PORT}"
            return f"Search Builder UI already running at: {url}"
        return f"Failed to start Search UI: {e}"


def connect_ui(
    endpoint: str,
    port: int = 443,
    use_ssl: bool = True,
    username: str = "",
    password: str = "",
    aws_region: str = "",
    aws_service: str = "",
    index_name: str = "",
) -> str:
    global _default_index, _endpoint_override

    if not endpoint:
        return "Error: endpoint is required."

    # Auto-detect AWS service from endpoint
    if not aws_service and aws_region:
        if ".aoss." in endpoint:
            aws_service = "aoss"
        elif ".es." in endpoint or ".aos." in endpoint:
            aws_service = "es"
    if not aws_region and (".aoss." in endpoint or ".es." in endpoint):
        m = re.search(r"\.([a-z]{2}-[a-z]+-\d+)\.", endpoint)
        if m:
            aws_region = m.group(1)
            if not aws_service:
                aws_service = "aoss" if ".aoss." in endpoint else "es"

    _endpoint_override = {
        "host": endpoint, "port": port, "use_ssl": use_ssl,
        "username": username, "password": password,
        "aws_region": aws_region, "aws_service": aws_service,
    }

    # Verify connectivity
    try:
        from .client import create_remote_client
        client = create_remote_client(
            endpoint, port, use_ssl, username, password, aws_region, aws_service
        )
        ok, _ = can_connect(client)
        if not ok:
            _endpoint_override = {}
            return f"Error: Could not connect to {endpoint}:{port}."
    except Exception as e:
        _endpoint_override = {}
        return f"Error connecting: {e}"

    if index_name:
        _default_index = index_name

    auth_mode = f"SigV4 ({aws_service}/{aws_region})" if aws_region else "basic" if username else "none"
    return f"Search UI connected to {endpoint} (auth: {auth_mode})"


def cleanup_ui() -> str:
    return "Search UI cleanup: the UI server runs as a daemon thread and stops when the script exits."
