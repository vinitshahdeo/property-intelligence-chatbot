import re
import sqlite3
from datetime import datetime, timezone
from .config import DB_PATH

def connect():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con

def init_db():
    with connect() as con:
        con.execute("""
        CREATE TABLE IF NOT EXISTS documents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source TEXT NOT NULL,
            title TEXT NOT NULL,
            url TEXT NOT NULL UNIQUE,
            content TEXT NOT NULL,
            location TEXT DEFAULT '',
            property_type TEXT DEFAULT '',
            price TEXT DEFAULT '',
            updated_at TEXT NOT NULL
        )""")
        con.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS documents_fts
        USING fts5(title, content, location, property_type, content='documents', content_rowid='id')
        """)
        con.executescript("""
        CREATE TRIGGER IF NOT EXISTS documents_ai AFTER INSERT ON documents BEGIN
          INSERT INTO documents_fts(rowid,title,content,location,property_type)
          VALUES(new.id,new.title,new.content,new.location,new.property_type);
        END;
        CREATE TRIGGER IF NOT EXISTS documents_ad AFTER DELETE ON documents BEGIN
          INSERT INTO documents_fts(documents_fts,rowid,title,content,location,property_type)
          VALUES('delete',old.id,old.title,old.content,old.location,old.property_type);
        END;
        CREATE TRIGGER IF NOT EXISTS documents_au AFTER UPDATE ON documents BEGIN
          INSERT INTO documents_fts(documents_fts,rowid,title,content,location,property_type)
          VALUES('delete',old.id,old.title,old.content,old.location,old.property_type);
          INSERT INTO documents_fts(rowid,title,content,location,property_type)
          VALUES(new.id,new.title,new.content,new.location,new.property_type);
        END;
        """)
        con.execute("""
        CREATE TABLE IF NOT EXISTS ingestion_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source TEXT NOT NULL,
            status TEXT NOT NULL,
            pages_seen INTEGER DEFAULT 0,
            records_saved INTEGER DEFAULT 0,
            message TEXT DEFAULT '',
            created_at TEXT NOT NULL
        )""")

_UPSERT_SQL = """
        INSERT INTO documents(source,title,url,content,location,property_type,price,updated_at)
        VALUES(?,?,?,?,?,?,?,?)
        ON CONFLICT(url) DO UPDATE SET
          source=excluded.source,title=excluded.title,content=excluded.content,
          location=excluded.location,property_type=excluded.property_type,
          price=excluded.price,updated_at=excluded.updated_at
        """

def _doc_row(doc, now):
    return (doc.get("source", "Unknown"), doc["title"], doc["url"], doc["content"],
            doc.get("location", ""), doc.get("property_type", ""), doc.get("price", ""), now)

def upsert_documents(docs):
    now = datetime.now(timezone.utc).isoformat()
    with connect() as con:
        con.executemany(_UPSERT_SQL, [_doc_row(d, now) for d in docs])
    return len(docs)

def log_run(source, status, pages_seen, records_saved, message=""):
    with connect() as con:
        con.execute(
            "INSERT INTO ingestion_runs(source,status,pages_seen,records_saved,message,created_at) VALUES(?,?,?,?,?,?)",
            (source, status, pages_seen, records_saved, message,
             datetime.now(timezone.utc).isoformat())
        )

_STOPWORDS = {"a", "an", "the", "in", "on", "at", "for", "of", "to", "and", "or", "with", "me", "show",
              "find", "list", "any", "some", "what", "which", "are", "is", "there", "near", "around",
              "please", "i", "want", "looking", "need", "can", "you", "get", "all", "available"}
_NUMBER_WORDS = {"one": "1", "two": "2", "three": "3", "four": "4", "five": "5", "six": "6",
                 "seven": "7", "eight": "8", "nine": "9", "ten": "10"}

def _query_terms(query):
    words = re.findall(r"[^\W_]+", query.lower())
    terms = []
    for w in words:
        w = _NUMBER_WORDS.get(w, w)
        if w in _STOPWORDS or (len(w) < 2 and not w.isdigit()):
            continue
        terms.append(w)
    return list(dict.fromkeys(terms))[:10]

def _fts_term(t):
    # Prefix-match a crude singular so "apartments" also matches "apartment".
    if not t.isdigit() and len(t) > 4 and t.endswith("s"):
        t = t[:-1]
    return f'"{t}"*' if not t.isdigit() else f'"{t}"'

def search_documents(query, limit=6):
    terms = _query_terms(query)
    if not terms:
        return []
    fts_terms = [_fts_term(t) for t in terms]
    rows = []
    with connect() as con:
        # Prefer documents matching every term; fall back to any term. Title matches weigh most.
        for joiner in (" AND ", " OR "):
            try:
                rows = con.execute("""
                  SELECT d.* FROM documents_fts f
                  JOIN documents d ON d.id=f.rowid
                  WHERE documents_fts MATCH ?
                  ORDER BY bm25(documents_fts, 6.0, 1.0, 3.0, 1.0) - (d.price != '') * 2.0
                  LIMIT ?
                """, (joiner.join(fts_terms), limit)).fetchall()
            except sqlite3.OperationalError:
                rows = []
            if rows:
                break
        if not rows:
            clauses = " OR ".join("content LIKE ?" for _ in terms)
            rows = con.execute(
                f"SELECT * FROM documents WHERE {clauses} ORDER BY updated_at DESC LIMIT ?",
                tuple(f"%{t}%" for t in terms) + (limit,)
            ).fetchall()
    return [dict(r) for r in rows]

def stats():
    with connect() as con:
        total = con.execute("SELECT COUNT(*) n FROM documents").fetchone()["n"]
        sources = con.execute("SELECT source,COUNT(*) n FROM documents GROUP BY source").fetchall()
        runs = con.execute("SELECT * FROM ingestion_runs ORDER BY id DESC LIMIT 8").fetchall()
    return {"documents": total, "by_source": {r["source"]: r["n"] for r in sources},
            "recent_runs": [dict(r) for r in runs]}
