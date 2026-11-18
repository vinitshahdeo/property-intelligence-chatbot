from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from .db import init_db, search_documents, stats
from .llm import answer_with_openrouter, grounded_fallback

app = FastAPI(title="Property Intelligence Chatbot", version="1.0.0",
              description="Chatbot over public property listings.")
app.mount("/static", StaticFiles(directory="app/static"), name="static")

@app.on_event("startup")
def startup():
    init_db()

class ChatRequest(BaseModel):
    message: str = Field(min_length=2, max_length=2000)
    history: list[dict] = Field(default_factory=list)

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
