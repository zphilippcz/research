#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import os
from typing import Literal, Optional

from fastapi import FastAPI, Query, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import uvicorn

from py_vespa import (
    VESPA_ENDPOINT,
    DOC_TYPE,
    _tensor_spec,
    compute_embedding,
    SESSION,
    search_fulltext as _search_fulltext_cli,
)

app = FastAPI(title="Vespa Search Server", version="0.1.0")

# Mount static files and templates
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")


def _perform_fulltext(query_text: str, limit: int, lat: Optional[float] = None, lon: Optional[float] = None, radius: Optional[float] = None) -> dict:
    print(f"Fulltext search: q='{query_text}', limit={limit}, lat={lat}, lon={lon}, radius={radius}")
    
    # Základní YQL
    yql = f"select * from {DOC_TYPE} where userQuery()"
    
    # Přidáme GPS filtr, pokud jsou parametry
    if lat is not None and lon is not None and radius is not None:
        # Převod km na stupně (přibližně 1 stupeň = 111 km)
        radius_degrees = radius / 111.0
        yql = f"select * from {DOC_TYPE} where userQuery() and geo within circle({lat}, {lon}, {radius_degrees})"
    
    print(f"Fulltext YQL: {yql}")
    
    params = {
        "yql": yql,
        "query": query_text,
        "hits": limit,
        "timeout": "5s",
        "ranking": "default",
    }
    
    try:
        r = SESSION.get(f"{VESPA_ENDPOINT}/search/", params=params, timeout=15)
        if not r.ok:
            try:
                err = r.json()
            except Exception:
                err = r.text
            print(f"Fulltext search failed: {r.status_code} - {err}")
            # Fallback na jednodušší dotaz bez GPS
            if lat is not None and lon is not None and radius is not None:
                print("Trying fulltext fallback without GPS filter...")
                fallback_params = {
                    "yql": f"select * from {DOC_TYPE} where userQuery()",
                    "query": query_text,
                    "hits": limit,
                    "timeout": "5s",
                    "ranking": "default",
                }
                r = SESSION.get(f"{VESPA_ENDPOINT}/search/", params=fallback_params, timeout=15)
                if not r.ok:
                    raise HTTPException(status_code=r.status_code, detail={"error": r.text})
            else:
                raise HTTPException(status_code=r.status_code, detail={"error": err})
        
        return r.json()
    except Exception as e:
        print(f"Fulltext search exception: {e}")
        raise HTTPException(status_code=500, detail={"error": str(e)})


def _perform_embedding(query_text: str, k: int, limit: int, exact: bool, lat: Optional[float] = None, lon: Optional[float] = None, radius: Optional[float] = None) -> dict:
    print(f"Embedding search: q='{query_text}', k={k}, limit={limit}, exact={exact}, lat={lat}, lon={lon}, radius={radius}")
    qvec = compute_embedding(query_text)
    ann_opts = "approximate:false," if exact else ""
    
    # Základní YQL
    yql = f"select * from {DOC_TYPE} where ([{{{ann_opts}targetHits:{k}}}]nearestNeighbor(embedding, qemb))"
    
    # Přidáme GPS filtr, pokud jsou parametry
    if lat is not None and lon is not None and radius is not None:
        radius_degrees = radius / 111.0
        yql = f"select * from {DOC_TYPE} where ([{{{ann_opts}targetHits:{k}}}]nearestNeighbor(embedding, qemb)) and geo within circle({lat}, {lon}, {radius_degrees})"
    
    print(f"Embedding YQL: {yql}")
    
    body = {
        "yql": yql,
        "hits": limit,
        "timeout": "5s",
        "ranking.profile": "vector",
        "ranking.features.query(qemb)": _tensor_spec(qvec),
    }
    
    try:
        r = SESSION.post(f"{VESPA_ENDPOINT}/search/", json=body, timeout=30)
        if not r.ok:
            try:
                err = r.json()
            except Exception:
                err = r.text
            print(f"Embedding search failed: {r.status_code} - {err}")
            # Fallback na jednodušší dotaz bez GPS
            if lat is not None and lon is not None and radius is not None:
                print("Trying embedding fallback without GPS filter...")
                fallback_body = {
                    "yql": f"select * from {DOC_TYPE} where ([{{{ann_opts}targetHits:{k}}}]nearestNeighbor(embedding, qemb))",
                    "hits": limit,
                    "timeout": "5s",
                    "ranking.profile": "vector",
                    "ranking.features.query(qemb)": _tensor_spec(qvec),
                }
                r = SESSION.post(f"{VESPA_ENDPOINT}/search/", json=fallback_body, timeout=30)
                if not r.ok:
                    raise HTTPException(status_code=r.status_code, detail={"error": r.text})
            else:
                raise HTTPException(status_code=r.status_code, detail={"error": err})
        
        return r.json()
    except Exception as e:
        print(f"Embedding search exception: {e}")
        raise HTTPException(status_code=500, detail={"error": str(e)})


