#!/usr/bin/env python3
import json
import psycopg2
from psycopg2.extras import Json
import sys

def load_graph(json_path, db_config):
    # Read graph_data.json
    try:
        with open(json_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except Exception as e:
        print(f"Error reading JSON file {json_path}: {e}")
        sys.exit(1)

    nodes = data.get("nodes", [])
    edges = data.get("edges", [])

    print(f"Loaded {len(nodes)} nodes and {len(edges)} edges from {json_path}.")

    # Build a lookup of node contexts to infer edge contexts
    node_contexts = {node["id"]: node.get("contexts", []) for node in nodes}

    # Connect to PostgreSQL
    try:
        conn = psycopg2.connect(**db_config)
        cursor = conn.cursor()
    except Exception as e:
        print(f"Database connection failed: {e}")
        sys.exit(1)

    try:
        # 1. Upsert Nodes
        print("Upserting nodes...")
        for node in nodes:
            node_id = node["id"]
            name = node["name"]
            node_type = node["type"]
            metadata = node.get("metadata", [])
            contexts = node.get("contexts", [])

            cursor.execute(
                """
                INSERT INTO nodes (id, name, type, metadata, contexts)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (id)
                DO UPDATE SET
                    name = EXCLUDED.name,
                    type = EXCLUDED.type,
                    metadata = EXCLUDED.metadata,
                    contexts = EXCLUDED.contexts;
                """,
                (node_id, name, node_type, Json(metadata), Json(contexts))
            )

        # 2. Upsert Edges
        print("Upserting edges...")
        for edge in edges:
            source = edge["source"]
            target = edge["target"]
            edge_type = edge["type"]

            # Infer context
            context = None
            if edge_type == "membership":
                context = target
            else:
                # For introduction, check if source and target share a common context
                source_ctxs = node_contexts.get(source, [])
                target_ctxs = node_contexts.get(target, [])
                common_ctxs = [c for c in source_ctxs if c in target_ctxs]
                if common_ctxs:
                    context = common_ctxs[0]

            cursor.execute(
                """
                INSERT INTO edges (source, target, type, context)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (source, target, type)
                DO UPDATE SET
                    context = EXCLUDED.context;
                """,
                (source, target, edge_type, context)
            )

        # Commit transaction
        conn.commit()
        print("Database upload completed successfully!")

        # Fetch and print status
        cursor.execute("SELECT count(*) FROM nodes;")
        nodes_count = cursor.fetchone()[0]
        cursor.execute("SELECT count(*) FROM edges;")
        edges_count = cursor.fetchone()[0]
        print(f"Total rows in nodes table: {nodes_count}")
        print(f"Total rows in edges table: {edges_count}")

    except Exception as e:
        conn.rollback()
        print(f"An error occurred during database operations: {e}")
        sys.exit(1)
    finally:
        cursor.close()
        conn.close()

if __name__ == "__main__":
    db_credentials = {
        "host": "localhost",
        "port": 5432,
        "user": "eric",
        "password": "password123",
        "database": "keep_social_graph"
    }
    load_graph("graph_data.json", db_credentials)
