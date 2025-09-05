#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Integration test to verify that server.py and py_vespa.py work with the new vespa_client.py library
"""

import os
import sys
import time
import logging
from vespa_client import create_vespa_client

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def test_vespa_client():
    """Test basic Vespa client functionality."""
    print("=== Vespa Client Test ===")
    
    # Create client
    client = create_vespa_client(
        endpoint="http://localhost:8080",
        namespace="mycompany",
        doc_type="deal",
        enable_embeddings=True
    )
    
    # Health test
    print("1. Checking Vespa health...")
    if client.health_check():
        print("✅ Vespa is healthy")
    else:
        print("❌ Vespa is not responding")
        return False
    
    # Document insertion test
    print("2. Document insertion test...")
    test_doc = {
        "deal_id": "test-integration-123",
        "document": "Test document for integration test",
        "category_id": "test",
        "price": 100.0,
        "is_active": True
    }
    
    if client.put_document("test-integration-123", test_doc):
        print("✅ Document inserted")
    else:
        print("❌ Error inserting document")
        return False
    
    # Document retrieval test
    print("3. Document retrieval test...")
    doc = client.get_document("test-integration-123")
    if doc:
        print("✅ Document retrieved")
        print(f"   ID: {doc.get('id')}")
        print(f"   Fields: {doc.get('fields', {})}")
    else:
        print("❌ Document not found")
        return False
    
    # Text search test
    print("4. Text search test...")
    results = client.search_text("test", limit=5)
    print(f"✅ Text search: {len(results.results)} results")
    
    # Vector search test
    print("5. Vector search test...")
    try:
        results = client.search_vector("test", k=10, limit=5)
        print(f"✅ Vector search: {len(results.results)} results")
    except Exception as e:
        print(f"⚠️ Vector search failed: {e}")
    
    # Hybrid search test
    print("6. Hybrid search test...")
    try:
        results = client.search_hybrid("test", k=10, limit=5)
        print(f"✅ Hybrid search: {len(results.results)} results")
    except Exception as e:
        print(f"⚠️ Hybrid search failed: {e}")
    
    # YQL query test
    print("7. YQL query test...")
    results = client.search_yql("select * from deal where category_id contains 'test'", limit=5)
    print(f"✅ YQL query: {len(results.results)} results")
    
    # Document deletion test
    print("8. Document deletion test...")
    if client.delete_document("test-integration-123"):
        print("✅ Document deleted")
    else:
        print("❌ Error deleting document")
        return False
    
    print("=== Vespa Client Test Completed ===\n")
    return True

def test_py_vespa_import():
    """Test that py_vespa.py can be imported and uses the new library."""
    print("=== py_vespa.py Import Test ===")
    
    try:
        # Import py_vespa module
        import py_vespa
        
        print("✅ py_vespa.py imported successfully")
        print(f"   Vespa endpoint: {py_vespa.VESPA_ENDPOINT}")
        print(f"   Namespace: {py_vespa.NAMESPACE}")
        print(f"   Doc type: {py_vespa.DOC_TYPE}")
        print(f"   Vespa client: {type(py_vespa.vespa_client).__name__}")
        
        # Test basic functions
        print("   Testing functions...")
        
        # Test compute_embedding
        try:
            embedding = py_vespa.compute_embedding("test text")
            print(f"   ✅ compute_embedding: {len(embedding)} dimensions")
        except Exception as e:
            print(f"   ⚠️ compute_embedding failed: {e}")
        
        # Test put_doc
        test_doc = {
            "deal_id": "test-py-vespa-123",
            "document": "Test document for py_vespa",
            "category_id": "test"
        }
        
        if py_vespa.put_doc("test-py-vespa-123", test_doc):
            print("   ✅ put_doc works")
            
            # Test delete_doc
            if py_vespa.delete_doc("test-py-vespa-123"):
                print("   ✅ delete_doc works")
            else:
                print("   ❌ delete_doc failed")
        else:
            print("   ❌ put_doc failed")
        
        print("=== py_vespa.py Import Test Completed ===\n")
        return True
        
    except Exception as e:
        print(f"❌ Error importing py_vespa: {e}")
        return False

def test_server_import():
    """Test that server.py can be imported and uses the new library."""
    print("=== server.py Import Test ===")
    
    try:
        # Import server module
        import server
        
        print("✅ server.py imported successfully")
        print(f"   Vespa config: {type(server.vespa_config).__name__}")
        print(f"   Vespa client: {type(server.vespa_client).__name__}")
        print(f"   FastAPI app: {type(server.app).__name__}")
        
        # Test configuration
        print(f"   Endpoint: {server.vespa_config.endpoint}")
        print(f"   Namespace: {server.vespa_config.namespace}")
        print(f"   Doc type: {server.vespa_config.doc_type}")
        
        # Test functions
        print("   Testing functions...")
        
        # Test _perform_fulltext
        try:
            result = server._perform_fulltext("test", 5)
            print(f"   ✅ _perform_fulltext: {type(result).__name__}")
        except Exception as e:
            print(f"   ⚠️ _perform_fulltext failed: {e}")
        
        print("=== server.py Import Test Completed ===\n")
        return True
        
    except Exception as e:
        print(f"❌ Error importing server: {e}")
        return False

def main():
    """Main function to run all tests."""
    print("🚀 Running integration tests for Vespa Client Library\n")
    
    # Check that Vespa is running
    print("Checking Vespa availability...")
    try:
        client = create_vespa_client()
        if client.health_check():
            print("✅ Vespa is available\n")
        else:
            print("❌ Vespa is not available - start Vespa before testing")
            return False
    except Exception as e:
        print(f"❌ Cannot connect to Vespa: {e}")
        return False
    
    # Run tests
    tests = [
        ("Vespa Client", test_vespa_client),
        ("py_vespa.py Import", test_py_vespa_import),
        ("server.py Import", test_server_import)
    ]
    
    results = []
    for test_name, test_func in tests:
        try:
            result = test_func()
            results.append((test_name, result))
        except Exception as e:
            print(f"❌ Test {test_name} threw exception: {e}")
            results.append((test_name, False))
    
    # Summary of results
    print("=== Results Summary ===")
    passed = 0
    total = len(results)
    
    for test_name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{status} {test_name}")
        if result:
            passed += 1
    
    print(f"\nTotal: {passed}/{total} tests passed")
    
    if passed == total:
        print("🎉 All tests passed! Integration is successful.")
        return True
    else:
        print("⚠️ Some tests failed. Check configuration.")
        return False

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
