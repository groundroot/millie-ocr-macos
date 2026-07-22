#!/usr/bin/env python3
"""Track live llama.cpp OCR work and publish it to the dashboard status file."""

from __future__ import annotations

import argparse
import json
import math
import os
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from status_store import load_status, update_status


@dataclass(frozen=True)
class ProgressSample:
    completed: int
    active: int
    progress: float
    rate: float
    absolute: bool


class SlotProgressTracker:
    """Convert llama.cpp slot activity into monotonic page-level progress."""

    def __init__(
        self,
        total: int,
        *,
        completed_offset: int = 0,
        initial_progress: float = 0.01,
    ) -> None:
        self.total = max(1, total)
        self.seen_tasks: set[str] = set()
        self.completed_offset = min(self.total, max(0, completed_offset))
        self.completed = self.completed_offset
        self.progress = min(0.99, max(0.01, initial_progress))
        self.started = time.monotonic()
        self.previous_active_ids: set[str] = set()
        self.tail_samples = 0
        self.absolute_count = False

    @staticmethod
    def _task_id(slot: dict[str, Any]) -> str | None:
        task_id = slot.get("id_task")
        return None if task_id is None else str(task_id)

    @staticmethod
    def _active_fraction(slot: dict[str, Any]) -> float:
        prompt_total = max(1, int(slot.get("n_prompt_tokens") or 0))
        prompt_done = max(0, int(slot.get("n_prompt_tokens_processed") or 0))
        prompt_fraction = min(1.0, prompt_done / prompt_total)

        next_token = slot.get("next_token") or []
        decoded = 0
        if next_token and isinstance(next_token[0], dict):
            decoded = max(0, int(next_token[0].get("n_decoded") or 0))
        generation_fraction = 1.0 - math.exp(-decoded / 900.0)
        return min(0.95, 0.1 * prompt_fraction + 0.85 * generation_fraction)

    def observe(self, slots: list[dict[str, Any]]) -> ProgressSample:
        active_slots = [slot for slot in slots if slot.get("is_processing")]
        active_ids = {
            task_id
            for slot in active_slots
            if (task_id := self._task_id(slot)) is not None
        }
        self.seen_tasks.update(active_ids)
        self.completed = max(
            self.completed,
            min(
                self.total,
                self.completed_offset + len(self.seen_tasks - active_ids),
            ),
        )

        capacity = len(slots)
        shrinking_tail = (
            capacity > 0
            and len(active_ids) < capacity
            and bool(self.previous_active_ids)
            and active_ids.issubset(self.previous_active_ids)
        )
        self.tail_samples = self.tail_samples + 1 if shrinking_tail else 0
        if self.tail_samples >= 5:
            self.completed = max(self.completed, self.total - len(active_ids))
            self.absolute_count = True
        self.previous_active_ids = active_ids

        active_units = sum(self._active_fraction(slot) for slot in active_slots)
        effective_units = min(self.total, self.completed + active_units)
        measured_progress = 0.01 + 0.98 * effective_units / self.total
        self.progress = min(0.99, max(self.progress, measured_progress))

        elapsed = max(0.001, time.monotonic() - self.started)
        newly_completed = max(0, self.completed - self.completed_offset)
        rate = newly_completed / elapsed if newly_completed else 0.0
        return ProgressSample(
            completed=self.completed,
            active=len(active_slots),
            progress=self.progress,
            rate=rate,
            absolute=self.absolute_count,
        )


class OCRProgressMonitor:
    def __init__(
        self,
        status_file: Path,
        total: int,
        *,
        interval: float = 1.0,
        completed_offset: int = 0,
        attached: bool = False,
    ) -> None:
        self.status_file = status_file.expanduser()
        self.total = max(1, total)
        self.interval = max(0.25, interval)
        self.completed_offset = completed_offset
        self.attached = attached
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self, port: int) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(
            target=self._run,
            args=(port,),
            name="millie-ocr-progress",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)

    def _fetch_slots(self, port: int) -> list[dict[str, Any]]:
        request = urllib.request.Request(
            f"http://127.0.0.1:{port}/slots",
            headers={"Accept": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=0.75) as response:
            payload = json.load(response)
        return payload if isinstance(payload, list) else []

    def _run(self, port: int) -> None:
        initial_status = load_status(self.status_file)
        tracker = SlotProgressTracker(
            self.total,
            completed_offset=self.completed_offset,
            initial_progress=float(initial_status.get("phase_progress") or 0.01),
        )
        while not self._stop.wait(self.interval):
            status = load_status(self.status_file)
            if status.get("state") != "running" or status.get("phase") != "ocr":
                return
            try:
                sample = tracker.observe(self._fetch_slots(port))
            except (OSError, ValueError, json.JSONDecodeError, urllib.error.URLError):
                continue
            qualifier = "실시간 감시 연결 후 " if self.attached and not sample.absolute else ""
            message = f"한글 OCR {qualifier}{sample.completed}/{self.total}쪽 완료"
            if sample.active:
                message += f" · {sample.active}쪽 분석 중"
            update_status(
                self.status_file,
                add_history=False,
                state="running",
                phase="ocr",
                message=message,
                phase_progress=sample.progress,
                phase_current=sample.completed,
                phase_total=self.total,
                phase_active=sample.active,
                rate=0.0 if self.attached else sample.rate,
            )


def process_exists(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except (OSError, ValueError):
        return False
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description="Publish live llama.cpp OCR progress")
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--total", type=int, required=True)
    parser.add_argument("--status-file", type=Path, required=True)
    parser.add_argument("--watch-pid", type=int)
    parser.add_argument("--interval", type=float, default=1.0)
    parser.add_argument("--completed-offset", type=int, default=0)
    args = parser.parse_args()

    monitor = OCRProgressMonitor(
        args.status_file,
        args.total,
        interval=args.interval,
        completed_offset=args.completed_offset,
        attached=True,
    )
    monitor.start(args.port)
    try:
        while args.watch_pid is None or process_exists(args.watch_pid):
            status = load_status(args.status_file.expanduser())
            if status.get("state") != "running" or status.get("phase") != "ocr":
                break
            time.sleep(max(0.25, args.interval))
    except KeyboardInterrupt:
        pass
    finally:
        monitor.stop()


if __name__ == "__main__":
    main()
