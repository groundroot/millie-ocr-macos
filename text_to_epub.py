#!/usr/bin/env python3
"""Build a small, reflowable EPUB 3 book from page-separated OCR text."""

from __future__ import annotations

import argparse
import html
import re
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path


PAGES_PER_CHAPTER = 20


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("input_txt", type=Path)
    parser.add_argument("output_epub", type=Path)
    parser.add_argument("--title", required=True)
    return parser.parse_args()


def clean_page(page: str) -> str:
    page = page.replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.rstrip() for line in page.splitlines()]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def page_html(page: str, number: int) -> str:
    marker = f'<span class="pagebreak" epub:type="pagebreak" id="page-{number}" title="{number}" aria-label="{number}쪽"></span>'
    if not page:
        return marker + '<p class="empty">인식된 텍스트 없음</p>'
    paragraphs = []
    for paragraph in re.split(r"\n\s*\n", page):
        text = " ".join(line.strip() for line in paragraph.splitlines() if line.strip())
        if text:
            paragraphs.append(f"<p>{html.escape(text)}</p>")
    return marker + "\n" + "\n".join(paragraphs)


def xhtml_document(title: str, body: str) -> str:
    return f'''<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" lang="ko" xml:lang="ko">
<head><title>{html.escape(title)}</title><link rel="stylesheet" type="text/css" href="styles.css"/></head>
<body>{body}</body>
</html>
'''


def build_epub(input_txt: Path, output_epub: Path, title: str) -> int:
    text = input_txt.read_text(encoding="utf-8", errors="replace")
    pages = [clean_page(page) for page in text.split("\f")]
    while pages and not pages[-1]:
        pages.pop()
    if not pages:
        raise SystemExit("EPUB으로 만들 OCR 본문이 없습니다.")

    identifier = f"urn:uuid:{uuid.uuid4()}"
    modified = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    chapter_files: list[str] = []
    chapter_items: list[str] = []
    spine_items: list[str] = []
    toc_items: list[str] = []
    page_list: list[str] = []
    chapter_docs: dict[str, str] = {}

    for chapter_index, start in enumerate(range(0, len(pages), PAGES_PER_CHAPTER), start=1):
        end = min(start + PAGES_PER_CHAPTER, len(pages))
        filename = f"chapter-{chapter_index:03d}.xhtml"
        item_id = f"chapter-{chapter_index:03d}"
        chapter_files.append(filename)
        chapter_items.append(f'<item id="{item_id}" href="{filename}" media-type="application/xhtml+xml"/>')
        spine_items.append(f'<itemref idref="{item_id}"/>')
        toc_items.append(f'<li><a href="{filename}#page-{start + 1}">{start + 1}–{end}쪽</a></li>')
        body = [f"<h1>{start + 1}–{end}쪽</h1>"]
        for page_number in range(start + 1, end + 1):
            body.append(page_html(pages[page_number - 1], page_number))
            page_list.append(f'<li><a href="{filename}#page-{page_number}">{page_number}</a></li>')
        chapter_docs[filename] = xhtml_document(f"{title} · {start + 1}–{end}쪽", "\n".join(body))

    nav = xhtml_document(
        title,
        f'''<nav epub:type="toc" id="toc"><h1>{html.escape(title)}</h1><ol>{''.join(toc_items)}</ol></nav>
<nav epub:type="page-list" id="page-list"><h2>쪽 목록</h2><ol>{''.join(page_list)}</ol></nav>''',
    )
    package = f'''<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="book-id" xml:lang="ko">
<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
  <dc:identifier id="book-id">{identifier}</dc:identifier>
  <dc:title>{html.escape(title)}</dc:title>
  <dc:language>ko</dc:language>
  <meta property="dcterms:modified">{modified}</meta>
</metadata>
<manifest>
  <item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>
  <item id="styles" href="styles.css" media-type="text/css"/>
  {''.join(chapter_items)}
</manifest>
<spine>{''.join(spine_items)}</spine>
</package>
'''
    container = '''<?xml version="1.0" encoding="utf-8"?>
<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container" version="1.0">
  <rootfiles><rootfile full-path="EPUB/package.opf" media-type="application/oebps-package+xml"/></rootfiles>
</container>
'''
    styles = '''body { font-family: -apple-system, sans-serif; line-height: 1.75; margin: 5%; }
h1 { font-size: 1.35em; margin: 0 0 2em; }
p { margin: 0 0 1em; text-align: justify; }
.empty { color: #666; font-style: italic; }
.pagebreak { display: block; break-before: page; }
nav ol { line-height: 1.8; }
'''

    output_epub.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output_epub, "w") as archive:
        archive.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        archive.writestr("META-INF/container.xml", container, compress_type=zipfile.ZIP_DEFLATED)
        archive.writestr("EPUB/package.opf", package, compress_type=zipfile.ZIP_DEFLATED)
        archive.writestr("EPUB/nav.xhtml", nav, compress_type=zipfile.ZIP_DEFLATED)
        archive.writestr("EPUB/styles.css", styles, compress_type=zipfile.ZIP_DEFLATED)
        for filename in chapter_files:
            archive.writestr(f"EPUB/{filename}", chapter_docs[filename], compress_type=zipfile.ZIP_DEFLATED)

    with zipfile.ZipFile(output_epub) as archive:
        if archive.namelist()[0] != "mimetype" or archive.read("mimetype") != b"application/epub+zip":
            raise SystemExit("EPUB mimetype 검증에 실패했습니다.")
        if archive.testzip() is not None:
            raise SystemExit("EPUB ZIP 검증에 실패했습니다.")
    return len(pages)


def main() -> None:
    args = parse_args()
    pages = build_epub(args.input_txt.resolve(), args.output_epub.resolve(), args.title.strip())
    print(f"output={args.output_epub.resolve()}")
    print(f"pages={pages}")


if __name__ == "__main__":
    main()
