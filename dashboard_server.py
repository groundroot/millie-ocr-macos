#!/usr/bin/env python3
"""Small localhost-only server for the Millie OCR status dashboard."""

from __future__ import annotations

import argparse
import json
import mimetypes
import subprocess
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from status_store import load_status


class DashboardServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address: tuple[str, int], handler, status_file: Path, html: Path):
        super().__init__(address, handler)
        self.status_file = status_file
        self.html = html


class DashboardHandler(BaseHTTPRequestHandler):
    server: DashboardServer

    def log_message(self, format: str, *args) -> None:
        return

    def send_bytes(self, body: bytes, content_type: str, status: int = 200) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; style-src 'self' 'unsafe-inline'; "
            "script-src 'self' 'unsafe-inline'; img-src 'self' data:; "
            "connect-src 'self'; frame-ancestors 'none'",
        )
        self.end_headers()
        self.wfile.write(body)

    def send_json(self, payload: dict, status: int = 200) -> None:
        self.send_bytes(
            json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            "application/json; charset=utf-8",
            status,
        )

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path in {"/", "/dashboard.html"}:
            try:
                body = self.server.html.read_bytes()
            except OSError as error:
                self.send_json({"ok": False, "error": str(error)}, 500)
                return
            self.send_bytes(body, mimetypes.guess_type(self.server.html.name)[0] or "text/html")
            return

        if parsed.path == "/health":
            self.send_json({"ok": True})
            return

        if parsed.path == "/api/status":
            self.send_json({"ok": True, "status": load_status(self.server.status_file)})
            return

        if parsed.path == "/api/open":
            target = parse_qs(parsed.query).get("target", [""])[0]
            status_payload = load_status(self.server.status_file)
            key_map = {
                "folder": "run_dir",
                "pdf": "pdf_path",
                "markdown": "markdown_path",
                "epub": "epub_path",
                "log": "log_path",
            }
            key = key_map.get(target)
            raw_path = status_payload.get(key, "") if key else ""
            if not raw_path:
                self.send_json({"ok": False, "error": "아직 열 수 있는 파일이 없습니다."}, 404)
                return
            path = Path(raw_path).expanduser()
            if not path.exists():
                self.send_json({"ok": False, "error": "파일을 찾을 수 없습니다."}, 404)
                return
            command = ["/usr/bin/open", str(path)]
            if target in {"pdf", "markdown", "epub"}:
                command = ["/usr/bin/open", "-R", str(path)]
            subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self.send_json({"ok": True})
            return

        self.send_json({"ok": False, "error": "Not found"}, HTTPStatus.NOT_FOUND)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Serve the Millie OCR dashboard")
    parser.add_argument("--status-file", type=Path, required=True)
    parser.add_argument("--html", type=Path, required=True)
    parser.add_argument("--port", type=int, default=8765)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    server = DashboardServer(
        ("127.0.0.1", args.port),
        DashboardHandler,
        args.status_file.expanduser(),
        args.html.expanduser(),
    )
    server.serve_forever(poll_interval=0.5)


if __name__ == "__main__":
    main()
