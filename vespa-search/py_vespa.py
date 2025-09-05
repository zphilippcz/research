#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# index_to_vespa.py
from __future__ import annotations
import os, json, sqlite3, unicodedata, argparse
from typing import Optional, List
from tqdm import tqdm

# Import new library
from vespa_client import create_vespa_client, Document

# --- Config -----------------------------------------------------------------
DB_PATH = os.getenv("DB_PATH", "/Users/zphilipp/git/research/dealsdb/deals_db1.db")
VESPA_ENDPOINT = os.getenv("VESPA_ENDPOINT", "http://localhost:8080")
NAMESPACE = os.getenv("VESPA_NAMESPACE", "mycompany")
DOC_TYPE = os.getenv("VESPA_DOC_TYPE", "deal")
BATCH_LOG_EVERY = 1000
SEARCH_PAGE_SIZE = int(os.getenv("SEARCH_PAGE_SIZE", "1000"))
VESPA_CLUSTER = os.getenv("VESPA_CLUSTER", "content")  # for bulk delete selection

# Embeddings (384 dims)
USE_EMBEDDER = True
EMBEDDER_MODEL = "all-MiniLM-L6-v2"  # 384-dim

# Create Vespa client
vespa_client = create_vespa_client(
    endpoint=VESPA_ENDPOINT,
    namespace=NAMESPACE,
    doc_type=DOC_TYPE,
    enable_embeddings=USE_EMBEDDER,
    embedding_model=EMBEDDER_MODEL
)

def compute_embedding(text: str) -> list[float]:
    """Create embedding for text using Vespa client."""
    if not USE_EMBEDDER:
        raise RuntimeError("Embedding disabled; set USE_EMBEDDER=True or replace this function.")
    return vespa_client.embedder.encode(text, normalize_embeddings=False)

# --- Document API helpers ---------------------------------------------------
def put_doc(doc_id: str, fields: dict) -> bool:
    """Insert document into Vespa using new library."""
    return vespa_client.put_document(doc_id, fields)

def delete_doc(doc_id: str) -> bool:
    """Delete document from Vespa using new library."""
    return vespa_client.delete_document(doc_id)

def delete_all_documents_fast() -> None:
    """Delete all documents using new library."""
    success = vespa_client.delete_all_documents()
    if success:
        print("[WIPE] Bulk delete successful")
    else:
        print("[WIPE-ERR] Bulk delete failed")

# --- Helpers ----------------------------------------------------------------
def normalize_text(s: str) -> str:
    if s is None:
        return ""
    s = unicodedata.normalize("NFC", str(s))
    s = "".join(ch for ch in s if ch.isprintable())
    return " ".join(s.split())

def fetch_tree(item_id: Optional[int], cursor: sqlite3.Cursor):
    cursor.execute("SELECT parent_id, name FROM category WHERE id = ?", (item_id,))
    item = cursor.fetchone()
    if not item:
        return None
    return {'value': item[1], 'parent_id': item[0]}

def category_value(id: Optional[int], cursor: sqlite3.Cursor) -> str:
    data = fetch_tree(id, cursor)
    category_string = ""
    while data is not None:
        data = fetch_tree(data["parent_id"], cursor)
        try:
            category_string = data["value"] + " / " + category_string
        except TypeError:
            break
    return category_string[:-2]

# --- Feed -------------------------------------------------------------------
def feed_all():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    sql = """
        SELECT
            d.deal_uuid,
            COALESCE(MAX(d.title_general), '') || '. ' ||
            COALESCE(MAX(d.highlights), '') || '. ' ||
            COALESCE(GROUP_CONCAT(o.title, ','), '') || '. ' ||
            COALESCE(MAX(m.name), '') AS text,
            d.customer_category_id,
            l.lat, l.lon
        FROM deals d
        LEFT JOIN merchant m ON (d.merchant_id=m.id)
        LEFT JOIN options  o ON (o.deal_id=d.id)
        LEFT JOIN deal_location l ON (d.deal_uuid=l.deal_uuid)
        -- where d.id = 151
        GROUP BY d.deal_uuid
    """
    cursor.execute(sql)
    rows = cursor.fetchall()

    ok = fail = 0
    for i, (deal_uuid, text, cat_id, lat, lon) in enumerate(tqdm(rows, unit="doc")):
        # if not cat_id: continue  # uncomment to skip no-category deals

        cat = category_value(cat_id, cursor)
        base_text = normalize_text(text)
        document_text = normalize_text(f"{base_text}. {cat}.") if cat else base_text

        fields = {
            "deal_id":     str(deal_uuid),
            "document":    document_text,
            "category_id": cat or normalize_text(str(cat_id)),
            # "price":     0.0,
            # "is_active": True,
        }

        if lat is not None and lon is not None:
            fields["geo"] = {"lat": float(lat), "lng": float(lon)}

        try:
            emb = compute_embedding(document_text)
            fields["embedding"] = emb
        except Exception as e:
            print(f"[EMB-ERR] id={deal_uuid}: {e}")

        #print(f"[FEED] {i+1:>5} id={deal_uuid} cat='{cat}' text='{document_text[:120]}…' 'lat={lat}' 'lon={lon}'")
        if put_doc(str(deal_uuid), fields):
            ok += 1
        else:
            fail += 1

        if (i + 1) % BATCH_LOG_EVERY == 0:
            print(f"[progress] sent={i+1} ok={ok} fail={fail}")

    conn.close()
    total = ok + fail
    print(f"Done. total={total} ok={ok} fail={fail}")

