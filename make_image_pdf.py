#!/usr/bin/env python3
"""Combine ordered page images into a PDF without running OCR."""

from __future__ import annotations

import argparse
from pathlib import Path

import img2pdf
from pypdf import PdfReader

from status_store import update_status


IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".tif", ".tiff"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create an image-only PDF from ordered page images."
    )
    parser.add_argument("input_dir", type=Path)
    parser.add_argument("output_pdf", type=Path)
    parser.add_argument("--dpi", type=int, default=300)
    parser.add_argument("--status-file", type=Path)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    input_dir = args.input_dir.resolve()
    images = sorted(
        path for path in input_dir.iterdir() if path.suffix.lower() in IMAGE_SUFFIXES
    )
    if not images:
        raise SystemExit(f"No page images found in: {input_dir}")

    output_pdf = args.output_pdf.resolve()
    output_pdf.parent.mkdir(parents=True, exist_ok=True)
    if args.status_file:
        update_status(
            args.status_file.expanduser(),
            state="running",
            phase="pdf",
            message="캡처 이미지를 OCR 없는 PDF로 묶고 있습니다.",
            phase_progress=0.15,
        )

    layout = img2pdf.get_fixed_dpi_layout_fun((args.dpi, args.dpi))
    output_pdf.write_bytes(
        img2pdf.convert([str(path) for path in images], layout_fun=layout)
    )
    page_count = len(PdfReader(str(output_pdf)).pages)
    if page_count != len(images):
        raise SystemExit(
            f"Image/PDF page mismatch: images={len(images)} pdf={page_count}"
        )

    if args.status_file:
        update_status(
            args.status_file.expanduser(),
            state="running",
            phase="pdf",
            message="OCR 없는 이미지 PDF를 완성했습니다.",
            phase_progress=1.0,
        )
    print(f"output={output_pdf}")
    print(f"pages={page_count}")


if __name__ == "__main__":
    main()
