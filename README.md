# Property Intelligence Chatbot — DarGlobal × Wasalt

A Dockerized, source-grounded property research chatbot. FastAPI serves the chat UI and API; SQLite FTS5 provides local retrieval; OpenRouter supplies the LLM when an API key is configured.

## Features

- Responsive property research chat UI
- Retrieval from indexed source documents with clickable citations
- OpenRouter-compatible model routing (default: `openrouter/free`)
- Retrieval-only fallback when no API key is configured or the LLM is unavailable
- DarGlobal and Wasalt scrapers (`app/scraper.py`, `scripts/scrape.py`) that honour `robots.txt`, use public sitemaps, rate-limit requests, and stop when a site serves a bot-protection challenge
- Wasalt JSON import adapter for data obtained through an authorized feed/export
- SQLite persistence, ingestion audit log, Docker, and Render Blueprint

## Data-use and compliance

Only index content you are permitted to collect and reuse. The scrapers check each site's `robots.txt` (and fail closed if it cannot be read), use a descriptive user agent, only visit sitemap URLs, and rate-limit requests (`CRAWL_DELAY`, default 1.5s). If a site answers with a Cloudflare/Imperva challenge, the scraper records the run as `blocked`/`partial` and stops — it never tries to bypass bot protection. Review each site's current terms before running. Do not bypass login, CAPTCHA, rate limits, technical controls, or contractual restrictions.

## Scrape public data (CLI)

```bash
pip install -r requirements.txt
python scripts/scrape.py --source all                      # DarGlobal + Wasalt into SQLite
python scripts/scrape.py --source wasalt --max-sitemap-records 20000 --max-pages 50
python scripts/scrape.py --source wasalt --out data/wasalt.jsonl --no-db   # export only
# In Docker: docker compose exec <service> python scripts/scrape.py --source all
```

What each source yields:

- **Wasalt** — `robots.txt` allows everything except `/search` and publishes sitemaps on `cdn.wasalt.sa`. The scraper indexes listing, daily-rental, and city/district category URLs from those sitemaps (property type, sale/rent, location from the URL), then fetches up to `--max-pages` listing pages to add full details (price, district/city, bedrooms, area, description) from JSON-LD and page text. If Cloudflare challenges page requests, the sitemap records are still saved and the run is marked `partial`.
- **DarGlobal** — `darglobal.co.uk` is behind Imperva/Incapsula bot protection, which currently serves a challenge even for `robots.txt`, so the run is recorded as `blocked` and nothing is fetched. To include DarGlobal, obtain an authorized export/feed or allowlisting from DarGlobal.

Settings: `CRAWL_DELAY`, `MAX_CRAWL_PAGES` (pages fetched per site), `WASALT_MAX_SITEMAP_RECORDS`, `REQUEST_TIMEOUT`.

## Run locally

```bash
cp .env.example .env
# Add your OpenRouter key and a strong INGEST_TOKEN to .env
docker compose up --build
```

Open http://localhost:10000

The app works without an OpenRouter key in retrieval-only mode. Add a key from https://openrouter.ai/keys to enable generated answers. Default model `openrouter/free` dynamically routes to an available free model; free model availability and provider rate limits can change.

## Ingest DarGlobal

Set `INGEST_TOKEN` in `.env`, then:

```bash
curl -X POST http://localhost:10000/api/ingest/darglobal \
  -H "X-Ingest-Token: $INGEST_TOKEN"
```

The crawler starts from the public sitemap, checks robots permissions per page, caps the number of pages, and waits one second between requests. It may index zero pages if the sitemap is unavailable or the site's robots policy disallows access.

## Import an authorized Wasalt export

Create `wasalt-export.json` in this format:

```json
{
  "properties": [
    {
      "title": "Example property title",
      "url": "https://wasalt.sa/en/example",
      "description": "Description from an authorized Wasalt export",
      "location": "Riyadh",
      "property_type": "Apartment",
      "price": "Not supplied"
    }
  ]
}
```

Import it:

```bash
curl -X POST http://localhost:10000/api/ingest/wasalt \
  -H "X-Ingest-Token: $INGEST_TOKEN" \
  -F "file=@wasalt-export.json"
```

## API

- `GET /health` — health check
- `GET /api/stats` — indexed document counts and ingestion runs
- `POST /api/chat` — `{ "message": "...", "history": [] }`
- `POST /api/ingest/darglobal` — authenticated DarGlobal scrape
- `POST /api/ingest/wasalt/scrape` — authenticated Wasalt public-sitemap scrape
- `POST /api/ingest/wasalt` — authenticated authorized JSON import

## Deploy to Render

1. Push this repository to GitHub.
2. In Render, choose **New → Blueprint** and connect the repository containing `render.yaml`.
3. Review the service and create it. The Blueprint uses Docker, a persistent disk at `/app/data`, and a generated `INGEST_TOKEN`.
4. Add `OPENROUTER_API_KEY` in the Render service's Environment settings. Keep it secret; never commit it.
5. Deploy and open the generated `onrender.com` URL. Check `/health`.
6. Run ingestion using the `INGEST_TOKEN` from Render's Environment page. Do not share the token publicly.

The included Blueprint uses a paid Starter web service because persistent disks are not available on Render's free web-service plan. You can remove the disk and use a free plan for a disposable demo, but the local SQLite index may be lost on restarts/redeploys. See Render's current plan and disk pricing before creating the service.

## Production hardening before real customer use

- Confirm permission/terms for each data source and establish refresh rules.
- Add authentication/rate limiting for chat if exposing beyond a demo.
- Add request quotas, logging/monitoring, backup/restore, and error tracking.
- Consider Postgres + managed vector search for larger datasets.
- Add automated tests, CI, and a scheduled ingestion worker.
- Do not present stale listing prices or availability as current.