def _perform_hybrid(query_text: str, k: int, limit: int, exact: bool, lat: Optional[float] = None, lon: Optional[float] = None, radius: Optional[float] = None) -> dict:
    print(f"Hybrid search: q='{query_text}', k={k}, limit={limit}, lat={lat}, lon={lon}, radius={radius}")
    qvec = compute_embedding(query_text)
    ann_opts = "approximate:false," if exact else ""
    
    # Vytvoříme dva separátní dotazy pro identifikaci zdroje (bez GPS filtru)
    # 1. Textový dotaz
    yql_text = f"select * from sources * where userQuery()"
    
    body_text = {
        "yql": yql_text,
        "query": query_text,
        "hits": k * 2,  # Více hitů pro lepší pokrytí
        "timeout": "5s",
        "ranking": "default",
    }
    
    # 2. Vektorový dotaz
    yql_vector = f"select * from sources * where ([{{{ann_opts}targetHits:{k}}}]nearestNeighbor(embedding, qemb))"
    
    body_vector = {
        "yql": yql_vector,
        "hits": k * 2,
        "timeout": "5s",
        "ranking": "vector",
        "ranking.features.query(qemb)": _tensor_spec(qvec),
    }
    
    print(f"Text YQL: {yql_text}")
    print(f"Vector YQL: {yql_vector}")
    
    # Spustíme oba dotazy paralelně
    import asyncio
    import concurrent.futures
    
    def run_text_search():
        try:
            r = SESSION.post(f"{VESPA_ENDPOINT}/search/", json=body_text, timeout=30)
            if not r.ok:
                print(f"Text search failed: {r.status_code} - {r.text}")
                return {"root": {"children": []}}  # Prázdný výsledek místo chyby
            return r.json()
        except Exception as e:
            print(f"Text search exception: {e}")
            return {"root": {"children": []}}
    
    def run_vector_search():
        try:
            r = SESSION.post(f"{VESPA_ENDPOINT}/search/", json=body_vector, timeout=30)
            if not r.ok:
                print(f"Vector search failed: {r.status_code} - {r.text}")
                return {"root": {"children": []}}  # Prázdný výsledek místo chyby
            return r.json()
        except Exception as e:
            print(f"Vector search exception: {e}")
            return {"root": {"children": []}}
    
    with concurrent.futures.ThreadPoolExecutor() as executor:
        future_text = executor.submit(run_text_search)
        future_vector = executor.submit(run_vector_search)
        
        text_results = future_text.result()
        vector_results = future_vector.result()
    
    # Získáme ID dokumentů z každého zdroje
    text_ids = set()
    vector_ids = set()
    
    for hit in text_results.get("root", {}).get("children", []):
        text_ids.add(hit.get("id", ""))
    
    for hit in vector_results.get("root", {}).get("children", []):
        vector_ids.add(hit.get("id", ""))
    
    print(f"Text results: {len(text_ids)} documents")
    print(f"Vector results: {len(vector_ids)} documents")
    print(f"Text IDs sample: {list(text_ids)[:3] if text_ids else 'None'}")
    print(f"Vector IDs sample: {list(vector_ids)[:3] if vector_ids else 'None'}")
    
    # Spustíme hybrid dotaz pro finální výsledky
    yql_hybrid = (
        f"select * from sources * where ("
        f"([{{{ann_opts}targetHits:{k}}}]nearestNeighbor(embedding, qemb))"
        f" OR "
        f"userQuery()"
        f")"
    )
    if lat is not None and lon is not None and radius is not None:
        radius_degrees = radius / 111.0
        yql_hybrid = (
            f"select * from sources * where ("
            f"([{{{ann_opts}targetHits:{k}}}]nearestNeighbor(embedding, qemb))"
            f" OR "
            f"userQuery()"
            f") and geo within circle({lat}, {lon}, {radius_degrees})"
        )
    body_hybrid = {
        "yql": yql_hybrid,
        "query": query_text,
        "hits": limit,
        "timeout": "5s",
        "ranking": "hybrid",
        "ranking.features.query(qemb)": _tensor_spec(qvec),
    }
    
    try:
        r = SESSION.post(f"{VESPA_ENDPOINT}/search/", json=body_hybrid, timeout=30)
        if not r.ok:
            try:
                err = r.json()
            except Exception:
                err = r.text
            print(f"Hybrid search failed: {r.status_code} - {err}")
            # Fallback na jednodušší dotaz bez GPS
            if lat is not None and lon is not None and radius is not None:
                print("Trying fallback without GPS filter...")
                body_hybrid_fallback = {
                    "yql": f"select * from sources * where (([{{{ann_opts}targetHits:{k}}}]nearestNeighbor(embedding, qemb)) OR userQuery())",
                    "query": query_text,
                    "hits": limit,
                    "timeout": "5s",
                    "ranking": "hybrid",
                    "ranking.features.query(qemb)": _tensor_spec(qvec),
                }
                r = SESSION.post(f"{VESPA_ENDPOINT}/search/", json=body_hybrid_fallback, timeout=30)
                if not r.ok:
                    raise HTTPException(status_code=r.status_code, detail={"error": r.text})
            else:
                raise HTTPException(status_code=r.status_code, detail={"error": err})
        
        hybrid_results = r.json()
    except Exception as e:
        print(f"Hybrid search exception: {e}")
        raise HTTPException(status_code=500, detail={"error": str(e)})
    
    # Přidáme informaci o zdroji ke každému výsledku
    for hit in hybrid_results.get("root", {}).get("children", []):
        doc_id = hit.get("id", "")
        
        # Určíme zdroj - stejná logika pro GPS i běžné vyhledávání
        if doc_id in text_ids and doc_id in vector_ids:
            source = "both"
        elif doc_id in text_ids:
            source = "text"
        elif doc_id in vector_ids:
            source = "vector"
        else:
            source = "unknown"
        
        # Přidáme informaci o zdroji do fields
        if "fields" not in hit:
            hit["fields"] = {}
        hit["fields"]["_source"] = source
        
        # Debug log
        print(f"Doc ID: {doc_id}, Source: {source}, Text IDs: {doc_id in text_ids}, Vector IDs: {doc_id in vector_ids}")
    
    return hybrid_results


