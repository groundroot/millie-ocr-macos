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
    parser.add_argument("--skip-first-page", action="store_true")
    return parser.parse_args()


def clean_page(page: str) -> str:
    page = page.replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.rstrip() for line in page.splitlines()]
    page_number = re.compile(r"^\s*(?:[-–—]?\s*\d+\s*[-–—]?|\d+\s*(?:쪽|페이지))\s*$")
    while lines and (not lines[0].strip() or page_number.fullmatch(lines[0])):
        lines.pop(0)
    while lines and (not lines[-1].strip() or page_number.fullmatch(lines[-1])):
        lines.pop()
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def join_pages(pages: list[str]) -> str:
    body = ""
    for page in (page for page in pages if page):
        if not body:
            body = page
            continue
        first_paragraph, separator, remainder = page.partition("\n\n")
        last_paragraph_start = body.rfind("\n\n") + 2
        last_paragraph = body[last_paragraph_start:]
        first_word = first_paragraph.split(maxsplit=1)[0] if first_paragraph else ""
        korean_continuation = (
            bool(re.search(r"[가-힣]$", last_paragraph))
            and len(first_word) == 1
            and first_word in "고며은는이가을를에도와과의로서만부터까지처럼보다"
        )
        if last_paragraph.endswith("-") and first_paragraph[:1].isalnum():
            body = body[:-1] + first_paragraph
        elif korean_continuation:
            body += first_paragraph
        elif last_paragraph and not re.search(r'[.!?。！？…]["”’\)\]]?$', last_paragraph):
            body += " " + first_paragraph
        else:
            body += "\n\n" + first_paragraph
        if separator:
            body += "\n\n" + remainder
    return body


def main() -> None:
    args = parse_args()
    text = args.input_txt.read_text(encoding="utf-8", errors="replace")
    pages = [clean_page(page) for page in text.split("\f")]
    while pages and not pages[-1]:
        pages.pop()
    if args.skip_first_page and pages:
        pages = pages[1:]

    body = join_pages(pages)
    document = f"# {args.title.strip()}\n"
    if body:
        document += f"\n{body}\n"

    args.output_md.parent.mkdir(parents=True, exist_ok=True)
    args.output_md.write_text(document, encoding="utf-8")
    print(f"output={args.output_md.resolve()}")
    print(f"pages={len(pages)}")


if __name__ == "__main__":
    main()
