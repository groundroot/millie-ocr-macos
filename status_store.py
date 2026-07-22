#!/usr/bin/env python3
"""Atomic status storage shared by the Millie OCR runner and dashboard."""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PHASES = [
    "preparing",
    "capture",
    "ocr",
    "pdf",
    "markdown",
    "epub",
    "validation",
    "complete",
]


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def default_status() -> dict[str, Any]:
    return {
        "schema_version": 2,
        "state": "idle",
        "phase": "preparing",
        "message": "새 OCR 작업을 기다리고 있습니다.",
        "book_title": "",
        "current": 0,
        "total": 0,
        "rate": 0.0,
        "phase_progress": None,
        "started_at": None,
        "updated_at": now_iso(),
        "run_dir": "",
        "pdf_path": "",
        "markdown_path": "",
        "epub_path": "",
        "log_path": "",
        "error": "",
        "history": [],
    }


def load_status(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        payload = default_status()
    base = default_status()
    base.update(payload)
    if not isinstance(base.get("history"), list):
        base["history"] = []
    return base


def write_status(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    os.replace(temporary, path)


def update_status(
    path: Path,
    *,
    reset: bool = False,
    add_history: bool = True,
    **changes: Any,
) -> dict[str, Any]:
    payload = default_status() if reset else load_status(path)
    previous_phase = payload.get("phase")
    previous_message = payload.get("message")
    previous_state = payload.get("state")

    for key, value in changes.items():
        if value is not None:
            payload[key] = value

    requested_phase = changes.get("phase")
    if requested_phase is not None and requested_phase != previous_phase and changes.get("phase_progress") is None:
        payload["phase_progress"] = 0.0

    if reset and not payload.get("started_at"):
        payload["started_at"] = now_iso()
    payload["updated_at"] = now_iso()

    changed = (
        payload.get("phase") != previous_phase
        or payload.get("message") != previous_message
        or payload.get("state") != previous_state
        or reset
    )
    if add_history and changed and payload.get("message"):
        history = payload.setdefault("history", [])
        history.append(
            {
                "at": payload["updated_at"],
                "phase": payload.get("phase", "preparing"),
                "state": payload.get("state", "running"),
                "message": payload["message"],
            }
        )
        payload["history"] = history[-30:]

    write_status(path, payload)
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Update the Millie OCR status file")
    parser.add_argument("--file", type=Path, required=True)
    parser.add_argument("--reset", action="store_true")
    parser.add_argument("--state")
    parser.add_argument("--phase", choices=PHASES)
    parser.add_argument("--message")
    parser.add_argument("--book-title")
    parser.add_argument("--current", type=int)
    parser.add_argument("--total", type=int)
    parser.add_argument("--rate", type=float)
    parser.add_argument("--phase-progress", type=float)
    parser.add_argument("--started-at")
    parser.add_argument("--run-dir")
    parser.add_argument("--pdf-path")
    parser.add_argument("--markdown-path")
    parser.add_argument("--epub-path")
    parser.add_argument("--log-path")
    parser.add_argument("--error")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    changes = {
        "state": args.state,
        "phase": args.phase,
        "message": args.message,
        "book_title": args.book_title,
        "current": args.current,
        "total": args.total,
        "rate": args.rate,
        "phase_progress": args.phase_progress,
        "started_at": args.started_at,
        "run_dir": args.run_dir,
        "pdf_path": args.pdf_path,
        "markdown_path": args.markdown_path,
        "epub_path": args.epub_path,
        "log_path": args.log_path,
        "error": args.error,
    }
    update_status(args.file.expanduser(), reset=args.reset, **changes)


if __name__ == "__main__":
    main()