# --- Search helpers ---------------------------------------------------------
def _print_hits(data: dict, max_snippet: int = 120) -> None:
    root = data.get("root", {})
    hits = root.get("children", []) or []
    print(f"[hits] {len(hits)}")
    for i, h in enumerate(hits, 1):
        hid = h.get("id")
        score = h.get("relevance")
        fields = h.get("fields", {})
        deal_id = fields.get("deal_id") or (hid.split("::", 1)[1] if hid and "::" in hid else None)
        doc = (fields.get("document") or "")[:max_snippet].replace("\n", " ")
        cat = fields.get("category_id")
        print(f"{i:>3}. score={score:.6f} id={deal_id} cat={cat}  text='{doc}…'")

def search_fulltext(text: str, limit: int = 10) -> None:
    """Text search using new library."""
    results = vespa_client.search_text(text, limit=limit)
    
    # Convert to original format for compatibility
    data = {
        "root": {
            "children": [
                {
                    "id": f"{NAMESPACE}::{result.doc_id}",
                    "relevance": result.score,
                    "fields": result.fields
                }
                for result in results.results
            ]
        }
    }
    
    _print_hits(data)

def search_embedding(text: str, k: int = 100, limit: int = 10,
                     prefer_rank_profile: str = "vector", exact: bool = False) -> None:
    """Vector search using new library."""
    try:
        results = vespa_client.search_vector(text, k=k, limit=limit, exact=exact)
        
        # Convert to original format for compatibility
        data = {
            "root": {
                "children": [
                    {
                        "id": f"{NAMESPACE}::{result.doc_id}",
                        "relevance": result.score,
                        "fields": result.fields
                    }
                    for result in results.results
                ]
            }
        }
        
        _print_hits(data)
    except Exception as e:
        print(f"[ANN-ERR] {e}")

def search_hybrid(text: str, k: int = 100, limit: int = 10, exact: bool = False) -> None:
    """Hybrid search using new library."""
    try:
        results = vespa_client.search_hybrid(text, k=k, limit=limit, exact=exact)
        
        # Convert to original format for compatibility
        data = {
            "root": {
                "children": [
                    {
                        "id": f"{NAMESPACE}::{result.doc_id}",
                        "relevance": result.score,
                        "fields": result.fields
                    }
                    for result in results.results
                ]
            }
        }
        
        _print_hits(data)
    except Exception as e:
        print(f"[HYB-ERR] {e}")

def run_yql(yql: str, limit: int = 10, query_text: Optional[str] = None) -> None:
    """Execute YQL query using new library."""
    try:
        results = vespa_client.search_yql(yql, limit=limit, query_text=query_text)
        
        # Convert to original format for compatibility
        data = {
            "root": {
                "children": [
                    {
                        "id": f"{NAMESPACE}::{result.doc_id}",
                        "relevance": result.score,
                        "fields": result.fields
                    }
                    for result in results.results
                ]
            }
        }
        
        _print_hits(data)
    except Exception as e:
        print(f"[YQL-ERR] {e}")

# --- Main -------------------------------------------------------------------
def parse_args():
    p = argparse.ArgumentParser()
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--delete-all", action="store_true",
                      help="Delete all documents of this doc type and exit.")
    mode.add_argument("--wipe-before-feed", action="store_true",
                      help="Delete all documents before feeding new data, then feed.")
    mode.add_argument("--search-text", type=str, help="Full-text query over 'document'.")
    mode.add_argument("--search-embed", type=str, help="ANN query using 'embedding'.")
    mode.add_argument("--search-hybrid", type=str, help="Hybrid query: text + ANN.")
    mode.add_argument("--yql", type=str, help="Raw YQL query (use with --yql-query if it contains userQuery()).")

    p.add_argument("--limit", type=int, default=10, help="Number of hits to return.")
    p.add_argument("--k", type=int, default=100, help="targetHits for nearestNeighbor (ANN).")
    p.add_argument("--yql-query", type=str, default=None,
                   help="Optional 'query' param value used by YQL with userQuery().")
    p.add_argument("--ann-exact", action="store_true",
               help="Use approximate:false (brute-force) ANN for debugging.")

    return p.parse_args()

def main():
    args = parse_args()

    if args.delete_all:
        print(f"[WIPE] Deleting all documents of {NAMESPACE}:{DOC_TYPE} via selection DELETE")
        delete_all_documents_fast()
        return

    if args.search_text:
        search_fulltext(args.search_text, limit=args.limit)
        return

    if args.search_embed:
        search_embedding(args.search_embed, k=args.k, limit=args.limit, exact=args.ann_exact)
        return

    if args.search_hybrid:
        search_hybrid(args.search_hybrid, k=args.k, limit=args.limit, exact=args.ann_exact)
        return

    if args.yql:
        run_yql(args.yql, limit=args.limit, query_text=args.yql_query)
        return

    if args.wipe_before_feed:
        print(f"[WIPE] Deleting all documents of {NAMESPACE}:{DOC_TYPE} via selection DELETE")
        delete_all_documents_fast()

    feed_all()

if __name__ == "__main__":
    main()
