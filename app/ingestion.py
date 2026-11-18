from .config import MAX_CRAWL_PAGES, WASALT_MAX_SITEMAP_RECORDS
from .db import upsert_document, upsert_documents, log_run
from .scraper import scrape_darglobal, scrape_wasalt


def _store(docs, report):
    saved = upsert_documents(docs) if docs else 0
    log_run(report["source"], report["status"], report["pages_seen"], saved, report["message"])
    return {"status": report["status"], "pages_seen": report["pages_seen"],
            "records_saved": saved, "message": report["message"]}


def crawl_darglobal(max_pages=MAX_CRAWL_PAGES):
    return _store(*scrape_darglobal(max_pages=max_pages))


def crawl_wasalt(max_sitemap_records=WASALT_MAX_SITEMAP_RECORDS, max_pages=MAX_CRAWL_PAGES):
    return _store(*scrape_wasalt(max_sitemap_records=max_sitemap_records, max_pages=max_pages))


def import_wasalt_json(payload):
    """
    Import an authorized Wasalt export/feed.
    Accepted shape: list[dict] or {"properties": list[dict]}.
    Each record must contain title, url and content/description.
    """
    records = payload if isinstance(payload, list) else payload.get("properties", [])
    saved = 0
    for item in records:
        title = str(item.get("title") or item.get("name") or "").strip()
        url = str(item.get("url") or "").strip()
        content = str(item.get("content") or item.get("description") or "").strip()
        if not title or not url.startswith("https://") or not content:
            continue
        upsert_document({
            "source": "Wasalt", "title": title[:300], "url": url,
            "content": content[:12000],
            "location": str(item.get("location") or ""),
            "property_type": str(item.get("property_type") or item.get("type") or ""),
            "price": str(item.get("price") or "")
        })
        saved += 1
    log_run("Wasalt", "completed", len(records), saved,
            "Imported authorized JSON data; no automated site crawling performed.")
    return {"pages_seen": len(records), "records_saved": saved}
