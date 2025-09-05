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

from vespa_client import create_vespa_client, VespaConfig
import math

def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate distance between two GPS coordinates in kilometers."""
    R = 6371  # Earth radius in km
    
    lat1_rad = math.radians(lat1)
    lon1_rad = math.radians(lon1)
    lat2_rad = math.radians(lat2)
    lon2_rad = math.radians(lon2)
    
    dlat = lat2_rad - lat1_rad
    dlon = lon2_rad - lon1_rad
    
    a = math.sin(dlat/2)**2 + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(dlon/2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
    
    return R * c

app = FastAPI(title="Vespa Search Server", version="0.1.0")

# Mount static files and templates
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# Create Vespa client
vespa_config = VespaConfig(
    endpoint=os.getenv("VESPA_ENDPOINT", "http://localhost:8080"),
    namespace=os.getenv("VESPA_NAMESPACE", "mycompany"),
    doc_type=os.getenv("VESPA_DOC_TYPE", "deal"),
    cluster=os.getenv("VESPA_CLUSTER", "content")
)

# Initialize client with embeddings
vespa_client = create_vespa_client(
    endpoint=vespa_config.endpoint,
    namespace=vespa_config.namespace,
    doc_type=vespa_config.doc_type,
    enable_embeddings=True,
    embedding_model=os.getenv("EMBEDDER_MODEL", "all-MiniLM-L6-v2")
)




def _perform_fulltext(query_text: str, limit: int, lat: Optional[float] = None, lon: Optional[float] = None, radius: Optional[float] = None) -> dict:
    print(f"Fulltext search: q='{query_text}', limit={limit}, lat={lat}, lon={lon}, radius={radius}")
    
    try:
        # Use vespa_client for search
        if lat is not None and lon is not None and radius is not None:
            # GPS filter - use post-processing approach
            print(f"Fulltext search with GPS post-processing: lat={lat}, lon={lon}, radius={radius}")
            results = vespa_client.search_text(query_text, limit=limit * 2)  # Get more results for filtering
            
            # Filter results by GPS distance
            filtered_results = []
            for result in results.results:
                geo = result.fields.get('geo', {})
                if 'lat' in geo and 'lng' in geo:
                    distance = haversine_distance(lat, lon, geo['lat'], geo['lng'])
                    if distance <= radius:
                        filtered_results.append(result)
                        if len(filtered_results) >= limit:
                            break
            
            # Create new SearchResponse with filtered results
            from vespa_client import SearchResponse, SearchResult
            filtered_response = SearchResponse(
                total_count=len(filtered_results),
                results=filtered_results[:limit]
            )
            results = filtered_response
        else:
            # Without GPS filter
            print(f"Fulltext search without GPS")
            results = vespa_client.search_text(query_text, limit=limit)
        
        # Convert to original response format
        response_data = {
            "root": {
                "children": [
                    {
                        "id": f"{vespa_config.namespace}::{result.doc_id}",
                        "relevance": result.score,
                        "fields": result.fields
                    }
                    for result in results.results
                ],
                "fields": {"totalCount": results.total_hits}
            }
        }
        
        if results.coverage:
            response_data["coverage"] = results.coverage
        if results.timing:
            response_data["timing"] = results.timing
        
        return response_data
        
    except Exception as e:
        print(f"Fulltext search exception: {e}")
        # Fallback to simpler query without GPS
        if lat is not None and lon is not None and radius is not None:
            print("Trying fulltext fallback without GPS filter...")
            try:
                results = vespa_client.search_text(query_text, limit=limit)
                response_data = {
                    "root": {
                        "children": [
                            {
                                "id": f"{vespa_config.namespace}::{result.doc_id}",
                                "relevance": result.score,
                                "fields": result.fields
                            }
                            for result in results.results
                        ],
                        "fields": {"totalCount": results.total_hits}
                    }
                }
                return response_data
            except Exception as fallback_e:
                print(f"Fallback also failed: {fallback_e}")
                raise HTTPException(status_code=500, detail={"error": str(fallback_e)})
        else:
            raise HTTPException(status_code=500, detail={"error": str(e)})


def _perform_embedding(query_text: str, k: int, limit: int, exact: bool, lat: Optional[float] = None, lon: Optional[float] = None, radius: Optional[float] = None) -> dict:
    print(f"Embedding search: q='{query_text}', k={k}, limit={limit}, exact={exact}, lat={lat}, lon={lon}, radius={radius}")
    
    try:
        # Use vespa_client for vector search
        if lat is not None and lon is not None and radius is not None:
            # GPS filter - use post-processing approach
            print(f"Embedding search with GPS post-processing: lat={lat}, lon={lon}, radius={radius}")
            
            # Use vector search without GPS filter and then filter
            results = vespa_client.search_vector(query_text, k=k, limit=limit * 2, exact=exact)  # Get more results for filtering
            
            # Filter results by GPS distance
            filtered_results = []
            for result in results.results:
                geo = result.fields.get('geo', {})
                if 'lat' in geo and 'lng' in geo:
                    distance = haversine_distance(lat, lon, geo['lat'], geo['lng'])
                    if distance <= radius:
                        filtered_results.append(result)
                        if len(filtered_results) >= limit:
                            break
            
            # Create new SearchResponse with filtered results
            from vespa_client import SearchResponse, SearchResult
            filtered_response = SearchResponse(
                total_hits=len(filtered_results),
                results=filtered_results[:limit]
            )
            results = filtered_response
        else:
            # Without GPS filter
            print(f"Embedding search without GPS")
            results = vespa_client.search_vector(query_text, k=k, limit=limit, exact=exact)
        
        # Convert to original response format
        response_data = {
            "root": {
                "children": [
                    {
                        "id": f"{vespa_config.namespace}::{result.doc_id}",
                        "relevance": result.score,
                        "fields": result.fields
                    }
                    for result in results.results
                ],
                "fields": {"totalCount": results.total_hits}
            }
        }
        
        if results.coverage:
            response_data["coverage"] = results.coverage
        if results.timing:
            response_data["timing"] = results.timing
        
        return response_data
        
    except Exception as e:
        print(f"Embedding search exception: {e}")
        # Fallback to simpler query without GPS
        if lat is not None and lon is not None and radius is not None:
            print("Trying embedding fallback without GPS filter...")
            try:
                results = vespa_client.search_vector(query_text, k=k, limit=limit, exact=exact)
                response_data = {
                    "root": {
                        "children": [
                            {
                                "id": f"{vespa_config.namespace}::{result.doc_id}",
                                "relevance": result.score,
                                "fields": result.fields
                            }
                            for result in results.results
                        ],
                        "fields": {"totalCount": results.total_hits}
                    }
                }
                return response_data
            except Exception as fallback_e:
                print(f"Fallback also failed: {fallback_e}")
                raise HTTPException(status_code=500, detail={"error": str(fallback_e)})
        else:
            raise HTTPException(status_code=500, detail={"error": str(e)})


def _perform_hybrid(query_text: str, k: int, limit: int, exact: bool, lat: Optional[float] = None, lon: Optional[float] = None, radius: Optional[float] = None) -> dict:
    print(f"Hybrid search: q='{query_text}', k={k}, limit={limit}, lat={lat}, lon={lon}, radius={radius}")
    
    # Create two separate queries for source identification (without GPS filter)
    # 1. Text query
    yql_text = f"select * from sources * where userQuery()"
    
    # 2. Vector query
    ann_opts = "approximate:false," if exact else ""
    yql_vector = f"select * from sources * where ([{{{ann_opts}targetHits:{k}}}]nearestNeighbor(embedding, qemb))"
    
    print(f"Text YQL: {yql_text}")
    print(f"Vector YQL: {yql_vector}")
    
    # Run both queries in parallel
    import asyncio
    import concurrent.futures
    
    def run_text_search():
        try:
            results = vespa_client.search_yql(yql_text, limit=k*2, query_text=query_text)
            return {
                "root": {
                    "children": [
                        {
                            "id": f"{vespa_config.namespace}::{result.doc_id}",
                            "relevance": result.score,
                            "fields": result.fields
                        }
                        for result in results.results
                    ]
                }
            }
        except Exception as e:
            print(f"Text search exception: {e}")
            return {"root": {"children": []}}
    
    def run_vector_search():
        try:
            results = vespa_client.search_yql(yql_vector, limit=k*2)
            return {
                "root": {
                    "children": [
                        {
                            "id": f"{vespa_config.namespace}::{result.doc_id}",
                            "relevance": result.score,
                            "fields": result.fields
                        }
                        for result in results.results
                    ]
                }
            }
        except Exception as e:
            print(f"Vector search exception: {e}")
            return {"root": {"children": []}}
    
    with concurrent.futures.ThreadPoolExecutor() as executor:
        future_text = executor.submit(run_text_search)
        future_vector = executor.submit(run_vector_search)
        
        text_results = future_text.result()
        vector_results = future_vector.result()
    
    # Get document IDs from each source
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
    
    # Run hybrid query for final results
    yql_hybrid = (
        f"select * from sources * where ("
        f"([{{{ann_opts}targetHits:{k}}}]nearestNeighbor(embedding, qemb))"
        f" OR "
        f"userQuery()"
        f")"
    )
    if lat is not None and lon is not None and radius is not None:
        # GPS filtr - použijeme post-processing přístup
        print(f"Hybrid search with GPS post-processing: lat={lat}, lon={lon}, radius={radius}")
        
        # Use hybrid search without GPS filter and then filter
        results = vespa_client.search_hybrid(query_text, k=k, limit=limit * 2, exact=exact)  # Get more results for filtering
        
        # Filtrujeme výsledky podle GPS vzdálenosti
        filtered_results = []
        for result in results.results:
            geo = result.fields.get('geo', {})
            if 'lat' in geo and 'lng' in geo:
                distance = haversine_distance(lat, lon, geo['lat'], geo['lng'])
                if distance <= radius:
                    filtered_results.append(result)
                    if len(filtered_results) >= limit:
                        break
        
        # Vytvoříme nový SearchResponse s filtrovanými výsledky
        from vespa_client import SearchResponse, SearchResult
        filtered_response = SearchResponse(
            total_hits=len(filtered_results),
            results=filtered_results[:limit]
        )
        results = filtered_response
    else:
        print(f"Hybrid search without GPS")
    
    try:
        results = vespa_client.search_hybrid(query_text, k=k, limit=limit, exact=exact)
        
        # Convert to original response format
        response_data = {
            "root": {
                "children": [
                    {
                        "id": f"{vespa_config.namespace}::{result.doc_id}",
                        "relevance": result.score,
                        "fields": result.fields
                    }
                    for result in results.results
                ],
                "fields": {"totalCount": results.total_hits}
            }
        }
        
        # For hybrid search we cannot precisely determine source, because Vespa combines results
        # Add source information to each result
        for hit in response_data.get("root", {}).get("children", []):
            # For hybrid search mark all results as "hybrid"
            if "fields" not in hit:
                hit["fields"] = {}
            hit["fields"]["_source"] = "hybrid"
        
        if results.coverage:
            response_data["coverage"] = results.coverage
        if results.timing:
            response_data["timing"] = results.timing
        
        return response_data
        
    except Exception as e:
        print(f"Hybrid search exception: {e}")
        # Fallback to simpler query without GPS
        if lat is not None and lon is not None and radius is not None:
            print("Trying fallback without GPS filter...")
            try:
                results = vespa_client.search_hybrid(query_text, k=k, limit=limit, exact=exact)
                response_data = {
                    "root": {
                        "children": [
                            {
                                "id": f"{vespa_config.namespace}::{result.doc_id}",
                                "relevance": result.score,
                                "fields": result.fields
                            }
                            for result in results.results
                        ],
                        "fields": {"totalCount": results.total_hits}
                    }
                }
                return response_data
            except Exception as fallback_e:
                print(f"Fallback also failed: {fallback_e}")
                raise HTTPException(status_code=500, detail={"error": str(fallback_e)})
        else:
            raise HTTPException(status_code=500, detail={"error": str(e)})


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
    info = {
        "vespa_endpoint": vespa_config.endpoint, 
        "doc_type": vespa_config.doc_type,
        "namespace": vespa_config.namespace
    }
    
    # Check Vespa health
    if vespa_client.health_check():
        info["vespa_health"] = "healthy"
    else:
        info["vespa_health"] = "unhealthy"
    
    # Document count
    try:
        yql = f"select count() as num from {vespa_config.doc_type} where true;"
        results = vespa_client.search_yql(yql, limit=0)
        info["doc_count"] = results.total_hits
        info["method"] = "direct_count"
    except Exception as e:
        try:
            # Fallback to sources
            yql = f"select count() as num from sources * where true;"
            results = vespa_client.search_yql(yql, limit=0)
            info["doc_count"] = results.total_hits
            info["method"] = "sources_count"
        except Exception as e2:
            try:
                # Fallback to document sample
                yql = f"select * from {vespa_config.doc_type} where true limit 1;"
                results = vespa_client.search_yql(yql, limit=1)
                info["doc_count"] = "unknown_but_docs_exist" if results.results else 0
                info["method"] = "sample_doc"
                if results.results:
                    info["sample_hit"] = results.results[0].fields
            except Exception as e3:
                info["doc_count"] = None
                info["error"] = f"All methods failed: {e}, {e2}, {e3}"
                info["method"] = "failed"
    
    return JSONResponse(info)


@app.get("/test-doc")
def test_doc():
    """Test direct document access via Document API."""
    test_doc_id = "test123"
    
    info = {
        "test_doc_id": test_doc_id,
        "vespa_endpoint": vespa_config.endpoint
    }
    
    try:
        doc = vespa_client.get_document(test_doc_id)
        if doc:
            info["found"] = True
            info["doc"] = doc
        else:
            info["found"] = False
            info["error"] = "Document not found"
    except Exception as e:
        info["exception"] = str(e)
    
    return JSONResponse(info)


def main():
    host = os.getenv("HOST", "127.0.0.1")
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run("server:app", host=host, port=port, reload=True)


if __name__ == "__main__":
    main()


