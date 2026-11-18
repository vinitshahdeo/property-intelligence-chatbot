"""Respectful scrapers for publicly available DarGlobal and Wasalt data.

Rules enforced here:
- robots.txt is honoured (fail closed if it cannot be read).
- Only URLs published in the sites' public sitemaps are visited.
- Requests are rate-limited and use a descriptive user agent.
- Bot-protection challenges (Cloudflare, Imperva/Incapsula, CAPTCHA) are
  detected and treated as "access denied"; they are never bypassed.
"""
import gzip
import json
import re
import time
import urllib.robotparser
from urllib.parse import urlparse
from xml.etree import ElementTree

import requests
from bs4 import BeautifulSoup

from .config import REQUEST_TIMEOUT, CRAWL_DELAY

USER_AGENT = "PropertyIntelligenceResearchBot/1.0 (respectful public-page indexing)"

DARGLOBAL_ROOT = "https://www.darglobal.co.uk/"
WASALT_ROOT = "https://wasalt.sa/"

CHALLENGE_MARKERS = (
    "_incapsula_resource", "just a moment...", "cf-chl", "challenge-platform",
    "cf_chl_opt", "attention required! | cloudflare",
)
MAX_CONSECUTIVE_BLOCKS = 3


class AccessBlocked(Exception):
    """The site is refusing automated access; stop instead of working around it."""


def is_challenge(resp):
    if resp.status_code in (401, 403, 429, 503):
        return True
    head = resp.text[:4000].lower() if resp.text else ""
    return any(m in head for m in CHALLENGE_MARKERS)


class PoliteClient:
    def __init__(self, root, delay=CRAWL_DELAY):
        self.root = root
        self.host = urlparse(root).netloc
        self.delay = delay
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT, "Accept-Language": "en"})
        self.robots = None
        self.robots_sitemaps = []
        self._last = 0.0
        self.consecutive_blocks = 0

    def _wait(self):
        pause = self.delay - (time.monotonic() - self._last)
        if pause > 0:
            time.sleep(pause)
        self._last = time.monotonic()

    def load_robots(self):
        """Fetch robots.txt. Raises AccessBlocked if it cannot be read reliably."""
        url = f"https://{self.host}/robots.txt"
        self._wait()
        try:
            resp = self.session.get(url, timeout=REQUEST_TIMEOUT)
        except requests.RequestException as exc:
            raise AccessBlocked(f"robots.txt unreachable: {exc}") from exc
        body = resp.text or ""
        if resp.status_code != 200 or is_challenge(resp) or "<html" in body[:500].lower():
            raise AccessBlocked(
                f"robots.txt at {url} is protected by bot mitigation (HTTP {resp.status_code}); "
                "automated access is not permitted.")
        rp = urllib.robotparser.RobotFileParser()
        rp.parse(body.splitlines())
        self.robots = rp
        self.robots_sitemaps = rp.site_maps() or []
        crawl_delay = rp.crawl_delay(USER_AGENT)
        if crawl_delay:
            self.delay = max(self.delay, float(crawl_delay))

    def allowed(self, url):
        return self.robots is not None and self.robots.can_fetch(USER_AGENT, url)

    def get(self, url, check_robots=True):
        """GET a URL politely. Returns Response or None. Raises AccessBlocked on repeated challenges."""
        if check_robots and not self.allowed(url):
            return None
        self._wait()
        try:
            resp = self.session.get(url, timeout=REQUEST_TIMEOUT)
        except requests.RequestException:
            return None
        if is_challenge(resp):
            self.consecutive_blocks += 1
            if self.consecutive_blocks >= MAX_CONSECUTIVE_BLOCKS:
                raise AccessBlocked(
                    f"{urlparse(url).netloc} returned bot-protection challenges "
                    f"(last HTTP {resp.status_code}); stopping page fetches.")
            return None
        self.consecutive_blocks = 0
        return resp if resp.status_code == 200 else None


def _decode_xml(content):
    if content[:2] == b"\x1f\x8b":
        content = gzip.decompress(content)
    return ElementTree.fromstring(content)


def iter_sitemap(client, sitemap_url, host_suffix, limit=None, _depth=0):
    """Yield (loc, lastmod) from a sitemap or sitemap index (gzip supported)."""
    # Sitemaps listed in robots.txt may live on a CDN host; robots of the site still governs pages.
    resp = client.get(sitemap_url, check_robots=False)
    if resp is None:
        return
    try:
        xml = _decode_xml(resp.content)
    except (ElementTree.ParseError, OSError):
        return
    count = 0
    is_index = xml.tag.endswith("sitemapindex")
    for node in xml:
        loc = lastmod = None
        for child in node:
            if child.tag.endswith("loc") and child.text:
                loc = child.text.strip()
            elif child.tag.endswith("lastmod") and child.text:
                lastmod = child.text.strip()
        if not loc:
            continue
        if is_index and _depth < 2:
            for item in iter_sitemap(client, loc, host_suffix,
                                     None if limit is None else limit - count, _depth + 1):
                yield item
                count += 1
                if limit is not None and count >= limit:
                    return
        elif urlparse(loc).netloc.endswith(host_suffix):
            yield loc, lastmod
            count += 1
            if limit is not None and count >= limit:
                return


