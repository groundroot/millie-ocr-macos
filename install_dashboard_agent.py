#!/usr/bin/env python3
"""Create the per-user launch agent for the local Millie OCR dashboard."""

from __future__ import annotations

import argparse
import os
import plistlib
from pathlib import Path


LABEL = "com.millieocr.dashboard"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--python", type=Path, required=True)
    parser.add_argument("--install-dir", type=Path, required=True)
    parser.add_argument("--home", type=Path, required=True)
    parser.add_argument("--port", type=int, default=8765)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    install_dir = args.install_dir.expanduser().resolve()
    home = args.home.expanduser().resolve()
    log_dir = home / "Library" / "Logs"
    status_file = home / ".cache" / "millie-ocr" / "status.json"
    payload = {
        "Label": LABEL,
        "ProgramArguments": [
            str(args.python.expanduser().resolve()),
            str(install_dir / "dashboard_server.py"),
            "--status-file",
            str(status_file),
            "--html",
            str(install_dir / "dashboard.html"),
            "--port",
            str(args.port),
        ],
        "RunAtLoad": True,
        "KeepAlive": True,
        "ProcessType": "Background",
        "StandardOutPath": str(log_dir / "MillieOCRDashboard.log"),
        "StandardErrorPath": str(log_dir / "MillieOCRDashboard.log"),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_name(f".{args.output.name}.{os.getpid()}.tmp")
    with temporary.open("wb") as output:
        plistlib.dump(payload, output, sort_keys=False)
    os.replace(temporary, args.output)
    print(f"agent={args.output}")


if __name__ == "__main__":
    main()
