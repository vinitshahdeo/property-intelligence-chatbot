import json
from fastapi import FastAPI, HTTPException, Header, UploadFile, File
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from .config import INGEST_TOKEN
from .db import init_db, search_documents, stats
from .ingestion import crawl_darglobal, crawl_wasalt, import_wasalt_json
from .llm import answer_with_openrouter, grounded_fallback

app = FastAPI(title="Property Intelligence Chatbot", version="1.0.0",
              description="RAG chatbot over permitted DarGlobal and authorized Wasalt data.")
app.mount("/static", StaticFiles(directory="app/static"), name="static")

@app.on_event("startup")
def startup():
    init_db()

class ChatRequest(BaseModel):
    message: str = Field(min_length=2, max_length=2000)
    history: list[dict] = Field(default_factory=list)

def require_token(token):
    if not INGEST_TOKEN:
        raise HTTPException(503, "Set INGEST_TOKEN before using ingestion endpoints.")
    if token != INGEST_TOKEN:
        raise HTTPException(401, "Invalid ingestion token.")

@app.get("/", response_class=HTMLResponse)
def home():
    with open("app/static/index.html", encoding="utf-8") as f:
        return f.read()

@app.get("/health")
def health():
    return {"status": "ok"}

@app.get("/api/stats")
def get_stats():
    return stats()

@app.post("/api/chat")
def chat(req: ChatRequest):
    docs = search_documents(req.message, limit=6)
    try:
        answer = answer_with_openrouter(req.message, req.history, docs)
        mode = "openrouter" if answer else "retrieval_only"
    except Exception as exc:
        answer = grounded_fallback(req.message, docs)
        mode = "retrieval_fallback"
        error = str(exc)[:240]
    else:
        error = None
    sources = [{
        "index": i + 1, "source": d["source"], "title": d["title"],
        "url": d["url"], "updated_at": d["updated_at"],
        "location": d.get("location", ""), "property_type": d.get("property_type", ""),
        "price": d.get("price", ""),
    } for i, d in enumerate(docs)]
    return {"answer": answer or grounded_fallback(req.message, docs),
            "sources": sources, "mode": mode, "warning": error}

@app.post("/api/ingest/darglobal")
def ingest_darglobal(x_ingest_token: str = Header(default="")):
    require_token(x_ingest_token)
    try:
        return crawl_darglobal()
    except Exception as exc:
        raise HTTPException(500, f"Ingestion failed: {str(exc)[:300]}")

@app.post("/api/ingest/wasalt/scrape")
def ingest_wasalt_scrape(x_ingest_token: str = Header(default="")):
    require_token(x_ingest_token)
    try:
        return crawl_wasalt()
    except Exception as exc:
        raise HTTPException(500, f"Ingestion failed: {str(exc)[:300]}")

@app.post("/api/ingest/wasalt")
async def ingest_wasalt(file: UploadFile = File(...), x_ingest_token: str = Header(default="")):
    require_token(x_ingest_token)
    if not file.filename.lower().endswith(".json"):
        raise HTTPException(400, "Upload a JSON export from an authorized Wasalt feed.")
    try:
        payload = json.loads((await file.read()).decode("utf-8"))
        result = import_wasalt_json(payload)
        return result
    except Exception as exc:
        raise HTTPException(400, f"Could not import JSON: {str(exc)[:300]}")
