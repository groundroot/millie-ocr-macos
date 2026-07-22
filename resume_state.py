#!/usr/bin/env python3
"""Persistent resumable-capture metadata for Millie OCR."""

from __future__ import annotations

import argparse
import json
import os
import re
import struct
import zlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCHEMA_VERSION = 1
PAGE_FILE = re.compile(r"page_(\d{4,})\.png$")
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
TARGET_SIZE = (1748, 2480)


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def load_resume(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}
    return payload if payload.get("schema_version") == SCHEMA_VERSION else {}


def write_resume(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload["schema_version"] = SCHEMA_VERSION
    payload["updated_at"] = now_iso()
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    os.replace(temporary, path)


def initialize_resume(
    path: Path,
    *,
    book_title: str,
    output_mode: str,
    result_root: Path,
    run_dir: Path,
    image_dir: Path,
    total_pages: int = 0,
) -> dict[str, Any]:
    payload = {
        "schema_version": SCHEMA_VERSION,
        "book_title": book_title,
        "output_mode": output_mode,
        "result_root": str(result_root.resolve()),
        "run_dir": str(run_dir.resolve()),
        "image_dir": str(image_dir.resolve()),
        "total_pages": max(0, int(total_pages)),
        "created_at": now_iso(),
    }
    write_resume(path, payload)
    return payload


def update_resume(path: Path, **changes: Any) -> dict[str, Any]:
    payload = load_resume(path)
    if not payload:
        return {}
    payload.update({key: value for key, value in changes.items() if value is not None})
    write_resume(path, payload)
    return payload


def clear_resume(path: Path) -> None:
    path.unlink(missing_ok=True)


def png_size(path: Path) -> tuple[int, int]:
    with path.open("rb") as image_file:
        if image_file.read(8) != PNG_SIGNATURE:
            raise ValueError(f"유효한 PNG가 아닙니다: {path.name}")
        dimensions: tuple[int, int] | None = None
        while True:
            length_bytes = image_file.read(4)
            if len(length_bytes) != 4:
                raise ValueError(f"완전히 저장되지 않은 PNG입니다: {path.name}")
            length = struct.unpack(">I", length_bytes)[0]
            chunk_type = image_file.read(4)
            chunk_data = image_file.read(length)
            crc_bytes = image_file.read(4)
            if len(chunk_type) != 4 or len(chunk_data) != length or len(crc_bytes) != 4:
                raise ValueError(f"완전히 저장되지 않은 PNG입니다: {path.name}")
            expected_crc = struct.unpack(">I", crc_bytes)[0]
            actual_crc = zlib.crc32(chunk_type)
            actual_crc = zlib.crc32(chunk_data, actual_crc) & 0xFFFFFFFF
            if actual_crc != expected_crc:
                raise ValueError(f"손상된 PNG입니다: {path.name}")
            if chunk_type == b"IHDR":
                if length < 8:
                    raise ValueError(f"PNG 크기를 읽지 못했습니다: {path.name}")
                dimensions = struct.unpack(">II", chunk_data[:8])
            if chunk_type == b"IEND":
                if dimensions is None:
                    raise ValueError(f"PNG 크기를 읽지 못했습니다: {path.name}")
                return dimensions


def scan_contiguous_pages(image_dir: Path) -> int:
    files = sorted(image_dir.glob("page_*.png"))
    if not files:
        return 0
    numbered: list[tuple[int, Path]] = []
    for path in files:
        match = PAGE_FILE.fullmatch(path.name)
        if match is None:
            raise ValueError(f"페이지 파일 이름을 확인할 수 없습니다: {path.name}")
        numbered.append((int(match.group(1)), path))
    numbers = [number for number, _ in numbered]
    expected = list(range(1, numbers[-1] + 1))
    if numbers != expected:
        raise ValueError("기존 페이지 이미지에 누락되거나 중복된 번호가 있습니다.")
    for _, path in numbered:
        if png_size(path) != TARGET_SIZE:
            raise ValueError(f"페이지 이미지 크기가 올바르지 않습니다: {path.name}")
    return numbers[-1]


def probe_resume(path: Path, book_title: str) -> tuple[dict[str, Any], int]:
    payload = load_resume(path)
    if not payload or payload.get("book_title") != book_title:
        return {}, 0
    run_dir = Path(str(payload.get("run_dir", ""))).expanduser()
    image_dir = Path(str(payload.get("image_dir", ""))).expanduser()
    if not run_dir.is_dir() or not image_dir.is_dir():
        return {}, 0
    last_page = scan_contiguous_pages(image_dir)
    if last_page < 1:
        return {}, 0
    total_pages = max(0, int(payload.get("total_pages") or 0))
    if total_pages and last_page > total_pages:
        raise ValueError(
            f"저장된 이미지 수({last_page})가 기존 전체 쪽수({total_pages})보다 많습니다."
        )
    return payload, last_page


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Manage resumable Millie OCR capture state")
    subparsers = parser.add_subparsers(dest="command", required=True)

    initialize = subparsers.add_parser("init")
    initialize.add_argument("--file", type=Path, required=True)
    initialize.add_argument("--book-title", required=True)
    initialize.add_argument("--output-mode", required=True)
    initialize.add_argument("--result-root", type=Path, required=True)
    initialize.add_argument("--run-dir", type=Path, required=True)
    initialize.add_argument("--image-dir", type=Path, required=True)
    initialize.add_argument("--total-pages", type=int, default=0)

    probe = subparsers.add_parser("probe")
    probe.add_argument("--file", type=Path, required=True)
    probe.add_argument("--book-title", required=True)

    clear = subparsers.add_parser("clear")
    clear.add_argument("--file", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    path = args.file.expanduser()
    if args.command == "init":
        initialize_resume(
            path,
            book_title=args.book_title,
            output_mode=args.output_mode,
            result_root=args.result_root.expanduser(),
            run_dir=args.run_dir.expanduser(),
            image_dir=args.image_dir.expanduser(),
            total_pages=args.total_pages,
        )
        return
    if args.command == "clear":
        clear_resume(path)
        return

    try:
        payload, last_page = probe_resume(path, args.book_title)
    except (OSError, ValueError) as error:
        print("0")
        print(str(error))
        return
    if not payload:
        print("0")
        return
    print("1")
    print(payload["run_dir"])
    print(payload["image_dir"])
    print(last_page)
    print(int(payload.get("total_pages") or 0))
    print(payload.get("output_mode", "all"))
    print(payload.get("created_at", ""))


if __name__ == "__main__":
    main()
