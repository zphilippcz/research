#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Testy pro Vespa Client Library

Tento soubor obsahuje základní testy pro knihovnu.
"""

import unittest
from unittest.mock import Mock, patch
import json
from vespa_client import (
    VespaClient, 
    VespaConfig, 
    SearchResult, 
    SearchResponse, 
    Document,
    create_vespa_client
)


class TestVespaConfig(unittest.TestCase):
    """Testy pro VespaConfig."""
    
    def test_default_config(self):
        """Test výchozí konfigurace."""
        config = VespaConfig()
        self.assertEqual(config.endpoint, "http://localhost:8080")
        self.assertEqual(config.namespace, "mycompany")
        self.assertEqual(config.doc_type, "deal")
        self.assertEqual(config.timeout, 30)
    
    def test_custom_config(self):
        """Test vlastní konfigurace."""
        config = VespaConfig(
            endpoint="http://test:8080",
            namespace="test",
            doc_type="test",
            timeout=60
        )
        self.assertEqual(config.endpoint, "http://test:8080")
        self.assertEqual(config.namespace, "test")
        self.assertEqual(config.doc_type, "test")
        self.assertEqual(config.timeout, 60)


class TestSearchResult(unittest.TestCase):
    """Testy pro SearchResult."""
    
    def test_search_result_creation(self):
        """Test vytvoření SearchResult."""
        result = SearchResult(
            doc_id="test-123",
            score=0.85,
            fields={"title": "Test Document"}
        )
        self.assertEqual(result.doc_id, "test-123")
        self.assertEqual(result.score, 0.85)
        self.assertEqual(result.fields, {"title": "Test Document"})
        self.assertEqual(result.relevance, 0.85)  # Default relevance
    
    def test_search_result_with_relevance(self):
        """Test SearchResult s explicitní relevance."""
        result = SearchResult(
            doc_id="test-123",
            score=0.85,
            fields={"title": "Test Document"},
            relevance=0.90
        )
        self.assertEqual(result.relevance, 0.90)


class TestSearchResponse(unittest.TestCase):
    """Testy pro SearchResponse."""
    
    def test_search_response_creation(self):
        """Test vytvoření SearchResponse."""
        results = [
            SearchResult("doc-1", 0.9, {"title": "Doc 1"}),
            SearchResult("doc-2", 0.8, {"title": "Doc 2"})
        ]
        response = SearchResponse(
            results=results,
            total_hits=2,
            coverage={"coverage": 100},
            timing={"queryTime": 0.1}
        )
        self.assertEqual(len(response.results), 2)
        self.assertEqual(response.total_hits, 2)
        self.assertEqual(response.coverage, {"coverage": 100})
        self.assertEqual(response.timing, {"queryTime": 0.1})
        self.assertEqual(response.errors, [])


class TestDocument(unittest.TestCase):
    """Testy pro Document."""
    
    def test_document_creation(self):
        """Test vytvoření Document."""
        doc = Document(
            doc_id="test-123",
            fields={"title": "Test", "content": "Content"}
        )
        self.assertEqual(doc.doc_id, "test-123")
        self.assertEqual(doc.fields, {"title": "Test", "content": "Content"})
        self.assertEqual(doc.namespace, "mycompany")  # Default
        self.assertEqual(doc.doc_type, "deal")  # Default


class TestVespaClient(unittest.TestCase):
    """Testy pro VespaClient."""
    
    def setUp(self):
        """Nastavení před každým testem."""
        self.config = VespaConfig(
            endpoint="http://test:8080",
            namespace="test",
            doc_type="test"
        )
        self.client = VespaClient(self.config)
    
    def test_client_creation(self):
        """Test vytvoření klienta."""
        self.assertEqual(self.client.config.endpoint, "http://test:8080")
        self.assertEqual(self.client.config.namespace, "test")
        self.assertEqual(self.client.config.doc_type, "test")
        self.assertIsNone(self.client.embedder)
    
    @patch('vespa_client.requests.Session')
    def test_health_check_success(self, mock_session):
        """Test úspěšné kontroly zdraví."""
        mock_response = Mock()
        mock_response.ok = True
        mock_session.return_value.get.return_value = mock_response
        
        result = self.client.health_check()
        self.assertTrue(result)
    
    @patch('vespa_client.requests.Session')
    def test_health_check_failure(self, mock_session):
        """Test neúspěšné kontroly zdraví."""
        mock_session.return_value.get.side_effect = Exception("Connection error")
        
        result = self.client.health_check()
        self.assertFalse(result)
    
    def test_build_doc_url(self):
        """Test vytvoření URL pro dokument."""
        url = self.client._build_doc_url("test-123")
        expected = "http://test:8080/document/v1/test/test/docid/test-123"
        self.assertEqual(url, expected)
    
    def test_build_search_url(self):
        """Test vytvoření URL pro vyhledávání."""
        url = self.client._build_search_url()
        expected = "http://test:8080/search/"
        self.assertEqual(url, expected)
    
    def test_tensor_spec(self):
        """Test vytvoření tensor specifikace."""
        vector = [0.1, 0.2, 0.3]
        spec = self.client._tensor_spec(vector)
        expected = "tensor<float>(d0[384]):[0.1,0.2,0.3]"
        self.assertEqual(spec, expected)
    
    def test_parse_search_response(self):
        """Test parsování vyhledávací odpovědi."""
        response_data = {
            "root": {
                "children": [
                    {
                        "id": "test::doc-1",
                        "relevance": 0.9,
                        "fields": {"title": "Doc 1"}
                    },
                    {
                        "id": "test::doc-2", 
                        "relevance": 0.8,
                        "fields": {"title": "Doc 2"}
                    }
                ],
                "fields": {"totalCount": 2}
            }
        }
        
        result = self.client._parse_search_response(response_data)
        
        self.assertEqual(len(result.results), 2)
        self.assertEqual(result.total_hits, 2)
        self.assertEqual(result.results[0].doc_id, "doc-1")
        self.assertEqual(result.results[0].score, 0.9)
        self.assertEqual(result.results[1].doc_id, "doc-2")
        self.assertEqual(result.results[1].score, 0.8)


class TestCreateVespaClient(unittest.TestCase):
    """Testy pro create_vespa_client funkci."""
    
    def test_create_basic_client(self):
        """Test vytvoření základního klienta."""
        client = create_vespa_client(
            endpoint="http://test:8080",
            namespace="test",
            doc_type="test"
        )
        self.assertEqual(client.config.endpoint, "http://test:8080")
        self.assertEqual(client.config.namespace, "test")
        self.assertEqual(client.config.doc_type, "test")
        self.assertIsNone(client.embedder)
    
    @patch('vespa_client.VespaEmbedder')
    def test_create_client_with_embeddings(self, mock_embedder):
        """Test vytvoření klienta s embeddings."""
        client = create_vespa_client(
            endpoint="http://test:8080",
            namespace="test",
            doc_type="test",
            enable_embeddings=True
        )
        self.assertIsNotNone(client.embedder)


if __name__ == "__main__":
    unittest.main()
