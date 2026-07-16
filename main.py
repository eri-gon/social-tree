# main.py
import os
import sys
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import psycopg2
from psycopg2.pool import SimpleConnectionPool
from contextlib import contextmanager

app = FastAPI(title="Personal CRM Social Graph")

# Database Configuration
DB_CONFIG = {
    "host": "localhost",
    "port": 5432,
    "user": "eric",
    "password": "password123",
    "database": "keep_social_graph"
}

# Create simple connection pool
try:
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

# Serve static folder
static_dir = os.path.join(os.path.dirname(__file__), "static")
os.makedirs(static_dir, exist_ok=True)

@app.get("/api/graph")
def get_graph_data():
    """Fetch nodes and edges from PostgreSQL and return as a D3-compatible format."""
    nodes = []
    edges = []
    
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            try:
                # 1. Fetch Nodes
                cursor.execute("SELECT id, name, type, metadata, contexts FROM nodes;")
                for row in cursor.fetchall():
                    nodes.append({
                        "id": row[0],
                        "name": row[1],
                        "type": row[2],
                        "metadata": row[3], # JSONB list
                        "contexts": row[4]  # JSONB list
                    })
                
                # 2. Fetch Edges
                cursor.execute("SELECT source, target, type, context FROM edges;")
                for row in cursor.fetchall():
                    edges.append({
                        "source": row[0],
                        "target": row[1],
                        "type": row[2],
                        "context": row[3]
                    })
            except Exception as e:
                raise HTTPException(status_code=500, detail=f"Database query failed: {e}")
                
    return {"nodes": nodes, "edges": edges}

# Serve the static SPA index page
@app.get("/")
def read_root():
    return FileResponse(os.path.join(static_dir, "index.html"))

# Mount remaining static assets (js, css)
app.mount("/static", StaticFiles(directory=static_dir), name="static")
