#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# index_to_vespa.py
from __future__ import annotations
import os, json, sqlite3, unicodedata, argparse
from typing import Optional, List
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from urllib.parse import quote
from tqdm import tqdm

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

# --- Optional embedder ------------------------------------------------------
if USE_EMBEDDER:
    try:
        from sentence_transformers import SentenceTransformer
        _embedder = SentenceTransformer(EMBEDDER_MODEL)
        try:
            # silence HF warning about future default flip
            _embedder.tokenizer.clean_up_tokenization_spaces = False
        except Exception:
            pass
        EMBED_DIM = len(_embedder.encode("test"))
        if EMBED_DIM != 384:
            raise ValueError(f"Schema expects 384 dims, but model outputs {EMBED_DIM}. "
                             f"Either change schema or model.")
    except Exception as e:
        raise RuntimeError(f"Failed to init embedder: {e}")

def compute_embedding(text: str) -> list[float]:
    if not USE_EMBEDDER:
        raise RuntimeError("Embedding disabled; set USE_EMBEDDER=True or replace this function.")
    return _embedder.encode(text, normalize_embeddings=False).tolist()

# --- HTTP client with retries ----------------------------------------------
def make_session(max_retries: int = 5, backoff: float = 0.5) -> requests.Session:
    s = requests.Session()
    retry = Retry(
        total=max_retries,
        backoff_factor=backoff,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset(["GET", "POST", "DELETE"]),
        raise_on_status=False,
        respect_retry_after_header=True,
    )
    adapter = HTTPAdapter(max_retries=retry, pool_connections=100, pool_maxsize=100)
    s.mount("http://", adapter)
    s.mount("https://", adapter)
    s.headers.update({"Content-Type": "application/json"})
    return s

SESSION = make_session()

# --- Document API helpers ---------------------------------------------------
def put_doc(doc_id: str, fields: dict) -> bool:
    url = f"{VESPA_ENDPOINT}/document/v1/{NAMESPACE}/{DOC_TYPE}/docid/{quote(doc_id, safe='')}"
    r = SESSION.post(url, data=json.dumps({"fields": fields}), timeout=10)
    if not r.ok:
        try:
            err = r.json()
        except Exception:
            err = r.text
        print(f"[PUT-ERR] id={doc_id} status={r.status_code} msg={err}")
    return r.ok

def delete_doc(doc_id: str) -> bool:
    url = f"{VESPA_ENDPOINT}/document/v1/{NAMESPACE}/{DOC_TYPE}/docid/{quote(doc_id, safe='')}"
    r = SESSION.delete(url, timeout=10)
    if not r.ok:
        try:
            err = r.json()
        except Exception:
            err = r.text
        print(f"[DEL-ERR] id={doc_id} status={r.status_code} msg={err}")
    return r.ok

def delete_all_documents_fast() -> None:
    """Bulk delete all docs of this type via Document API selection=TRUE."""
    url = f"{VESPA_ENDPOINT}/document/v1/{NAMESPACE}/{DOC_TYPE}/docid/"
    params = {"selection": "true", "cluster": VESPA_CLUSTER}
    r = SESSION.delete(url, params=params, timeout=120)
    if r.ok:
        print("[WIPE] Bulk delete accepted:", r.text)
    else:
        try:
            print("[WIPE-ERR]", r.status_code, r.json())
        except Exception:
            print("[WIPE-ERR]", r.status_code, r.text)

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
    params = {
        "yql": f"select * from {DOC_TYPE} where userQuery()",
        "query": text,
        "hits": limit,
        "timeout": "5s",
        "ranking": "default",
    }
    r = SESSION.get(f"{VESPA_ENDPOINT}/search/", params=params, timeout=15)
    if not r.ok:
        try:
            print("[SEARCH-ERR]", r.status_code, r.json())
        except Exception:
            print("[SEARCH-ERR]", r.status_code, r.text)
        r.raise_for_status()
    _print_hits(r.json())

def _tensor_spec(vec: List[float]) -> str:
    # Vespa tensor literal string: tensor<float>(d0[384]):[...]
    return "tensor<float>(d0[384]):[" + ",".join(f"{x:.6g}" for x in vec) + "]"

