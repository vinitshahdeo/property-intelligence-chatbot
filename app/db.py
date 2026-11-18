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

def upsert_document(doc):
    upsert_documents([doc])

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

def search_documents(query, limit=6):
    terms = [t for t in query.replace('"', ' ').split() if len(t) > 1][:10]
    if not terms:
        return []
    # FTS5 syntax is constructed only from alphanumeric tokens.
    safe = " OR ".join('"' + ''.join(c for c in t if c.isalnum()) + '"' for t in terms)
    safe = safe.replace('""', '')
    with connect() as con:
        try:
            rows = con.execute("""
              SELECT d.* FROM documents_fts f
              JOIN documents d ON d.id=f.rowid
              WHERE documents_fts MATCH ? ORDER BY rank LIMIT ?
            """, (safe, limit)).fetchall()
        except sqlite3.OperationalError:
            rows = []
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
