# main.py
import os
import sys
import secrets
from datetime import datetime, timezone, timedelta
from typing import Optional, List
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException, Depends, Header, Query
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
import psycopg2
from psycopg2.pool import SimpleConnectionPool
from psycopg2.extras import Json
from contextlib import contextmanager
from dotenv import load_dotenv

# Load env
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(dotenv_path=os.path.join(_ROOT, ".env"))

sys.path.insert(0, os.path.join(_ROOT, "parser"))
from parser import parse_notes_text

app = FastAPI(title="Personal CRM Social Graph")

# Database Configuration: prefer DATABASE_URL (cloud), fall back to local config
DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
OWNER_SECRET = os.environ.get("OWNER_SECRET", "").strip()

try:
    if DATABASE_URL:
        db_pool = SimpleConnectionPool(1, 10, dsn=DATABASE_URL)
    else:
        DB_CONFIG = {
            "host": "localhost",
            "port": 5432,
            "user": "eric",
            "password": "password123",
            "database": "keep_social_graph",
        }
        db_pool = SimpleConnectionPool(1, 10, **DB_CONFIG)
except Exception as e:
    print(f"Database connection pool creation failed: {e}")
    sys.exit(1)

@contextmanager
def get_db_connection():
    conn = db_pool.getconn()
    try:
        yield conn
    finally:
        db_pool.putconn(conn)

def require_owner(x_owner_token: Optional[str] = Header(default=None)):
    if not OWNER_SECRET:
        raise HTTPException(status_code=500, detail="OWNER_SECRET is not configured on this server.")
    if not x_owner_token or not secrets.compare_digest(x_owner_token, OWNER_SECRET):
        raise HTTPException(status_code=403, detail="Invalid or missing owner token.")

class NodeCreate(BaseModel):
    id: str
    name: str
    type: str
    metadata: List[str] = []
    contexts: List[str] = []

class NodeUpdate(BaseModel):
    name: Optional[str] = None
    metadata: Optional[List[str]] = None
    contexts: Optional[List[str]] = None

class EdgeCreate(BaseModel):
    source: str
    target: str
    type: str
    context: Optional[str] = None

class NoteCreate(BaseModel):
    title: str = ""
    content: str = ""
    color: str = "default"
    pinned: bool = False

class NoteUpdate(BaseModel):
    title: Optional[str] = None
    content: Optional[str] = None
    color: Optional[str] = None
    pinned: Optional[bool] = None

static_dir = os.path.join(os.path.dirname(__file__), "static")
os.makedirs(static_dir, exist_ok=True)

def merge_graphs(graphs: list) -> dict:
    merged_nodes = {}
    merged_edges = set()
    for graph in graphs:
        for node in graph.get("nodes", []):
            nid = node["id"]
            if nid not in merged_nodes:
                merged_nodes[nid] = {
                    "id": nid,
                    "name": node["name"],
                    "type": node["type"],
                    "metadata": list(node.get("metadata", [])),
                    "contexts": list(node.get("contexts", []))
                }
            else:
                for m in node.get("metadata", []):
                    if m not in merged_nodes[nid]["metadata"]:
                        merged_nodes[nid]["metadata"].append(m)
                for c in node.get("contexts", []):
                    if c not in merged_nodes[nid]["contexts"]:
                        merged_nodes[nid]["contexts"].append(c)
        for edge in graph.get("edges", []):
            merged_edges.add((edge["source"], edge["target"], edge["type"]))
    edges_list = [{"source": src, "target": tgt, "type": et} for src, tgt, et in merged_edges]
    return {"nodes": list(merged_nodes.values()), "edges": edges_list}

