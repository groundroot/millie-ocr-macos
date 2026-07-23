#!/usr/bin/env python3
"""Small localhost-only server for the MyBook status dashboard."""

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
            message="사용자가 작업을 중지했습니다. 다음 실행에서 저장된 페이지 이후부터 이어갈 수 있습니다.",
            error="",
            worker_pid=0,
        )
    else:
        update_status(
            status_file,
            state="error",
            message="작업을 완전히 중지하지 못했습니다.",
            error="마이북 앱을 종료한 뒤 다시 시도해 주세요.",
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

    def is_remote_request(self) -> bool:
        host = self.headers.get("Host", "").split(":", 1)[0].strip("[]").lower()
        return bool(
            self.headers.get("Tailscale-User-Login")
            or self.headers.get("Tailscale-User-Name")
            or host not in {"127.0.0.1", "localhost", "::1"}
        )

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
            if self.is_remote_request():
                self.send_json(
                    {"ok": False, "error": "외부 조회 화면에서는 Mac의 파일을 열 수 없습니다."},
                    HTTPStatus.FORBIDDEN,
                )
                return
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
        if parsed.path not in {"/api/stop", "/api/resume", "/api/reset"}:
            self.send_json({"ok": False, "error": "Not found"}, HTTPStatus.NOT_FOUND)
            return

        if self.is_remote_request():
            self.send_json(
                {"ok": False, "error": "외부 링크는 조회 전용입니다."},
                HTTPStatus.FORBIDDEN,
            )
            return

        action = {
            "/api/stop": "stop",
            "/api/resume": "resume",
            "/api/reset": "reset",
        }[parsed.path]

        expected_origins = {
            f"http://127.0.0.1:{self.server.server_port}",
            f"http://localhost:{self.server.server_port}",
        }
        origin = self.headers.get("Origin", "")
        if origin and origin not in expected_origins:
            self.send_json({"ok": False, "error": "허용되지 않은 요청입니다."}, HTTPStatus.FORBIDDEN)
            return
        if (
            self.headers.get("X-MyBook") != action
            or not self.headers.get("Content-Type", "").startswith("application/json")
        ):
            message = {
                "stop": "중지 요청을 확인할 수 없습니다.",
                "resume": "재개 요청을 확인할 수 없습니다.",
                "reset": "리셋 요청을 확인할 수 없습니다.",
            }[action]
            self.send_json({"ok": False, "error": message}, HTTPStatus.BAD_REQUEST)
            return

        status_payload = load_status(self.server.status_file)
        if action == "resume":
            if status_payload.get("state") != "stopped":
                self.send_json(
                    {"ok": False, "error": "중지된 작업이 있을 때만 재개할 수 있습니다."},
                    HTTPStatus.CONFLICT,
                )
                return
            try:
                worker_pid = int(status_payload.get("worker_pid") or 0)
            except (TypeError, ValueError):
                worker_pid = 0
            if find_runner_pid(worker_pid):
                self.send_json(
                    {"ok": False, "error": "기존 작업 프로세스가 아직 실행 중입니다."},
                    HTTPStatus.CONFLICT,
                )
                return
            resume_file = self.server.status_file.with_name("resume.json")
            try:
                resume_payload = json.loads(resume_file.read_text(encoding="utf-8"))
            except (FileNotFoundError, json.JSONDecodeError, OSError):
                resume_payload = {}
            required_resume_fields = ("book_title", "output_mode", "result_root", "run_dir", "image_dir")
            if any(not resume_payload.get(key) for key in required_resume_fields):
                self.send_json(
                    {"ok": False, "error": "이어갈 작업 정보를 찾지 못했습니다."},
                    HTTPStatus.CONFLICT,
                )
                return
            app_candidates = [
                Path.home() / "Applications" / "마이북.app",
                Path.home() / "Applications" / "밀리 OCR.app",
            ]
            app_path = next((path for path in app_candidates if path.is_dir()), None)
            if app_path is None:
                self.send_json(
                    {"ok": False, "error": "마이북 앱을 찾지 못했습니다. 설치 명령을 다시 실행해 주세요."},
                    HTTPStatus.NOT_FOUND,
                )
                return
            resume_request = self.server.status_file.with_name("resume.request")
            try:
                resume_request.write_text("resume\n", encoding="utf-8")
                opened = subprocess.run(
                    ["/usr/bin/open", str(app_path)],
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                if opened.returncode != 0:
                    raise OSError((opened.stderr or opened.stdout).strip() or "마이북 앱을 열지 못했습니다.")
            except (OSError, subprocess.TimeoutExpired) as error:
                resume_request.unlink(missing_ok=True)
                self.send_json(
                    {"ok": False, "error": str(error)},
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                )
                return
            self.send_json({"ok": True, "message": "작업 재개를 요청했습니다."})
            return

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
            lock_dir = self.server.status_file.with_name("active-run.lock")
            try:
                stop_request.unlink(missing_ok=True)
                (lock_dir / "pid").unlink(missing_ok=True)
                lock_dir.rmdir()
            except FileNotFoundError:
                pass
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
    parser = argparse.ArgumentParser(description="Serve the MyBook dashboard")
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