@app.get("/", response_class=HTMLResponse)
def index():
    return templates.TemplateResponse("index.html", {"request": {}})


@app.get("/search/fulltext")
def api_search_fulltext(
    q: str = Query(..., min_length=1),
    limit: int = Query(10, ge=1, le=1000),
    lat: Optional[float] = Query(None, description="Latitude"),
    lon: Optional[float] = Query(None, description="Longitude"),
    radius: Optional[float] = Query(None, description="Radius in km"),
):
    return JSONResponse(_perform_fulltext(q, limit, lat, lon, radius))


@app.get("/search/embedding")
def api_search_embedding(
    q: str = Query(..., min_length=1),
    limit: int = Query(10, ge=1, le=1000),
    k: int = Query(100, ge=1, le=10000),
    exact: Optional[bool] = Query(False),
    lat: Optional[float] = Query(None, description="Latitude"),
    lon: Optional[float] = Query(None, description="Longitude"),
    radius: Optional[float] = Query(None, description="Radius in km"),
):
    return JSONResponse(_perform_embedding(q, k=k, limit=limit, exact=bool(exact), lat=lat, lon=lon, radius=radius))


@app.get("/search/hybrid")
def api_search_hybrid(
    q: str = Query(..., min_length=1),
    limit: int = Query(10, ge=1, le=1000),
    k: int = Query(100, ge=1, le=10000),
    exact: Optional[bool] = Query(False),
    lat: Optional[float] = Query(None, description="Latitude"),
    lon: Optional[float] = Query(None, description="Longitude"),
    radius: Optional[float] = Query(None, description="Radius in km"),
):
    return JSONResponse(_perform_hybrid(q, k=k, limit=limit, exact=bool(exact), lat=lat, lon=lon, radius=radius))