def _walk_jsonld(data):
    if isinstance(data, list):
        for d in data:
            yield from _walk_jsonld(d)
    elif isinstance(data, dict):
        yield data
        for key in ("@graph", "itemOffered", "mainEntity"):
            if key in data:
                yield from _walk_jsonld(data[key])


def _address_text(addr):
    if isinstance(addr, str):
        return addr
    if isinstance(addr, dict):
        parts = [addr.get(k) for k in ("streetAddress", "addressLocality", "addressRegion", "addressCountry")]
        return ", ".join(str(p if not isinstance(p, dict) else p.get("name", "")) for p in parts if p)
    return ""


def extract_document(url, html, source):
    """Turn an HTML page into a chatbot document using JSON-LD, meta tags and visible text."""
    soup = BeautifulSoup(html, "html.parser")
    location = property_type = price = ""
    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(tag.string or "")
        except (json.JSONDecodeError, TypeError):
            continue
        for obj in _walk_jsonld(data):
            location = location or _address_text(obj.get("address", ""))
            types = obj.get("@type", "")
            if not property_type and isinstance(types, str) and types not in ("WebPage", "Organization", "BreadcrumbList", "WebSite"):
                property_type = types
            offers = obj.get("offers")
            if not price and isinstance(offers, (dict, list)):
                offer = offers[0] if isinstance(offers, list) and offers else offers
                if isinstance(offer, dict) and offer.get("price"):
                    price = f"{offer.get('price')} {offer.get('priceCurrency', '')}".strip()

    def meta(name):
        tag = soup.find("meta", attrs={"property": name}) or soup.find("meta", attrs={"name": name})
        return tag.get("content", "").strip() if tag else ""

    title = meta("og:title") or (soup.title.get_text(" ", strip=True) if soup.title else url)
    description = meta("og:description") or meta("description")
    for node in soup(["script", "style", "noscript", "svg", "nav", "footer", "header", "form"]):
        node.decompose()
    main = soup.find("main") or soup.find("article") or soup.body or soup
    text = re.sub(r"\s+", " ", main.get_text(" ", strip=True)).strip()
    content = f"{description}\n\n{text}".strip() if description and description not in text else text
    if len(content) < 120:
        return None
    return {
        "source": source, "title": title[:300], "url": url, "content": content[:12000],
        "location": location[:200], "property_type": property_type[:100], "price": price[:100],
    }


# ---------------------------------------------------------------- DarGlobal

def scrape_darglobal(max_pages=35):
    """Crawl public DarGlobal pages listed in its sitemap. Returns (docs, report)."""
    client = PoliteClient(DARGLOBAL_ROOT)
    report = {"source": "DarGlobal", "pages_seen": 0, "status": "completed", "message": ""}
    docs = []
    try:
        client.load_robots()
        sitemaps = client.robots_sitemaps or [DARGLOBAL_ROOT + "sitemap.xml", DARGLOBAL_ROOT + "sitemap_index.xml"]
        urls = []
        for sm in sitemaps:
            urls.extend(u for u, _ in iter_sitemap(client, sm, "darglobal.co.uk", limit=max_pages * 3))
        urls = list(dict.fromkeys(urls))
        if not urls:
            report.update(status="unavailable", message="No sitemap URLs found.")
            return docs, report
        for url in urls:
            if report["pages_seen"] >= max_pages:
                break
            resp = client.get(url)
            if resp is None:
                continue
            report["pages_seen"] += 1
            if "text/html" in resp.headers.get("content-type", ""):
                doc = extract_document(url, resp.text, "DarGlobal")
                if doc:
                    docs.append(doc)
        report["message"] = f"Sitemap crawl of {len(urls)} candidate URLs."
    except AccessBlocked as exc:
        report.update(status="blocked", message=str(exc))
    return docs, report


# ---------------------------------------------------------------- Wasalt

WASALT_SITEMAPS = {
    "categories": "https://cdn.wasalt.sa/sitemap/category_sitemap_en_sa.xml.gz",
    "listings": "https://cdn.wasalt.sa/sitemap/product_sitemap_en_sa.xml.gz",
    "daily_rental_categories": "https://cdn.wasalt.sa/sitemap/rental_srp_sitemap_en_sa.xml.gz",
    "daily_rentals": "https://cdn.wasalt.sa/sitemap/rental_pdp_sitemap_en_sa.xml.gz",
}

_CATEGORY_RE = re.compile(
    r"/en/(?P<what>[a-z0-9-]+?)-for-(?P<purpose>sale|rent|daily-rental)-in-(?P<where>[a-z0-9-]+)$")
