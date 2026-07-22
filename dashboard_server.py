#!/usr/bin/env python3
"""Small localhost-only server for the Millie OCR status dashboard."""

from __future__ import annotations

import argparse
import json
import mimetypes
import os
import signal
import subprocess
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from status_store import default_status, load_status, update_status, write_status


def process_command(pid: int) -> str:
    if pid <= 1 or pid == os.getpid():
        return ""
    completed = subprocess.run(
        ["/bin/ps", "-p", str(pid), "-o", "command="],
        check=False,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip() if completed.returncode == 0 else ""


def runner_is_alive(pid: int) -> bool:
    command = process_command(pid)
    return command.startswith("/bin/zsh ") and "run_millie_ocr.sh" in command


def find_runner_pid(preferred_pid: int) -> int:
    if runner_is_alive(preferred_pid):
        return preferred_pid
    completed = subprocess.run(
        ["/usr/bin/pgrep", "-f", "run_millie_ocr.sh"],
        check=False,
        capture_output=True,
        text=True,
    )
    candidates = {
        int(line)
        for line in completed.stdout.splitlines()
        if line.isdigit() and int(line) != os.getpid()
    }
    verified = [pid for pid in candidates if runner_is_alive(pid)]
    return verified[0] if len(verified) == 1 else 0


def child_processes(pid: int) -> list[int]:
    completed = subprocess.run(
        ["/usr/bin/pgrep", "-P", str(pid)],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode not in {0, 1}:
        return []
    return [int(line) for line in completed.stdout.splitlines() if line.isdigit()]


def process_tree(pid: int) -> list[int]:
    descendants: list[int] = []
    for child in child_processes(pid):
        descendants.extend(process_tree(child))
        descendants.append(child)
    return descendants


def signal_process_tree(pid: int, requested_signal: signal.Signals) -> None:
    for target in [*process_tree(pid), pid]:
        try:
            os.kill(target, requested_signal)
        except (ProcessLookupError, PermissionError):
            continue


def terminate_runner(pid: int) -> bool:
    if not runner_is_alive(pid):
        return True
    signal_process_tree(pid, signal.SIGTERM)
    for _ in range(20):
        if not runner_is_alive(pid):
            return True
        time.sleep(0.05)
    signal_process_tree(pid, signal.SIGKILL)
    for _ in range(20):
        if not runner_is_alive(pid):
            return True
        time.sleep(0.05)
    return not runner_is_alive(pid)


def terminate_and_record(status_file: Path, pid: int) -> None:
    if terminate_runner(pid):
        update_status(
            status_file,
            state="stopped",
            message="사용자가 작업을 중지했습니다.",
            error="",
            worker_pid=0,
        )
    else:
        update_status(
            status_file,
            state="error",
            message="작업을 완전히 중지하지 못했습니다.",
            error="밀리 OCR 앱을 종료한 뒤 다시 시도해 주세요.",
        )


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

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path not in {"/api/stop", "/api/reset"}:
            self.send_json({"ok": False, "error": "Not found"}, HTTPStatus.NOT_FOUND)
            return

        action = "stop" if parsed.path == "/api/stop" else "reset"

        expected_origins = {
            f"http://127.0.0.1:{self.server.server_port}",
            f"http://localhost:{self.server.server_port}",
        }
        origin = self.headers.get("Origin", "")
        if origin and origin not in expected_origins:
            self.send_json({"ok": False, "error": "허용되지 않은 요청입니다."}, HTTPStatus.FORBIDDEN)
            return
        if (
            self.headers.get("X-Millie-OCR") != action
            or not self.headers.get("Content-Type", "").startswith("application/json")
        ):
            message = (
                "중지 요청을 확인할 수 없습니다."
                if action == "stop"
                else "리셋 요청을 확인할 수 없습니다."
            )
            self.send_json({"ok": False, "error": message}, HTTPStatus.BAD_REQUEST)
            return

        status_payload = load_status(self.server.status_file)
        if action == "reset":
            if status_payload.get("state") != "stopped":
                self.send_json(
                    {"ok": False, "error": "작업을 중지한 뒤에만 페이지를 리셋할 수 있습니다."},
                    HTTPStatus.CONFLICT,
                )
                return
            try:
                worker_pid = int(status_payload.get("worker_pid") or 0)
            except (TypeError, ValueError):
                worker_pid = 0
            if find_runner_pid(worker_pid):
                self.send_json(
                    {"ok": False, "error": "작업 프로세스가 아직 종료되지 않았습니다."},
                    HTTPStatus.CONFLICT,
                )
                return
            stop_request = self.server.status_file.with_name("stop.request")
            try:
                stop_request.unlink(missing_ok=True)
            except OSError as error:
                self.send_json(
                    {"ok": False, "error": str(error)},
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                )
                return
            reset_payload = default_status()
            write_status(self.server.status_file, reset_payload)
            self.send_json(
                {"ok": True, "message": "페이지를 초기화했습니다.", "status": reset_payload}
            )
            return

        if status_payload.get("state") == "stopping":
            self.send_json({"ok": True, "message": "이미 작업을 중지하고 있습니다."})
            return
        if status_payload.get("state") != "running":
            self.send_json({"ok": False, "error": "현재 실행 중인 작업이 없습니다."}, HTTPStatus.CONFLICT)
            return

        try:
            worker_pid = int(status_payload.get("worker_pid") or 0)
        except (TypeError, ValueError):
            worker_pid = 0
        worker_pid = find_runner_pid(worker_pid)
        if worker_pid == 0:
            self.send_json({"ok": False, "error": "실행 중인 작업 프로세스를 찾지 못했습니다."}, HTTPStatus.CONFLICT)
            return

        stop_request = self.server.status_file.with_name("stop.request")
        stop_request.parent.mkdir(parents=True, exist_ok=True)
        stop_request.write_text(str(worker_pid), encoding="utf-8")
        update_status(
            self.server.status_file,
            state="stopping",
            message="작업 중지를 요청했습니다. 현재 처리를 종료하고 있습니다.",
            error="",
        )
        self.send_json({"ok": True, "message": "작업 중지를 요청했습니다."})
        threading.Thread(
            target=terminate_and_record,
            args=(self.server.status_file, worker_pid),
            daemon=True,
        ).start()


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
