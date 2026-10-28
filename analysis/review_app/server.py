"""HTTP layer for the HW4 review app (standard library only, localhost only).

Routes:
    GET  /                                  the review UI
    GET  /ui/<file>                         UI assets
    GET  /api/conversations                 session-grouped conversations
    GET  /api/state                         annotations, suggestions, patterns, manifest, labels
    POST /api/annotations                   create an open code or "no failure"
    POST /api/annotations/<id>              edit a note (old note kept in history)
    POST /api/suggestions/<id>/accept       promote an AI suggestion to a human note
    POST /api/suggestions/<id>/reject       reject with a reason
    POST /api/patterns                      save the taxonomy
    POST /api/labels                        save a Pass/Fail judgment (Langfuse + local)

Run:
    uv run python -m analysis.review_app.server --refresh   # first run: snapshot Langfuse
    uv run python -m analysis.review_app.server             # then open http://127.0.0.1:8030
"""

from __future__ import annotations

import argparse
import json
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable

from analysis.review_app.app import ReviewApp
from analysis.review_app.store import ReviewStore

UI_DIR = Path(__file__).resolve().parent / "ui"
STATE_DIR = Path(__file__).resolve().parent.parent / "state"
MAX_BODY = 1_000_000
_TYPES = {".html": "text/html; charset=utf-8", ".css": "text/css", ".js": "text/javascript"}
_CSP = "default-src 'self'; style-src 'self'; script-src 'self'; img-src 'self' data:"

__all__ = ["ReviewApp", "make_server"]


def _post_routes(app: ReviewApp) -> list[tuple[re.Pattern[str], Callable[..., Any], int]]:
    return [
        (re.compile(r"^/api/annotations$"), lambda b: app.create_annotation(b), 201),
        (re.compile(r"^/api/annotations/([\w-]+)$"), lambda b, i: app.update_annotation(i, b), 200),
        (re.compile(r"^/api/suggestions/([\w-]+)/accept$"), lambda b, i: app.accept_suggestion(i, b), 200),
        (re.compile(r"^/api/suggestions/([\w-]+)/reject$"), lambda b, i: app.reject_suggestion(i, b), 200),
        (re.compile(r"^/api/patterns$"), lambda b: app.save_patterns(b), 200),
        (re.compile(r"^/api/labels$"), lambda b: app.save_label(b), 200),
    ]


def make_server(app: ReviewApp, host: str = "127.0.0.1", port: int = 8030) -> ThreadingHTTPServer:
    routes = _post_routes(app)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt: str, *args: Any) -> None:  # quiet console
            return

        def _send(self, status: int, payload: bytes, content_type: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("X-Content-Type-Options", "nosniff")
            if content_type.startswith("text/html"):
                self.send_header("Content-Security-Policy", _CSP)
            self.end_headers()
            self.wfile.write(payload)

        def _json(self, status: int, data: Any) -> None:
            self._send(status, json.dumps(data, ensure_ascii=False).encode(), "application/json")

        def _static(self, name: str) -> None:
            path = (UI_DIR / name).resolve()
            if UI_DIR not in path.parents or not path.is_file():
                self._json(404, {"error": "not found"})
                return
            self._send(200, path.read_bytes(), _TYPES.get(path.suffix, "application/octet-stream"))

        def do_GET(self) -> None:  # noqa: N802
            path = self.path.split("?", 1)[0]
            if path in ("/", "/index.html"):
                self._static("index.html")
            elif path.startswith("/ui/"):
                self._static(path[len("/ui/"):])
            elif path == "/api/conversations":
                self._json(200, app.conversations)
            elif path == "/api/state":
                self._json(200, app.state())
            else:
                self._json(404, {"error": f"unknown path {path}"})

        def do_POST(self) -> None:  # noqa: N802
            path = self.path.split("?", 1)[0]
            for pattern, handler, ok_status in routes:
                match = pattern.match(path)
                if match:
                    self._dispatch(handler, match.groups(), ok_status)
                    return
            self._json(404, {"error": f"cannot POST {path}"})

        def _dispatch(self, handler: Callable[..., Any], args: tuple, ok_status: int) -> None:
            length = int(self.headers.get("Content-Length") or 0)
            if length > MAX_BODY:
                self._json(413, {"error": "request body too large"})
                return
            try:
                body = json.loads(self.rfile.read(length) or b"null")
                self._json(ok_status, handler(body, *args))
            except json.JSONDecodeError:
                self._json(400, {"error": "expected a JSON body"})
            except ValueError as exc:
                self._json(400, {"error": str(exc)})
            except KeyError as exc:
                self._json(404, {"error": f"not found: {exc}"})
            except Exception:  # never leak a stack trace to the browser
                self._json(500, {"error": "internal error; see the server console"})
                raise

    return ThreadingHTTPServer((host, port), Handler)


def _sink() -> Any:
    from analysis.helpers import langfuse_io
    from analysis.review_app.label_sync import LangfuseLabelSink

    if not langfuse_io.is_configured():
        print("Langfuse not configured: labels are saved locally as unsynced.")
        return None
    return LangfuseLabelSink(langfuse_io._client())


def main() -> None:
    from dotenv import load_dotenv

    from analysis.review_app import snapshot
    from analysis.review_app.conversations import build_conversations

    parser = argparse.ArgumentParser(description="HW4 review app")
    parser.add_argument("--port", type=int, default=8030)
    parser.add_argument("--refresh", action="store_true", help="re-snapshot traces from Langfuse first")
    parser.add_argument("--state-dir", type=Path, default=STATE_DIR)
    args = parser.parse_args()
    load_dotenv()
    if args.refresh:
        print(f"Snapshotted {snapshot.refresh_snapshot()} traces from Langfuse.")
    conversations = build_conversations(snapshot.load_snapshot(), snapshot.load_scenarios())
    app = ReviewApp(conversations, ReviewStore(args.state_dir), _sink())
    server = make_server(app, port=args.port)
    print(f"{len(conversations)} conversations. Review app: http://127.0.0.1:{args.port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
