"""Localhost-only, read-only web server for the Optimus brain viewer.

Guarantees (enforced, not just intended):
  * Binds 127.0.0.1 ONLY — never reachable off the machine.
  * Opens the brain through Store(read_only=True): an OS-level mode=ro SQLite
    handle, every write method raises, log_event no-ops. No markdown is written.
  * Makes NO outbound network calls and serves NO third-party assets — the
    frontend is hand-rolled vanilla JS, fully offline.
  * Serves only three whitelisted static files from this package directory.

Run:  python -m ui.server            (defaults --root to the repo root)
      python -m ui.server --root . --port 8765
Then open http://127.0.0.1:8765/ in a browser.
"""

from __future__ import annotations

import argparse
import json
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from core.audit import audit
from core.store import Store

from . import model

_UI_DIR = Path(__file__).parent
_STATIC = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/index.html": ("index.html", "text/html; charset=utf-8"),
    "/app.js": ("app.js", "application/javascript; charset=utf-8"),
    "/style.css": ("style.css", "text/css; charset=utf-8"),
}


class BrainView:
    """Holds the read-only store + a cached audit report. Recomputable on demand."""

    def __init__(self, root: str):
        self.store = Store(root, read_only=True)
        assert self.store.read_only is True
        # one shared read-only connection across worker threads → serialize reads.
        self.lock = threading.Lock()
        self.report = audit(self.store)

    def refresh(self) -> None:
        with self.lock:
            self.report = audit(self.store)


def _make_handler(view: BrainView):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        # -- helpers -------------------------------------------------------- #
        def _send_json(self, payload, status: int = 200) -> None:
            body = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _send_static(self, fname: str, ctype: str) -> None:
            path = _UI_DIR / fname
            try:
                body = path.read_bytes()
            except OSError:
                self._send_json({"error": f"missing {fname}"}, 404)
                return
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        # -- routing -------------------------------------------------------- #
        def do_GET(self) -> None:  # noqa: N802 (stdlib naming)
            parsed = urlparse(self.path)
            route = parsed.path
            qs = parse_qs(parsed.query)

            if route in _STATIC:
                self._send_static(*_STATIC[route])
                return

            try:
                if route == "/api/graph":
                    with view.lock:
                        payload = model.build_graph(view.store, view.report)
                    self._send_json(payload)
                elif route == "/api/page":
                    pid = (qs.get("id") or [""])[0]
                    with view.lock:
                        detail = model.page_detail(view.store, view.report, pid)
                    if detail is None:
                        self._send_json({"error": f"no page {pid!r}"}, 404)
                    else:
                        self._send_json(detail)
                elif route == "/api/tombstones":
                    with view.lock:
                        toms = model.tombstones(view.store)
                    self._send_json({"tombstones": toms})
                elif route == "/api/search":
                    q = (qs.get("q") or [""])[0]
                    with view.lock:
                        results = model.search(view.store, q)
                    self._send_json({"results": results})
                elif route == "/api/refresh":
                    view.refresh()
                    with view.lock:
                        summary = model.build_graph(view.store, view.report)["summary"]
                    self._send_json(summary)
                else:
                    self._send_json({"error": "not found", "path": route}, 404)
            except Exception as exc:  # never leak a stack to the socket
                self._send_json({"error": str(exc)}, 500)

        # Block every write verb at the HTTP layer too — defense in depth.
        def _reject(self) -> None:
            self._send_json({"error": "read-only viewer; writes are not supported"}, 405)

        do_POST = do_PUT = do_DELETE = do_PATCH = _reject  # noqa: N815

        def log_message(self, fmt, *args):  # quieter console
            return

    return Handler


def serve(root: str = ".", port: int = 8765, open_browser: bool = True) -> None:
    view = BrainView(root)
    s = view.report
    print(f"Optimus brain viewer — READ-ONLY  (root: {Path(root).resolve()})")
    print(f"  pages: {len(view.store.all_pages_any_status())}  "
          f"claims: {len(s.results)}  tombstones: {len(view.store.list_tombstones())}")
    print(f"  audit: {s.verified} verified · {s.drifted} DRIFTED · "
          f"{s.unverifiable} unverifiable-here · {s.skipped} skipped")
    httpd = ThreadingHTTPServer(("127.0.0.1", port), _make_handler(view))
    url = f"http://127.0.0.1:{port}/"
    print(f"  serving {url}  (Ctrl+C to stop)")
    if open_browser:
        try:
            webbrowser.open(url)
        except Exception:
            pass
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped.")
    finally:
        httpd.server_close()
        view.store.close()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="ui.server", description="Read-only Optimus brain viewer")
    ap.add_argument("--root", default=str(Path(__file__).resolve().parent.parent),
                    help="Optimus repo root (default: repo root)")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--no-browser", action="store_true", help="don't auto-open a browser")
    args = ap.parse_args(argv)
    serve(args.root, args.port, open_browser=not args.no_browser)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
