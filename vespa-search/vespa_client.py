#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Vespa Client Library for Python

A comprehensive client library for interacting with Vespa search engine.
Supports document operations, search queries, and vector embeddings.
"""

from __future__ import annotations
import os
import json
import time
from typing import Optional, List, Dict, Any, Union, Tuple
from dataclasses import dataclass, field
from urllib.parse import quote, urljoin
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import logging

# Optional dependencies
try:
    from sentence_transformers import SentenceTransformer
    SENTENCE_TRANSFORMERS_AVAILABLE = True
except ImportError:
    SENTENCE_TRANSFORMERS_AVAILABLE = False

logger = logging.getLogger(__name__)


@dataclass
class VespaConfig:
    """Configuration for Vespa client."""
    endpoint: str = "http://localhost:8080"
    namespace: str = "mycompany"
    doc_type: str = "deal"
    cluster: str = "content"
    timeout: int = 30
    max_retries: int = 5
    backoff_factor: float = 0.5
    pool_connections: int = 100
    pool_maxsize: int = 100


@dataclass
class SearchResult:
    """Represents a single search result."""
    doc_id: str
    score: float
    fields: Dict[str, Any]
    relevance: Optional[float] = None
    
    def __post_init__(self):
        if self.relevance is None:
            self.relevance = self.score


@dataclass
class SearchResponse:
    """Represents a search response."""
    results: List[SearchResult]
    total_hits: int
    coverage: Optional[Dict[str, Any]] = None
    timing: Optional[Dict[str, Any]] = None
    errors: List[str] = field(default_factory=list)


@dataclass
class Document:
    """Represents a Vespa document."""
    doc_id: str
    fields: Dict[str, Any]
    namespace: str = "mycompany"
    doc_type: str = "deal"


class VespaEmbedder:
    """Handles text embedding for vector search."""
    
    def __init__(self, model_name: str = "all-MiniLM-L6-v2", dimension: int = 384):
        if not SENTENCE_TRANSFORMERS_AVAILABLE:
            raise ImportError("sentence-transformers is required for embeddings. "
                            "Install with: pip install sentence-transformers")
        
        self.model_name = model_name
        self.dimension = dimension
        self._model = None
        self._load_model()
    
    def _load_model(self):
        """Load the embedding model."""
        try:
            self._model = SentenceTransformer(self.model_name)
            # Silence HF warning about future default flip
            try:
                self._model.tokenizer.clean_up_tokenization_spaces = False
            except Exception:
                pass
            
            # Verify dimension
            test_embedding = self._model.encode("test", normalize_embeddings=False)
            if len(test_embedding) != self.dimension:
                raise ValueError(f"Model outputs {len(test_embedding)} dimensions, "
                               f"but {self.dimension} expected")
            
            logger.info(f"Loaded embedding model: {self.model_name}")
        except Exception as e:
            raise RuntimeError(f"Failed to load embedding model: {e}")
    
    def encode(self, text: str, normalize: bool = False) -> List[float]:
        """Encode text to embedding vector."""
        if not self._model:
            raise RuntimeError("Embedding model not loaded")
        
        return self._model.encode(text, normalize_embeddings=normalize).tolist()
    
    def encode_batch(self, texts: List[str], normalize: bool = False) -> List[List[float]]:
        """Encode multiple texts to embedding vectors."""
        if not self._model:
            raise RuntimeError("Embedding model not loaded")
        
        return self._model.encode(texts, normalize_embeddings=normalize).tolist()


class VespaClient:
    """Main Vespa client for document operations and search."""
    
    def __init__(self, config: Optional[VespaConfig] = None):
        self.config = config or VespaConfig()
        self.session = self._create_session()
        self.embedder: Optional[VespaEmbedder] = None
    
    def _create_session(self) -> requests.Session:
        """Create HTTP session with retry logic."""
        session = requests.Session()
        retry = Retry(
            total=self.config.max_retries,
            backoff_factor=self.config.backoff_factor,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset(["GET", "POST", "DELETE", "PUT"]),
            raise_on_status=False,
            respect_retry_after_header=True,
        )
        adapter = HTTPAdapter(
            max_retries=retry,
            pool_connections=self.config.pool_connections,
            pool_maxsize=self.config.pool_maxsize
        )
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        session.headers.update({"Content-Type": "application/json"})
        return session
    
    def enable_embeddings(self, model_name: str = "all-MiniLM-L6-v2", dimension: int = 384):
        """Enable embedding support."""
        self.embedder = VespaEmbedder(model_name, dimension)
    
    def _build_doc_url(self, doc_id: str) -> str:
        """Build document URL."""
        safe_doc_id = quote(doc_id, safe='')
        return urljoin(
            self.config.endpoint,
            f"/document/v1/{self.config.namespace}/{self.config.doc_type}/docid/{safe_doc_id}"
        )
    
    def _build_search_url(self) -> str:
        """Build search URL."""
        return urljoin(self.config.endpoint, "/search/")
    
    def put_document(self, doc_id: str, fields: Dict[str, Any]) -> bool:
        """
        Put a document into Vespa.
        
        Args:
            doc_id: Document ID
            fields: Document fields
            
        Returns:
            True if successful, False otherwise
        """
        url = self._build_doc_url(doc_id)
        payload = {"fields": fields}
        
        try:
            response = self.session.post(
                url, 
                data=json.dumps(payload), 
                timeout=self.config.timeout
            )
            
            if not response.ok:
                logger.error(f"Failed to put document {doc_id}: {response.status_code} - {response.text}")
                return False
            
            logger.debug(f"Successfully put document {doc_id}")
            return True
            
        except Exception as e:
            logger.error(f"Error putting document {doc_id}: {e}")
            return False
    
    def get_document(self, doc_id: str) -> Optional[Dict[str, Any]]:
        """
        Get a document from Vespa.
        
        Args:
            doc_id: Document ID
            
        Returns:
            Document data or None if not found
        """
        url = self._build_doc_url(doc_id)
        
        try:
            response = self.session.get(url, timeout=self.config.timeout)
            
            if response.status_code == 404:
                return None
            
            if not response.ok:
                logger.error(f"Failed to get document {doc_id}: {response.status_code} - {response.text}")
                return None
            
            return response.json()
            
        except Exception as e:
            logger.error(f"Error getting document {doc_id}: {e}")
            return None
    
    def delete_document(self, doc_id: str) -> bool:
        """
        Delete a document from Vespa.
        
        Args:
            doc_id: Document ID
            
        Returns:
            True if successful, False otherwise
        """
        url = self._build_doc_url(doc_id)
        
        try:
            response = self.session.delete(url, timeout=self.config.timeout)
            
            if not response.ok:
                logger.error(f"Failed to delete document {doc_id}: {response.status_code} - {response.text}")
                return False
            
            logger.debug(f"Successfully deleted document {doc_id}")
            return True
            
        except Exception as e:
            logger.error(f"Error deleting document {doc_id}: {e}")
            return False
    
    def delete_all_documents(self) -> bool:
        """
        Delete all documents of the current document type.
        
        Returns:
            True if successful, False otherwise
        """
        url = self._build_doc_url("")
        params = {"selection": "true", "cluster": self.config.cluster}
        
        try:
            response = self.session.delete(url, params=params, timeout=120)
            
            if not response.ok:
                logger.error(f"Failed to delete all documents: {response.status_code} - {response.text}")
                return False
            
            logger.info("Successfully deleted all documents")
            return True
            
        except Exception as e:
            logger.error(f"Error deleting all documents: {e}")
            return False
    
    def _parse_search_response(self, response_data: Dict[str, Any]) -> SearchResponse:
        """Parse Vespa search response into SearchResponse object."""
        root = response_data.get("root", {})
        children = root.get("children", [])
        
        results = []
        for child in children:
            doc_id = child.get("id", "")
            if "::" in doc_id:
                doc_id = doc_id.split("::", 1)[1]
            
            result = SearchResult(
                doc_id=doc_id,
                score=child.get("relevance", 0.0),
                fields=child.get("fields", {}),
                relevance=child.get("relevance")
            )
            results.append(result)
        
        return SearchResponse(
            results=results,
            total_hits=root.get("fields", {}).get("totalCount", 0),
            coverage=response_data.get("coverage"),
            timing=response_data.get("timing")
        )
    
    def search_text(self, query: str, limit: int = 10, 
                   rank_profile: str = "default") -> SearchResponse:
        """
        Perform full-text search.
        
        Args:
            query: Search query
            limit: Maximum number of results
            rank_profile: Ranking profile to use
            
        Returns:
            SearchResponse object
        """
        params = {
            "yql": f"select * from {self.config.doc_type} where userQuery()",
            "query": query,
            "hits": limit,
            "timeout": "5s",
            "ranking.profile": rank_profile
        }
        
        try:
            response = self.session.get(
                self._build_search_url(),
                params=params,
                timeout=self.config.timeout
            )
            
            if not response.ok:
                logger.error(f"Search failed: {response.status_code} - {response.text}")
                return SearchResponse(results=[], total_hits=0, errors=[response.text])
            
            return self._parse_search_response(response.json())
            
        except Exception as e:
            logger.error(f"Error during text search: {e}")
            return SearchResponse(results=[], total_hits=0, errors=[str(e)])
    
    def search_vector(self, query: str, k: int = 100, limit: int = 10,
                     rank_profile: str = "vector", exact: bool = False) -> SearchResponse:
        """
        Perform vector search using embeddings.
        
        Args:
            query: Text query to embed
            k: Target hits for nearest neighbor search
            limit: Maximum number of results to return
            rank_profile: Ranking profile to use
            exact: Use exact search instead of approximate
            
        Returns:
            SearchResponse object
        """
        if not self.embedder:
            raise RuntimeError("Embeddings not enabled. Call enable_embeddings() first.")
        
        # Encode query
        query_vector = self.embedder.encode(query)
        
        # Build YQL
        ann_opts = "approximate:false," if exact else ""
        yql = (
            f"select * from {self.config.doc_type} where "
            f"([{{{ann_opts}targetHits:{k}}}]nearestNeighbor(embedding, qemb))"
        )
        
        # Build request body
        body = {
            "yql": yql,
            "hits": limit,
            "timeout": "5s",
            "ranking.profile": rank_profile,
            "ranking.features.query(qemb)": self._tensor_spec(query_vector)
        }
        
        try:
            response = self.session.post(
                self._build_search_url(),
                json=body,
                timeout=self.config.timeout
            )
            
            if not response.ok:
                logger.error(f"Vector search failed: {response.status_code} - {response.text}")
                return SearchResponse(results=[], total_hits=0, errors=[response.text])
            
            return self._parse_search_response(response.json())
            
        except Exception as e:
            logger.error(f"Error during vector search: {e}")
            return SearchResponse(results=[], total_hits=0, errors=[str(e)])
    
    def search_hybrid(self, query: str, k: int = 100, limit: int = 10,
                     rank_profile: str = "hybrid", exact: bool = False) -> SearchResponse:
        """
        Perform hybrid search combining text and vector search.
        
        Args:
            query: Search query
            k: Target hits for nearest neighbor search
            limit: Maximum number of results to return
            rank_profile: Ranking profile to use
            exact: Use exact vector search instead of approximate
            
        Returns:
            SearchResponse object
        """
        if not self.embedder:
            raise RuntimeError("Embeddings not enabled. Call enable_embeddings() first.")
        
        # Encode query
        query_vector = self.embedder.encode(query)
        
        # Build YQL
        ann_opts = "approximate:false," if exact else ""
        yql = (
            f"select * from {self.config.doc_type} where "
            f"(userQuery() or ([{{{ann_opts}targetHits:{k}}}]nearestNeighbor(embedding, qemb)))"
        )
        
        # Build request body
        body = {
            "yql": yql,
            "query": query,
            "hits": limit,
            "timeout": "5s",
            "ranking.profile": rank_profile,
            "ranking.features.query(qemb)": self._tensor_spec(query_vector)
        }
        
        try:
            response = self.session.post(
                self._build_search_url(),
                json=body,
                timeout=self.config.timeout
            )
            
            if not response.ok:
                logger.error(f"Hybrid search failed: {response.status_code} - {response.text}")
                return SearchResponse(results=[], total_hits=0, errors=[response.text])
            
            return self._parse_search_response(response.json())
            
        except Exception as e:
            logger.error(f"Error during hybrid search: {e}")
            return SearchResponse(results=[], total_hits=0, errors=[str(e)])
    
    def search_yql(self, yql: str, limit: int = 10, 
                  query_text: Optional[str] = None) -> SearchResponse:
        """
        Execute raw YQL query.
        
        Args:
            yql: YQL query string
            limit: Maximum number of results
            query_text: Optional query text for userQuery()
            
        Returns:
            SearchResponse object
        """
        params = {
            "yql": yql,
            "hits": limit,
            "timeout": "5s"
        }
        
        if query_text is not None:
            params["query"] = query_text
        
        try:
            response = self.session.get(
                self._build_search_url(),
                params=params,
                timeout=self.config.timeout
            )
            
            if not response.ok:
                logger.error(f"YQL search failed: {response.status_code} - {response.text}")
                return SearchResponse(results=[], total_hits=0, errors=[response.text])
            
            return self._parse_search_response(response.json())
            
        except Exception as e:
            logger.error(f"Error during YQL search: {e}")
            return SearchResponse(results=[], total_hits=0, errors=[str(e)])
    
    def _tensor_spec(self, vector: List[float]) -> str:
        """Convert vector to Vespa tensor specification."""
        return "tensor<float>(d0[384]):[" + ",".join(f"{x:.6g}" for x in vector) + "]"
    
    def batch_put_documents(self, documents: List[Document], 
                           batch_size: int = 100) -> Tuple[int, int]:
        """
        Put multiple documents in batches.
        
        Args:
            documents: List of Document objects
            batch_size: Number of documents per batch
            
        Returns:
            Tuple of (successful, failed) counts
        """
        successful = 0
        failed = 0
        
        for i in range(0, len(documents), batch_size):
            batch = documents[i:i + batch_size]
            
            for doc in batch:
                if self.put_document(doc.doc_id, doc.fields):
                    successful += 1
                else:
                    failed += 1
            
            logger.info(f"Batch progress: {i + len(batch)}/{len(documents)} "
                       f"(successful: {successful}, failed: {failed})")
        
        return successful, failed
    
    def health_check(self) -> bool:
        """
        Check if Vespa is healthy.
        
        Returns:
            True if healthy, False otherwise
        """
        try:
            response = self.session.get(
                urljoin(self.config.endpoint, "/ApplicationStatus"),
                timeout=10
            )
            return response.ok
        except Exception as e:
            logger.error(f"Health check failed: {e}")
            return False
    
    def get_statistics(self) -> Optional[Dict[str, Any]]:
        """
        Get Vespa statistics.
        
        Returns:
            Statistics data or None if failed
        """
        try:
            response = self.session.get(
                urljoin(self.config.endpoint, "/metrics/v2/values"),
                timeout=10
            )
            
            if response.ok:
                return response.json()
            else:
                logger.error(f"Failed to get statistics: {response.status_code}")
                return None
                
        except Exception as e:
            logger.error(f"Error getting statistics: {e}")
            return None


# Convenience functions
def create_vespa_client(endpoint: str = "http://localhost:8080",
                       namespace: str = "mycompany",
                       doc_type: str = "deal",
                       enable_embeddings: bool = False,
                       embedding_model: str = "all-MiniLM-L6-v2") -> VespaClient:
    """
    Create a Vespa client with common configuration.
    
    Args:
        endpoint: Vespa endpoint URL
        namespace: Document namespace
        doc_type: Document type
        enable_embeddings: Whether to enable embedding support
        embedding_model: Embedding model name
        
    Returns:
        Configured VespaClient instance
    """
    config = VespaConfig(
        endpoint=endpoint,
        namespace=namespace,
        doc_type=doc_type
    )
    
    client = VespaClient(config)
    
    if enable_embeddings:
        client.enable_embeddings(embedding_model)
    
    return client


# Example usage and documentation
if __name__ == "__main__":
    # Example usage
    logging.basicConfig(level=logging.INFO)
    
    # Create client
    client = create_vespa_client(
        endpoint="http://localhost:8080",
        namespace="mycompany",
        doc_type="deal",
        enable_embeddings=True
    )
    
    # Check health
    if client.health_check():
        print("Vespa is healthy!")
    else:
        print("Vespa is not responding")
        exit(1)
    
    # Example document
    doc_fields = {
        "deal_id": "example-123",
        "document": "This is an example deal document",
        "category_id": "electronics",
        "price": 99.99,
        "is_active": True
    }
    
    # Put document
    if client.put_document("example-123", doc_fields):
        print("Document put successfully")
    
    # Search
    results = client.search_text("example deal")
    print(f"Found {len(results.results)} results")
    
    for result in results.results:
        print(f"- {result.doc_id}: {result.score}")