def search_embedding(text: str, k: int = 100, limit: int = 10,
                     prefer_rank_profile: str = "vector", exact: bool = False) -> None:
    qvec = compute_embedding(text)

    def _tensor_spec(vec):
        return "tensor<float>(d0[384]):[" + ",".join(f"{x:.6g}" for x in vec) + "]"

    ann_opts = "approximate:false," if exact else ""
    yql = (
        f"select * from {DOC_TYPE} where "
        f"([{{{ann_opts}targetHits:{k}}}]nearestNeighbor(embedding, qemb))"
    )

    body = {
        "yql": yql,
        "hits": limit,
        "timeout": "5s",
        "ranking.features.query(qemb)": _tensor_spec(qvec)
    }
    # Try preferred rank profile first, then fallback
    for prof in ([prefer_rank_profile] if prefer_rank_profile else []) + [None]:
        if prof:
            body["ranking.profile"] = prof
        else:
            body.pop("ranking.profile", None)

        r = SESSION.post(f"{VESPA_ENDPOINT}/search/", json=body, timeout=30)
        if r.ok:
            _print_hits(r.json())
            return
        # print server error to see the actual reason
        try:
            print("[ANN-ERR]", r.status_code, r.json())
        except Exception:
            print("[ANN-ERR]", r.status_code, r.text)

    r.raise_for_status()

    
def search_hybrid(text: str, k: int = 100, limit: int = 10, exact: bool = False) -> None:
    """Hybrid search combining full-text (BM25) and ANN on embeddings.

    Uses rank-profile 'hybrid' defined in schema which blends normalized BM25
    with vector closeness. Recall is the union of text and ANN matches.
    """
    qvec = compute_embedding(text)

    ann_opts = "approximate:false," if exact else ""
    yql = (
        f"select * from {DOC_TYPE} where "
        f"(userQuery() or ([{{{ann_opts}targetHits:{k}}}]nearestNeighbor(embedding, qemb)))"
    )

    body = {
        "yql": yql,
        "query": text,
        "hits": limit,
        "timeout": "5s",
        "ranking.profile": "hybrid",
        "ranking.features.query(qemb)": _tensor_spec(qvec),
    }

    r = SESSION.post(f"{VESPA_ENDPOINT}/search/", json=body, timeout=30)
    if not r.ok:
        try:
            print("[HYB-ERR]", r.status_code, r.json())
        except Exception:
            print("[HYB-ERR]", r.status_code, r.text)
        r.raise_for_status()
    _print_hits(r.json())

def run_yql(yql: str, limit: int = 10, query_text: Optional[str] = None) -> None:
    params = {"yql": yql, "hits": limit, "timeout": "5s"}
    if query_text is not None:
        params["query"] = query_text  # used if yql includes userQuery()
    r = SESSION.get(f"{VESPA_ENDPOINT}/search/", params=params, timeout=20)
    if not r.ok:
        try:
            print("[YQL-ERR]", r.status_code, r.json())
        except Exception:
            print("[YQL-ERR]", r.status_code, r.text)
        r.raise_for_status()
    _print_hits(r.json())

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
    USE_EMBEDDER = False
    args = parse_args()

    if args.delete_all:
        print(f"[WIPE] Deleting all documents of {NAMESPACE}:{DOC_TYPE} via selection DELETE")
        #delete_all_documents_fast()
        return

    if args.search_text:
        search_fulltext(args.search_text, limit=args.limit)
        return

    if args.search_embed:
        USE_EMBEDDER = True  # ensure embedder is used
        search_embedding(args.search_embed, k=args.k, limit=args.limit)
        return

    if args.search_hybrid:
        USE_EMBEDDER = True  # ensure embedder is used
        search_hybrid(args.search_hybrid, k=args.k, limit=args.limit, exact=args.ann_exact)
        return

    if args.yql:
        run_yql(args.yql, limit=args.limit, query_text=args.yql_query)
        return

    if args.wipe_before_feed:
        print(f"[WIPE] Deleting all documents of {NAMESPACE}:{DOC_TYPE} via selection DELETE")
        #delete_all_documents_fast()

    feed_all()

if __name__ == "__main__":
    main()
