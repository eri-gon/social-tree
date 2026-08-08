import os
import sys
import glob
import json
import re
from urllib.parse import urlparse
import psycopg2
from dotenv import load_dotenv

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(dotenv_path=os.path.join(_ROOT, ".env"))

sys.path.insert(0, os.path.join(_ROOT, "parser"))
from parser import parse_notes_text
from psycopg2.extras import Json

# Database connection settings
DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
if DATABASE_URL:
    parsed = urlparse(DATABASE_URL)
    DB_CONFIG = {
        "host": parsed.hostname,
        "port": parsed.port or 5432,
        "user": parsed.username,
        "password": parsed.password,
        "database": parsed.path.lstrip("/"),
        "sslmode": "require",
    }
else:
    DB_CONFIG = {
        "host": "localhost",
        "port": 5432,
        "user": "eric",
        "password": "password123",
        "database": "keep_social_graph",
    }

def merge_graphs(graphs: list) -> dict:
    merged_nodes = {}
    merged_edges = set()
    for graph in graphs:
        for node in graph["nodes"]:
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
        for edge in graph["edges"]:
            merged_edges.add((edge["source"], edge["target"], edge["type"]))
    edges_list = [{"source": src, "target": tgt, "type": et} for src, tgt, et in merged_edges]
    return {"nodes": list(merged_nodes.values()), "edges": edges_list}

def rebuild_graph(conn):
    """Fetch all notes from notes table, parse them, and update nodes/edges tables."""
    with conn.cursor() as cur:
        cur.execute("SELECT id, title, content FROM notes ORDER BY id ASC;")
        rows = cur.fetchall()
    
    graphs = []
    for note_id, title, content in rows:
        title_clean = title.strip()
        content_clean = content.strip()
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
    conn.commit()
    print(f"Graph rebuilt successfully: {len(nodes)} nodes, {len(edges)} edges.")
    return len(nodes), len(edges)

def import_notes():
    conn = psycopg2.connect(**DB_CONFIG)
    try:
        takeout_dir = os.environ.get("KEEP_TAKEOUT_DIR", "/Users/ericgan/Takeout/keep/").strip()
        json_files = []
        if os.path.isdir(takeout_dir):
            json_files = glob.glob(os.path.join(takeout_dir, "*#name*.json"))
            if not json_files:
                json_files = glob.glob(os.path.join(takeout_dir, "*.json"))

        notes_to_insert = []
        if json_files:
            print(f"Found {len(json_files)} Keep JSON files in {takeout_dir}")
            for fp in json_files:
                try:
                    with open(fp, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    if data.get("isTrashed", False):
                        continue
                    title = data.get("title", "").strip()
                    content = data.get("textContent", "").strip()
                    title_clean = re.sub(r'#name', '', title, flags=re.IGNORECASE).strip()
                    if title_clean or content:
                        notes_to_insert.append((title_clean, content, "keep_import"))
                except Exception as e:
                    print(f"Error reading {fp}: {e}")
        
        # Also check sample_notes.txt if no JSON files found or to ensure sample notes are included
        sample_path = os.path.join(_ROOT, "parser", "sample_notes.txt")
        if not notes_to_insert and os.path.exists(sample_path):
            print(f"Importing from {sample_path}")
            with open(sample_path, "r", encoding="utf-8") as f:
                raw_text = f.read()
            # Split sections by ---
            sections = raw_text.split("---")
            for idx, sec in enumerate(sections, 1):
                sec = sec.strip()
                if not sec:
                    continue
                lines = sec.splitlines()
                first_line = lines[0].strip()
                if first_line.endswith(":") or first_line.endswith("#name"):
                    title = re.sub(r'#name|:$', '', first_line, flags=re.IGNORECASE).strip()
                    content = "\n".join(lines[1:]).strip()
                else:
                    title = f"Note {idx}"
                    content = sec
                notes_to_insert.append((title, content, "sample_import"))

        with conn.cursor() as cur:
            for title, content, src in notes_to_insert:
                # Avoid exact duplicates
                cur.execute("SELECT id FROM notes WHERE title = %s AND content = %s;", (title, content))
                if not cur.fetchone():
                    cur.execute(
                        "INSERT INTO notes (title, content, source) VALUES (%s, %s, %s);",
                        (title, content, src)
                    )
        conn.commit()
        print(f"Imported notes into 'notes' table.")

        # Rebuild graph
        rebuild_graph(conn)
    finally:
        conn.close()

if __name__ == "__main__":
    import_notes()
