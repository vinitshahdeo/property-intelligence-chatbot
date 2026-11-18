#!/usr/bin/env python3
"""Scrape publicly available DarGlobal and Wasalt data for the chatbot.

Examples:
    python scripts/scrape.py --source all
    python scripts/scrape.py --source wasalt --max-sitemap-records 20000 --max-pages 50
    python scripts/scrape.py --source wasalt --out data/wasalt.jsonl --no-db
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import MAX_CRAWL_PAGES, WASALT_MAX_SITEMAP_RECORDS  # noqa: E402
from app.db import init_db, log_run, upsert_documents  # noqa: E402
from app.scraper import scrape_darglobal, scrape_wasalt  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--source", choices=["darglobal", "wasalt", "all"], default="all")
    ap.add_argument("--max-pages", type=int, default=MAX_CRAWL_PAGES,
                    help="Max HTML pages fetched per site (default: %(default)s)")
    ap.add_argument("--max-sitemap-records", type=int, default=WASALT_MAX_SITEMAP_RECORDS,
                    help="Max Wasalt sitemap entries indexed (default: %(default)s)")
    ap.add_argument("--out", type=Path, help="Also write scraped documents to this JSONL file")
    ap.add_argument("--no-db", action="store_true", help="Do not write to the SQLite index")
    args = ap.parse_args()

    jobs = []
    if args.source in ("darglobal", "all"):
        jobs.append(lambda: scrape_darglobal(max_pages=args.max_pages))
    if args.source in ("wasalt", "all"):
        jobs.append(lambda: scrape_wasalt(max_sitemap_records=args.max_sitemap_records,
                                          max_pages=args.max_pages))
    if not args.no_db:
        init_db()

    all_docs = []
    for job in jobs:
        docs, report = job()
        all_docs.extend(docs)
        saved = 0
        if not args.no_db:
            saved = upsert_documents(docs) if docs else 0
            log_run(report["source"], report["status"], report["pages_seen"], saved, report["message"])
        print(f"[{report['source']}] status={report['status']} docs={len(docs)} "
              f"pages_fetched={report['pages_seen']} saved={saved}\n  {report['message']}")

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        with args.out.open("w", encoding="utf-8") as f:
            for d in all_docs:
                f.write(json.dumps(d, ensure_ascii=False) + "\n")
        print(f"Wrote {len(all_docs)} documents to {args.out}")


if __name__ == "__main__":
    main()
