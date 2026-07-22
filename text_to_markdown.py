#!/usr/bin/env python3
"""Turn pdftotext output into one continuous, readable Markdown document."""

import argparse
import re
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("input_txt", type=Path)
    parser.add_argument("output_md", type=Path)
    parser.add_argument("--title", required=True)
    return parser.parse_args()


def clean_page(page: str) -> str:
    page = page.replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.rstrip() for line in page.splitlines()]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def main() -> None:
    args = parse_args()
    text = args.input_txt.read_text(encoding="utf-8", errors="replace")
    pages = [clean_page(page) for page in text.split("\f")]
    while pages and not pages[-1]:
        pages.pop()

    body = "\n\n".join(page for page in pages if page)
    document = f"# {args.title.strip()}\n"
    if body:
        document += f"\n{body}\n"

    args.output_md.parent.mkdir(parents=True, exist_ok=True)
    args.output_md.write_text(document, encoding="utf-8")
    print(f"output={args.output_md.resolve()}")
    print(f"pages={len(pages)}")


if __name__ == "__main__":
    main()