def rebuild_graph_from_notes(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT title, content FROM notes ORDER BY id ASC;")
        rows = cur.fetchall()

    graphs = []
    for title, content in rows:
        title_clean = title.strip() if title else ""
        content_clean = content.strip() if content else ""
        overall_context = title_clean if title_clean else None
        if title_clean:
            note_text = f"{title_clean}:\n{content_clean}"
        else:
            note_text = content_clean
        if note_text:
            graph = parse_notes_text(note_text, overall_context=overall_context)
            graphs.append(graph)

    merged = merge_graphs(graphs)
    nodes = merged["nodes"]
    edges = merged["edges"]

    with conn.cursor() as cur:
        cur.execute("DELETE FROM edges;")
        cur.execute("DELETE FROM nodes;")

        for node in nodes:
            cur.execute(
                """
                INSERT INTO nodes (id, name, type, metadata, contexts)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET
                    name = EXCLUDED.name,
                    type = EXCLUDED.type,
                    metadata = EXCLUDED.metadata,
                    contexts = EXCLUDED.contexts;
                """,
                (node["id"], node["name"], node["type"], Json(node.get("metadata", [])), Json(node.get("contexts", [])))
            )

        node_contexts = {n["id"]: n.get("contexts", []) for n in nodes}
        for edge in edges:
            source, target, etype = edge["source"], edge["target"], edge["type"]
            if etype == "membership":
                context = target
            else:
                src_ctxs = node_contexts.get(source, [])
                tgt_ctxs = node_contexts.get(target, [])
                shared = [c for c in src_ctxs if c in tgt_ctxs]
                context = shared[0] if shared else None
            cur.execute(
                """
                INSERT INTO edges (source, target, type, context)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (source, target, type) DO UPDATE SET context = EXCLUDED.context;
                """,
                (source, target, etype, context)
            )

@app.get("/")
def read_root():
    return FileResponse(os.path.join(static_dir, "index.html"))

@app.get("/api/graph")
def get_graph_data():
    nodes = []
    edges = []
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            try:
                cursor.execute("SELECT id, name, type, metadata, contexts FROM nodes WHERE id <> 'eric_gan';")
                for row in cursor.fetchall():
                    nodes.append({"id": row[0], "name": row[1], "type": row[2], "metadata": row[3], "contexts": row[4]})
                cursor.execute("SELECT id, source, target, type, context FROM edges WHERE source <> 'eric_gan' AND target <> 'eric_gan';")
                for row in cursor.fetchall():
                    edges.append({"id": row[0], "source": row[1], "target": row[2], "type": row[3], "context": row[4]})
            except Exception as e:
                raise HTTPException(status_code=500, detail=f"Database query failed: {e}")
    return {"nodes": nodes, "edges": edges}

# ── NOTES ENDPOINTS ─────────────────────────────────────────────────────────────

@app.get("/api/notes")
def list_notes():
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            try:
                cur.execute(
                    """
                    SELECT id, title, content, color, pinned, source, created_at, updated_at
                    FROM notes
                    ORDER BY pinned DESC, updated_at DESC, id DESC;
                    """
                )
                rows = cur.fetchall()
            except Exception as e:
                raise HTTPException(status_code=500, detail=f"Query failed: {e}")
    return [
        {
            "id": r[0],
            "title": r[1],
            "content": r[2],
            "color": r[3],
            "pinned": r[4],
            "source": r[5],
            "created_at": r[6].isoformat() if r[6] else None,
            "updated_at": r[7].isoformat() if r[7] else None,
        }
        for r in rows
    ]

@app.post("/api/notes", status_code=201, dependencies=[Depends(require_owner)])
def create_note(note: NoteCreate):
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            try:
                cur.execute(
                    """
                    INSERT INTO notes (title, content, color, pinned, source)
                    VALUES (%s, %s, %s, %s, 'manual')
                    RETURNING id, title, content, color, pinned, source, created_at, updated_at;
                    """,
                    (note.title, note.content, note.color, note.pinned)
                )
                row = cur.fetchone()
            except Exception as e:
                conn.rollback()
                raise HTTPException(status_code=400, detail=f"Create note failed: {e}")
        rebuild_graph_from_notes(conn)
        conn.commit()
    return {
        "id": row[0],
        "title": row[1],
        "content": row[2],
        "color": row[3],
        "pinned": row[4],
        "source": row[5],
        "created_at": row[6].isoformat() if row[6] else None,
        "updated_at": row[7].isoformat() if row[7] else None,
    }

@app.put("/api/notes/{note_id}", dependencies=[Depends(require_owner)])
def update_note(note_id: int, update: NoteUpdate):
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id, title, content, color, pinned FROM notes WHERE id = %s;", (note_id,))
            existing = cur.fetchone()
            if not existing:
                raise HTTPException(status_code=404, detail=f"Note {note_id} not found.")

            new_title = update.title if update.title is not None else existing[1]
            new_content = update.content if update.content is not None else existing[2]
            new_color = update.color if update.color is not None else existing[3]
            new_pinned = update.pinned if update.pinned is not None else existing[4]

            try:
                cur.execute(
                    """
                    UPDATE notes
                    SET title = %s, content = %s, color = %s, pinned = %s, updated_at = NOW()
                    WHERE id = %s
                    RETURNING id, title, content, color, pinned, source, created_at, updated_at;
                    """,
                    (new_title, new_content, new_color, new_pinned, note_id)
                )
                row = cur.fetchone()
            except Exception as e:
                conn.rollback()
                raise HTTPException(status_code=400, detail=f"Update note failed: {e}")
        rebuild_graph_from_notes(conn)
        conn.commit()
    return {
        "id": row[0],
        "title": row[1],
        "content": row[2],
        "color": row[3],
        "pinned": row[4],
        "source": row[5],
        "created_at": row[6].isoformat() if row[6] else None,
        "updated_at": row[7].isoformat() if row[7] else None,
    }

@app.delete("/api/notes/{note_id}", status_code=204, dependencies=[Depends(require_owner)])
def delete_note(note_id: int):
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM notes WHERE id = %s;", (note_id,))
            if not cur.fetchone():
                raise HTTPException(status_code=404, detail=f"Note {note_id} not found.")
            try:
                cur.execute("DELETE FROM notes WHERE id = %s;", (note_id,))
            except Exception as e:
                conn.rollback()
                raise HTTPException(status_code=400, detail=f"Delete note failed: {e}")
        rebuild_graph_from_notes(conn)
        conn.commit()
    return None

# ── NODE & EDGE ENDPOINTS (Legacy/Direct) ──────────────────────────────────────

@app.get("/api/nodes")
def list_nodes(type: Optional[str] = Query(default=None)):
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            try:
                if type:
                    cur.execute("SELECT id, name, type, metadata, contexts FROM nodes WHERE type = %s ORDER BY name;", (type,))
                else:
                    cur.execute("SELECT id, name, type, metadata, contexts FROM nodes ORDER BY name;")
                rows = cur.fetchall()
            except Exception as e:
                raise HTTPException(status_code=500, detail=f"Query failed: {e}")
    return [{"id": r[0], "name": r[1], "type": r[2], "metadata": r[3], "contexts": r[4]} for r in rows]

@app.post("/api/nodes", status_code=201, dependencies=[Depends(require_owner)])
def create_node(node: NodeCreate):
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            try:
                cur.execute(
                    "INSERT INTO nodes (id, name, type, metadata, contexts) VALUES (%s, %s, %s, %s, %s) ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name, type = EXCLUDED.type, metadata = EXCLUDED.metadata, contexts = EXCLUDED.contexts RETURNING id, name, type, metadata, contexts;",
                    (node.id, node.name, node.type, Json(node.metadata), Json(node.contexts))
                )
                row = cur.fetchone()
            except Exception as e:
                conn.rollback()
                raise HTTPException(status_code=400, detail=f"Create failed: {e}")
        conn.commit()
    return {"id": row[0], "name": row[1], "type": row[2], "metadata": row[3], "contexts": row[4]}

@app.put("/api/nodes/{node_id}", dependencies=[Depends(require_owner)])
def update_node(node_id: str, update: NodeUpdate):
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id, name, type, metadata, contexts FROM nodes WHERE id = %s;", (node_id,))
            existing = cur.fetchone()
            if not existing:
                raise HTTPException(status_code=404, detail=f"Node '{node_id}' not found.")
            new_name = update.name if update.name is not None else existing[1]
            new_metadata = update.metadata if update.metadata is not None else existing[3]
            new_contexts = update.contexts if update.contexts is not None else existing[4]
            try:
                cur.execute(
                    "UPDATE nodes SET name = %s, metadata = %s, contexts = %s WHERE id = %s RETURNING id, name, type, metadata, contexts;",
                    (new_name, Json(new_metadata), Json(new_contexts), node_id)
                )
                row = cur.fetchone()
            except Exception as e:
                conn.rollback()
                raise HTTPException(status_code=400, detail=f"Update failed: {e}")
        conn.commit()
    return {"id": row[0], "name": row[1], "type": row[2], "metadata": row[3], "contexts": row[4]}

@app.delete("/api/nodes/{node_id}", status_code=204, dependencies=[Depends(require_owner)])
def delete_node(node_id: str):
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM nodes WHERE id = %s;", (node_id,))
            if not cur.fetchone():
                raise HTTPException(status_code=404, detail=f"Node '{node_id}' not found.")
            try:
                cur.execute("DELETE FROM nodes WHERE id = %s;", (node_id,))
            except Exception as e:
                conn.rollback()
                raise HTTPException(status_code=400, detail=f"Delete failed: {e}")
        conn.commit()
    return None

@app.post("/api/edges", status_code=201, dependencies=[Depends(require_owner)])
def create_edge(edge: EdgeCreate):
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            try:
                cur.execute(
                    "INSERT INTO edges (source, target, type, context) VALUES (%s, %s, %s, %s) ON CONFLICT (source, target, type) DO UPDATE SET context = EXCLUDED.context RETURNING id, source, target, type, context;",
                    (edge.source, edge.target, edge.type, edge.context)
                )
                row = cur.fetchone()
            except Exception as e:
                conn.rollback()
                raise HTTPException(status_code=400, detail=f"Create edge failed: {e}")
        conn.commit()
    return {"id": row[0], "source": row[1], "target": row[2], "type": row[3], "context": row[4]}

@app.delete("/api/edges/{edge_id}", status_code=204, dependencies=[Depends(require_owner)])
def delete_edge(edge_id: int):
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM edges WHERE id = %s;", (edge_id,))
            if not cur.fetchone():
                raise HTTPException(status_code=404, detail=f"Edge {edge_id} not found.")
            try:
                cur.execute("DELETE FROM edges WHERE id = %s;", (edge_id,))
            except Exception as e:
                conn.rollback()
                raise HTTPException(status_code=400, detail=f"Delete failed: {e}")
        conn.commit()
    return None

@app.post("/api/sync")
def trigger_sync():
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            try:
                cur.execute("SELECT last_successful_sync FROM sync_metadata ORDER BY last_successful_sync DESC LIMIT 1;")
                row = cur.fetchone()
            except Exception as e:
                raise HTTPException(status_code=500, detail=f"Could not query sync_metadata: {e}")
    if row:
        last_sync: datetime = row[0]
        age = datetime.now(timezone.utc) - last_sync
        if age < timedelta(hours=24):
            hours_left = 24 - (age.total_seconds() / 3600)
            raise HTTPException(status_code=429, detail=f"Sync throttled. Next sync available in {hours_left:.1f} hour(s).")
    from database.import_keep_notes import import_notes
    try:
        import_notes()
    except RuntimeError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Sync failed: {e}")
    synced_at = datetime.now(timezone.utc)
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO sync_metadata (last_successful_sync) VALUES (%s);", (synced_at,))
        conn.commit()
    return {"status": "success", "synced_at": synced_at.isoformat()}

app.mount("/static", StaticFiles(directory=static_dir), name="static")
