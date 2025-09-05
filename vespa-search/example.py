#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Example usage of Vespa Client Library

This script demonstrates basic library functions.
"""

import logging
from vespa_client import create_vespa_client, Document

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def main():
    print("=== Vespa Client Library - Example Usage ===\n")
    
    # Create client
    print("1. Creating Vespa client...")
    client = create_vespa_client(
        endpoint="http://localhost:8080",
        namespace="mycompany",
        doc_type="deal",
        enable_embeddings=True
    )
    
    # Health check
    print("2. Checking Vespa health...")
    if client.health_check():
        print("✅ Vespa is running correctly!")
    else:
        print("❌ Vespa is not responding - make sure it's running")
        return
    
    # Insert test documents
    print("\n3. Inserting test documents...")
    
    test_documents = [
        {
            "id": "deal-1",
            "fields": {
                "deal_id": "deal-1",
                "document": "Great offer on iPhone 15 with 20% discount",
                "category_id": "electronics",
                "price": 19999.0,
                "is_active": True
            }
        },
        {
            "id": "deal-2", 
            "fields": {
                "deal_id": "deal-2",
                "document": "Restaurant in Prague center - lunch for 150 CZK",
                "category_id": "restaurants",
                "price": 150.0,
                "is_active": True,
                "geo": {"lat": 50.0755, "lng": 14.4378}
            }
        },
        {
            "id": "deal-3",
            "fields": {
                "deal_id": "deal-3", 
                "document": "Summer vacation in Greece - all inclusive",
                "category_id": "travel",
                "price": 25000.0,
                "is_active": True
            }
        }
    ]
    
    # Insert documents with embeddings
    for doc_data in test_documents:
        doc_id = doc_data["id"]
        fields = doc_data["fields"]
        
        # Create embedding for text
        text = fields["document"]
        embedding = client.embedder.encode(text)
        fields["embedding"] = embedding
        
        if client.put_document(doc_id, fields):
            print(f"✅ Document {doc_id} inserted")
        else:
            print(f"❌ Error inserting document {doc_id}")
    
    # Text search
    print("\n4. Text search...")
    results = client.search_text("iPhone", limit=5)
    print(f"Found {len(results.results)} results for 'iPhone':")
    for result in results.results:
        print(f"  - {result.doc_id}: {result.score:.4f}")
        print(f"    Text: {result.fields.get('document', '')[:60]}...")
    
    # Vector search
    print("\n5. Vector search...")
    results = client.search_vector("vacation", k=10, limit=5)
    print(f"Found {len(results.results)} results for 'vacation':")
    for result in results.results:
        print(f"  - {result.doc_id}: {result.score:.4f}")
        print(f"    Text: {result.fields.get('document', '')[:60]}...")
    
    # Hybrid search
    print("\n6. Hybrid search...")
    results = client.search_hybrid("offer", k=10, limit=5)
    print(f"Found {len(results.results)} results for 'offer':")
    for result in results.results:
        print(f"  - {result.doc_id}: {result.score:.4f}")
        print(f"    Text: {result.fields.get('document', '')[:60]}...")
    
    # Filtering by price
    print("\n7. Filtering by price...")
    yql = "select * from deal where price < 1000 and is_active = true"
    results = client.search_yql(yql, limit=5)
    print(f"Found {len(results.results)} cheap offers:")
    for result in results.results:
        price = result.fields.get('price', 0)
        print(f"  - {result.doc_id}: {price} CZK")
        print(f"    Text: {result.fields.get('document', '')[:60]}...")
    
    # Filtering by category
    print("\n8. Filtering by category...")
    yql = "select * from deal where category_id contains 'electronics'"
    results = client.search_yql(yql, limit=5)
    print(f"Found {len(results.results)} electronics offers:")
    for result in results.results:
        print(f"  - {result.doc_id}: {result.fields.get('category_id')}")
        print(f"    Text: {result.fields.get('document', '')[:60]}...")
    
    # Get specific document
    print("\n9. Getting specific document...")
    doc = client.get_document("deal-1")
    if doc:
        print(f"Document deal-1:")
        print(f"  ID: {doc.get('id')}")
        print(f"  Fields: {doc.get('fields', {})}")
    else:
        print("Document deal-1 not found")
    
    # Statistics
    print("\n10. Getting statistics...")
    stats = client.get_statistics()
    if stats:
        print("✅ Statistics obtained")
        # You can iterate through stats for specific metrics
    else:
        print("❌ Failed to get statistics")
    
    print("\n=== Example completed ===")
    print("To clean up test data you can run:")
    print("client.delete_all_documents()")

if __name__ == "__main__":
    main()
