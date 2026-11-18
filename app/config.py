import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.getenv("DATA_DIR", ROOT / "data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / "property_intelligence.db"

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "openrouter/free")
OPENROUTER_SITE_URL = os.getenv("OPENROUTER_SITE_URL", "https://property-intelligence-chatbot.onrender.com")
OPENROUTER_APP_NAME = os.getenv("OPENROUTER_APP_NAME", "Property Intelligence Chatbot")
INGEST_TOKEN = os.getenv("INGEST_TOKEN", "")
MAX_CRAWL_PAGES = int(os.getenv("MAX_CRAWL_PAGES", "35"))
REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "15"))
CRAWL_DELAY = float(os.getenv("CRAWL_DELAY", "1.5"))
WASALT_MAX_SITEMAP_RECORDS = int(os.getenv("WASALT_MAX_SITEMAP_RECORDS", "5000"))