_LISTING_RE = re.compile(r"/en/property/(?P<purpose>sale|rent)/(?P<slug>.+)-(?P<id>\d+)$")
_DAILY_RE = re.compile(r"/en/dailyrental/(?P<slug>.+)-(?P<id>\d+)$")


def _humanize(slug):
    return re.sub(r"\s+", " ", slug.replace("-", " ")).strip()


def _listing_title(slug):
    # Slugs strip decimal points (119.17 sqm -> 11917-sqm), so drop the unreliable area.
    return _humanize(re.sub(r"(^|-)\d+-sqm(?=-|$)", r"\1", slug)).capitalize()


def _guess_type(text):
    t = text.lower()
    for kind in ("apartment", "villa", "land", "building", "floor", "duplex", "townhouse", "studio",
                 "office", "shop", "showroom", "warehouse", "farm", "chalet", "rest house", "istiraha",
                 "compound", "room", "camp"):
        if kind in t:
            return kind.title()
    return ""


def wasalt_doc_from_sitemap(url, lastmod):
    """Build a document from the public sitemap entry alone (no page request needed)."""
    path = urlparse(url).path.rstrip("/")
    updated = f" Sitemap last modified {lastmod}." if lastmod else ""
    if m := _LISTING_RE.search(path):
        title = _listing_title(m["slug"])
        purpose = "for sale" if m["purpose"] == "sale" else "for rent"
        return {
            "source": "Wasalt", "title": f"{title} ({purpose}) – Wasalt #{m['id']}"[:300], "url": url,
            "content": (f"Wasalt property listing #{m['id']}: {title}, {purpose} in Saudi Arabia. "
                        f"Full details, price and location are on the listing page.{updated}"),
            "location": "Saudi Arabia", "property_type": _guess_type(title), "price": "",
        }
    if m := _DAILY_RE.search(path):
        title = _listing_title(m["slug"])
        return {
            "source": "Wasalt", "title": f"{title} – Wasalt daily rental #{m['id']}"[:300], "url": url,
            "content": (f"Wasalt daily rental listing #{m['id']}: {title} in Saudi Arabia. "
                        f"See the listing page for availability and nightly price.{updated}"),
            "location": "Saudi Arabia", "property_type": _guess_type(title), "price": "",
        }
    if m := _CATEGORY_RE.search(path):
        what = _humanize(m["what"])
        purpose = _humanize(m["purpose"])
        where = _humanize(m["where"]).title()
        title = f"{what.capitalize()} for {purpose} in {where}"
        return {
            "source": "Wasalt", "title": f"{title} – Wasalt"[:300], "url": url,
            "content": (f"Wasalt search page listing {what} available for {purpose} in {where}, "
                        f"Saudi Arabia. Browse current {what} for {purpose}, with prices and "
                        f"neighbourhood details for {where}, on Wasalt.{updated}"),
            "location": where, "property_type": _guess_type(what), "price": "",
        }
    return None


def scrape_wasalt(max_sitemap_records=5000, max_pages=35,
                  sections=("categories", "listings", "daily_rental_categories", "daily_rentals")):
    """Index Wasalt's public sitemaps and enrich a sample of pages when the site permits it.

    Returns (docs, report).
    """
    client = PoliteClient(WASALT_ROOT)
    report = {"source": "Wasalt", "pages_seen": 0, "status": "completed", "message": ""}
    docs_by_url = {}
    try:
        client.load_robots()
    except AccessBlocked as exc:
        report.update(status="blocked", message=str(exc))
        return [], report

    per_section = max(1, max_sitemap_records // max(1, len(sections)))
    for name in sections:
        for url, lastmod in iter_sitemap(client, WASALT_SITEMAPS[name], "wasalt.sa", limit=per_section):
            if not client.allowed(url):
                continue
            doc = wasalt_doc_from_sitemap(url, lastmod)
            if doc:
                docs_by_url[url] = doc

    notes = [f"{len(docs_by_url)} records from public sitemaps."]
    # Try to enrich listing pages with full details; stop politely if bot protection blocks us.
    enriched = 0
    try:
        for url in [u for u in docs_by_url if "/property/" in u or "/dailyrental/" in u][:max_pages]:
            resp = client.get(url)
            report["pages_seen"] += 1
            if resp is not None and "text/html" in resp.headers.get("content-type", ""):
                doc = extract_document(url, resp.text, "Wasalt")
                if doc:
                    base = docs_by_url[url]
                    doc["location"] = doc["location"] or base["location"]
                    doc["property_type"] = base["property_type"] or doc["property_type"]
                    docs_by_url[url] = doc
                    enriched += 1
        notes.append(f"{enriched} listing pages enriched with page content.")
    except AccessBlocked as exc:
        report["status"] = "partial"
        notes.append(f"Page enrichment skipped: {exc}")
    report["message"] = " ".join(notes)
    return list(docs_by_url.values()), report