@app.get("/diagnostics")
def diagnostics():
    """Basic diagnostics to help when no results are returned."""
    # Try multiple approaches to count documents
    info = {
        "vespa_endpoint": VESPA_ENDPOINT, 
        "doc_type": DOC_TYPE,
        "namespace": "mycompany"  # Add namespace info
    }
    
    # Method 1: Direct count query
    yql1 = f"select count() as num from {DOC_TYPE} where true;"
    r1 = SESSION.get(f"{VESPA_ENDPOINT}/search/", params={"yql": yql1, "hits": 0, "timeout": "5s"}, timeout=10)
    
    if r1.ok:
        try:
            data = r1.json()
            # Check for totalCount in root.fields (Vespa count response format)
            root_fields = (data or {}).get("root", {}).get("fields", {})
            if "totalCount" in root_fields:
                info["doc_count"] = root_fields["totalCount"]
                info["method"] = "direct_count"
            else:
                # Fallback to looking for num field in children
                fields = ((data or {}).get("root", {}).get("children", []) or [{}])[0].get("fields", {})
                info["doc_count"] = fields.get("num", 0)
                info["method"] = "direct_count_fallback"
            info["response"] = data
        except Exception as e:
            info["doc_count"] = None
            info["error"] = f"Parse error: {e}"
            info["raw"] = r1.text
    else:
        # Method 2: Try with sources
        yql2 = f"select count() as num from sources * where true;"
        r2 = SESSION.get(f"{VESPA_ENDPOINT}/search/", params={"yql": yql2, "hits": 0, "timeout": "5s"}, timeout=10)
        
        if r2.ok:
            try:
                data = r2.json()
                # Check for totalCount in root.fields (Vespa count response format)
                root_fields = (data or {}).get("root", {}).get("fields", {})
                if "totalCount" in root_fields:
                    info["doc_count"] = root_fields["totalCount"]
                    info["method"] = "sources_count"
                else:
                    # Fallback to looking for num field in children
                    fields = ((data or {}).get("root", {}).get("children", []) or [{}])[0].get("fields", {})
                    info["doc_count"] = fields.get("num", 0)
                    info["method"] = "sources_count_fallback"
                info["response"] = data
            except Exception as e:
                info["doc_count"] = None
                info["error"] = f"Parse error: {e}"
                info["raw"] = r2.text
        else:
            # Method 3: Try to get a sample document
            yql3 = f"select * from {DOC_TYPE} where true limit 1;"
            r3 = SESSION.get(f"{VESPA_ENDPOINT}/search/", params={"yql": yql3, "hits": 1, "timeout": "5s"}, timeout=10)
            
            if r3.ok:
                try:
                    data = r3.json()
                    hits = (data or {}).get("root", {}).get("children", []) or []
                    info["doc_count"] = "unknown_but_docs_exist" if hits else 0
                    info["method"] = "sample_doc"
                    info["sample_hit"] = hits[0] if hits else None
                    info["response"] = data
                except Exception as e:
                    info["doc_count"] = None
                    info["error"] = f"Parse error: {e}"
                    info["raw"] = r3.text
            else:
                # Method 4: Check if Vespa is responding at all
                try:
                    health_r = SESSION.get(f"{VESPA_ENDPOINT}/ApplicationStatus", timeout=5)
                    info["vespa_health"] = health_r.status_code
                    if health_r.ok:
                        info["vespa_health_data"] = health_r.json()
                except Exception as e:
                    info["vespa_health_error"] = str(e)
                
                try:
                    info["error"] = r3.json()
                except Exception:
                    info["error"] = r3.text
                info["doc_count"] = None
                info["method"] = "failed"
    
    return JSONResponse(info)


@app.get("/test-doc")
def test_doc():
    """Test direct document access via Document API."""
    # Try to get a document directly via Document API
    test_doc_id = "test123"
    url = f"{VESPA_ENDPOINT}/document/v1/mycompany/deal/docid/{test_doc_id}"
    
    info = {
        "test_doc_id": test_doc_id,
        "url": url,
        "vespa_endpoint": VESPA_ENDPOINT
    }
    
    try:
        r = SESSION.get(url, timeout=10)
        info["status_code"] = r.status_code
        if r.ok:
            info["found"] = True
            info["doc"] = r.json()
        else:
            info["found"] = False
            try:
                info["error"] = r.json()
            except Exception:
                info["error"] = r.text
    except Exception as e:
        info["exception"] = str(e)
    
    return JSONResponse(info)


def main():
    host = os.getenv("HOST", "127.0.0.1")
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run("server:app", host=host, port=port, reload=True)


if __name__ == "__main__":
    main()


