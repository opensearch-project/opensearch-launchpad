#!/usr/bin/env python3
"""Standalone search UI server that runs as a detached subprocess.

Spawned by _start_search_ui_server() so the UI survives parent process exit.
Reads dynamic config (default_index, suggestions) from a shared state file
written by the MCP host process.

The UI server at http://127.0.0.1:8765 now stays up even after the MCP server
 process, Cursor, or any calling Python process exits. 
"""
import argparse
import signal
import threading

from http.server import ThreadingHTTPServer  # noqa: E402

from opensearch_launchpad.opensearch_ops_tools import (  # noqa: E402
    SEARCH_UI_HOST,
    SEARCH_UI_IDLE_TIMEOUT_SECONDS,
    SEARCH_UI_PORT,
    _SearchUIRequestHandler,
    _clear_ui_server_lock_if_owned_by_current_process,
    _configure_ui_server_runtime,
    _maybe_reload_ui_state,
    _record_ui_activity,
    _register_ui_server_lock,
    _should_ui_server_auto_stop,
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Detached Search Builder UI server"
    )
    parser.add_argument(
        "--instance-id",
        default="",
        help="Unique instance identifier written to the lock file.",
    )
    parser.add_argument(
        "--idle-timeout-seconds",
        type=int,
        default=SEARCH_UI_IDLE_TIMEOUT_SECONDS,
        help="Auto-stop timeout when no requests are received.",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    _maybe_reload_ui_state()
    _configure_ui_server_runtime(
        instance_id=args.instance_id,
        idle_timeout_seconds=args.idle_timeout_seconds,
    )

    server = ThreadingHTTPServer(
        (SEARCH_UI_HOST, SEARCH_UI_PORT), _SearchUIRequestHandler
    )
    server.timeout = 1.0

    stop_event = threading.Event()

    def _shutdown(signum: int, frame: object) -> None:
        stop_event.set()

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    _register_ui_server_lock()
    _record_ui_activity()

    try:
        while not stop_event.is_set():
            server.handle_request()
            if _should_ui_server_auto_stop():
                break
    finally:
        server.server_close()
        _clear_ui_server_lock_if_owned_by_current_process()


if __name__ == "__main__":
    main()
