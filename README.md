# Property Intelligence

A chatbot for asking questions about property listings in Saudi Arabia. It searches data scraped from public pages and links every answer back to the original listing.

Built with FastAPI and SQLite full-text search. If you add an [OpenRouter](https://openrouter.ai/keys) key, answers are written by an LLM; without one, the app still works and returns a short summary of the matching listings.

## Run it

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env          # add OPENROUTER_API_KEY if you have one
.venv/bin/uvicorn app.main:app --port 10000
```

Open http://localhost:10000. Or use Docker: `docker compose up --build`.

The repo already includes a database (`data/property_intelligence.db`) with about 17,600 Wasalt pages, so you don't need to scrape before trying it.

## Scraping

```bash
.venv/bin/python scripts/scrape.py --source all
.venv/bin/python scripts/scrape.py --source wasalt --max-sitemap-records 20000 --max-pages 50
.venv/bin/python scripts/scrape.py --source wasalt --out data/wasalt.jsonl --no-db
```

`--max-sitemap-records` controls how many sitemap URLs are indexed. `--max-pages` controls how many listing pages are opened to pull in price, area and description. `--no-db` with `--out` writes JSON lines instead of updating the database.

**Wasalt** allows crawling in its `robots.txt` (except `/search`) and publishes sitemaps. The scraper indexes listing and category URLs from those sitemaps, then opens a sample of listing pages for full details.

**DarGlobal** sits behind Imperva bot protection, which blocks automated requests, so the scraper logs the run as `blocked` and moves on. Getting DarGlobal data would need an export or API access from them.

The scraper respects `robots.txt`, waits between requests (`CRAWL_DELAY`, 1.5s by default), and stops if a site serves a bot challenge. It doesn't try to get around one.

## Deploy (Fly.io)

```bash
fly secrets set OPENROUTER_API_KEY=... INGEST_TOKEN=...
fly deploy
```

The database is built into the Docker image, so the app has data as soon as it starts. To refresh it, scrape locally, commit the database and deploy again.

## API

| Endpoint | |
|---|---|
| `POST /api/chat` | `{"message": "...", "history": []}` |
| `GET /api/stats` | Document counts and recent scrape runs |
| `GET /health` | Health check |
| `POST /api/ingest/wasalt/scrape` | Run the Wasalt scraper (needs `X-Ingest-Token`) |
| `POST /api/ingest/darglobal` | Run the DarGlobal scraper (needs `X-Ingest-Token`) |
| `POST /api/ingest/wasalt` | Upload a JSON file of listings (needs `X-Ingest-Token`) |

---

Built by [Vinit Shahdeo](https://github.com/vinitshahdeo) for the DarGlobal assignment.
