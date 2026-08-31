#!/usr/bin/env python3
"""Download HLPC minutes PDFs listed in data/index.json and extract their text.

Both the PDFs and the extracted text are cached on disk, so re-running only
picks up documents that are new since the last run.
"""

import argparse
import json
import sys
import time
import urllib.request
from pathlib import Path

import pypdf

ROOT = Path(__file__).resolve().parent.parent
INDEX = ROOT / "data" / "index.json"
PDF_DIR = ROOT / "data" / "pdf"
TXT_DIR = ROOT / "data" / "text"

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

# robots.txt on kingston-ny.gov asks for 15 seconds between requests. Downloads
# are cached, so after the first run a month's update fetches one document.
CRAWL_DELAY = 15


def slug(record):
    """Stable per-document id: the meeting date plus the source filename stem."""
    stem = record["filename"].rsplit(".", 1)[0]
    stem = "".join(c if c.isalnum() else "-" for c in stem).strip("-").lower()
    while "--" in stem:
        stem = stem.replace("--", "-")
    return f"{record['date']}_{stem}"


def download(url, dest):
    request = urllib.request.Request(url, headers={"User-Agent": UA})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=90) as resp:
                dest.write_bytes(resp.read())
            return True
        except Exception as exc:
            if attempt == 2:
                print(f"  FAILED {url}: {exc}", file=sys.stderr)
                return False
            time.sleep(2 * (attempt + 1))


def extract(pdf_path):
    """Return (text, page_count). A handful of "PDFs" are really WebVTT
    transcripts of the meeting recording, served under a .pdf name."""
    head = pdf_path.open("rb").read(16)
    if head.startswith(b"WEBVT"):
        return vtt_to_text(pdf_path.read_text(errors="replace")), 0
    reader = pypdf.PdfReader(str(pdf_path))
    pages = [page.extract_text() or "" for page in reader.pages]
    return "\n".join(pages), len(pages)


def vtt_to_text(raw):
    """Flatten WebVTT captions into plain speech, dropping cues and timestamps."""
    lines = []
    for line in raw.splitlines():
        line = line.strip()
        if not line or line == "WEBVTT" or line.isdigit() or "-->" in line:
            continue
        if lines and lines[-1] == line:
            continue
        lines.append(line)
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default="2020", help="earliest meeting year to fetch")
    ap.add_argument("--kind", default="minutes", choices=["minutes", "agenda", "audio"])
    ap.add_argument("--force", action="store_true", help="re-download cached files")
    args = ap.parse_args()

    records = json.loads(INDEX.read_text())
    wanted = [
        r
        for r in records
        if r["kind"] == args.kind and r["date"] and r["date"][:4] >= args.since
    ]
    wanted.sort(key=lambda r: r["date"])

    PDF_DIR.mkdir(parents=True, exist_ok=True)
    TXT_DIR.mkdir(parents=True, exist_ok=True)

    fetched = cached = failed = 0
    empty = []

    for record in wanted:
        name = slug(record)
        pdf_path = PDF_DIR / f"{name}.pdf"
        txt_path = TXT_DIR / f"{name}.txt"

        if not pdf_path.exists() or args.force:
            if not download(record["url"], pdf_path):
                failed += 1
                continue
            fetched += 1
            time.sleep(CRAWL_DELAY)
        else:
            cached += 1

        if not txt_path.exists() or args.force:
            try:
                text, pages = extract(pdf_path)
            except Exception as exc:
                print(f"  UNREADABLE {pdf_path.name}: {exc}", file=sys.stderr)
                failed += 1
                continue
            txt_path.write_text(text)
            # A near-empty text layer means the PDF is a scan needing OCR.
            if len(text.strip()) < 200 * max(pages, 1) / 4:
                empty.append((name, pages, len(text.strip())))

    print(f"{len(wanted)} {args.kind} documents since {args.since}", file=sys.stderr)
    print(f"  downloaded {fetched}, cached {cached}, failed {failed}", file=sys.stderr)
    if empty:
        print(f"  thin text layer (likely scanned): {len(empty)}", file=sys.stderr)
        for name, pages, chars in empty:
            print(f"    {name} ({pages}p, {chars} chars)", file=sys.stderr)


if __name__ == "__main__":
    main()
