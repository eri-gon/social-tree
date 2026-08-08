"""
app/sync_engine.py
------------------
Google Keep on-demand sync pipeline based on Google Takeout.

Responsibilities:
  1. Load KEEP_TAKEOUT_DIR from .env
  2. Scan the Takeout directory for JSON files containing "#name" in their filename
  3. Parse each JSON note individually, ignoring trashed notes
  4. Prepend cleaned titles as context headers
  5. Combine and parse notes text into individual graphs
  6. Merge graphs, deduplicating and combining metadata and contexts
  7. Cleanly upsert nodes and edges into PostgreSQL
  8. Return a summary dict { nodes_synced, edges_synced }
"""

import os
import sys
import glob
import json
import re
from dotenv import load_dotenv
from psycopg2.extras import Json

# ── locate .env relative to this file (project root) ──────────────────────────
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_ENV_PATH = os.path.join(_ROOT, ".env")

# ── import the in-memory parser ────────────────────────────────────────────────
sys.path.insert(0, os.path.join(_ROOT, "parser"))
from parser import parse_notes_text   # noqa: E402

def merge_graphs(graphs: list[dict]) -> dict:
    """
    Combine a list of graphs, deduplicating nodes and edges,
    and merging node metadata and contexts.
    """
    merged_nodes = {}
    merged_edges = set() # Store as (source, target, type)
    
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
                # Merge metadata
                for m in node.get("metadata", []):
                    if m not in merged_nodes[nid]["metadata"]:
                        merged_nodes[nid]["metadata"].append(m)
                # Merge contexts
                for c in node.get("contexts", []):
                    if c not in merged_nodes[nid]["contexts"]:
                        merged_nodes[nid]["contexts"].append(c)
                        
        for edge in graph["edges"]:
            merged_edges.add((edge["source"], edge["target"], edge["type"]))
            
    edges_list = [{"source": src, "target": tgt, "type": et} for src, tgt, et in merged_edges]
    return {"nodes": list(merged_nodes.values()), "edges": edges_list}

def run_sync(db_pool) -> dict:
    """
    Execute a full sync cycle using Google Takeout Keep files.
    """
    load_dotenv(dotenv_path=_ENV_PATH, override=True)
    
    takeout_dir = os.environ.get("KEEP_TAKEOUT_DIR", "/Users/ericgan/Takeout/keep/").strip()
    
    if not os.path.isdir(takeout_dir):
        raise RuntimeError(
            f"Google Keep Takeout directory not found at: '{takeout_dir}'. "
            "Please check the KEEP_TAKEOUT_DIR variable in your .env file."
        )

    # 1. Glob all JSON files containing "#name" in their filename
    search_pattern = os.path.join(takeout_dir, "*#name*.json")
    json_files = glob.glob(search_pattern)
    
    if not json_files:
        return {"nodes_synced": 0, "edges_synced": 0}

    # 2. Parse each JSON note individually and collect their graphs
    graphs = []
    
    for file_path in json_files:
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                note_data = json.load(f)
        except Exception as e:
            print(f"Warning: Failed to parse JSON file {file_path}: {e}")
            continue

        # Skip trashed notes
        if note_data.get("isTrashed", False):
            continue

        title = note_data.get("title", "").strip()
        text_content = note_data.get("textContent", "").strip()
        
        # Clean title by removing the #name tag (case-insensitive)
        cleaned_title = re.sub(r'#name', '', title, flags=re.IGNORECASE).strip()
        overall_context = cleaned_title if cleaned_title else None
        
        # Format the block: if a title exists, prepend it as a context header
        if cleaned_title:
            note_text = f"{cleaned_title}:\n{text_content}"
        else:
            note_text = text_content
            
        note_graph = parse_notes_text(note_text, overall_context=overall_context)
        graphs.append(note_graph)

    # 3. Merge all sub-graphs into a unified graph representation
    merged_graph = merge_graphs(graphs)
    nodes = merged_graph["nodes"]
    edges = merged_graph["edges"]

    # 4. Upsert into PostgreSQL
    conn = db_pool.getconn()
    try:
        with conn.cursor() as cur:
            # 4a. Clear existing graph data to remove obsolete/ghost nodes
            cur.execute("DELETE FROM nodes;")

            # 4b. Upsert nodes
            for node in nodes:
                cur.execute(
                    """
                    INSERT INTO nodes (id, name, type, metadata, contexts)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO UPDATE SET
                        name     = EXCLUDED.name,
                        type     = EXCLUDED.type,
                        metadata = EXCLUDED.metadata,
                        contexts = EXCLUDED.contexts;
                    """,
                    (
                        node["id"],
                        node["name"],
                        node["type"],
                        Json(node.get("metadata", [])),
                        Json(node.get("contexts", [])),
                    ),
                )

            # 4b. Upsert edges
            # Build a node-context lookup for edge context inference
            node_contexts = {n["id"]: n.get("contexts", []) for n in nodes}

            for edge in edges:
                source = edge["source"]
                target = edge["target"]
                etype  = edge["type"]

                # Infer context: membership edges use the target group name;
                # introduction edges use the first shared context.
                if etype == "membership":
                    context = target
                else:
                    src_ctxs = node_contexts.get(source, [])
                    tgt_ctxs = node_contexts.get(target, [])
                    shared   = [c for c in src_ctxs if c in tgt_ctxs]
                    context  = shared[0] if shared else None

                cur.execute(
                    """
                    INSERT INTO edges (source, target, type, context)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (source, target, type) DO UPDATE SET
                        context = EXCLUDED.context;
                    """,
                    (source, target, etype, context),
                )

        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        db_pool.putconn(conn)

    return {"nodes_synced": len(nodes), "edges_synced": len(edges)}
