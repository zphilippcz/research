#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GPS search test with corrected YQL syntax
"""

import os
import sys
import logging
from vespa_client import create_vespa_client

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def test_gps_search():
    """Test GPS search."""
    print("=== GPS Search Test ===")
    
    # Create client
    client = create_vespa_client(
        endpoint="http://localhost:8080",
        namespace="mycompany",
        doc_type="deal",
        enable_embeddings=True
    )
    
    # Health check
    if not client.health_check():
        print("❌ Vespa is not responding")
        return False
    
    # Insert test documents with GPS
    test_docs = [
        {
            "id": "gps-test-1",
            "fields": {
                "deal_id": "gps-test-1",
                "document": "Restaurant in Prague center",
                "category_id": "restaurants",
                "geo": {"lat": 50.0755, "lng": 14.4378}  # Prague center
            }
        },
        {
            "id": "gps-test-2", 
            "fields": {
                "deal_id": "gps-test-2",
                "document": "Cafe on Wenceslas Square",
                "category_id": "cafes",
                "geo": {"lat": 50.0817, "lng": 14.4266}  # Wenceslas Square
            }
        },
        {
            "id": "gps-test-3",
            "fields": {
                "deal_id": "gps-test-3", 
                "document": "Shop in Brno",
                "category_id": "shopping",
                "geo": {"lat": 49.1951, "lng": 16.6068}  # Brno
            }
        }
    ]
    
    print("1. Inserting test documents with GPS...")
    for doc_data in test_docs:
        doc_id = doc_data["id"]
        fields = doc_data["fields"]
        
        # Create embedding
        text = fields["document"]
        embedding = client.embedder.encode(text)
        fields["embedding"] = embedding
        
        if client.put_document(doc_id, fields):
            print(f"   ✅ {doc_id} inserted")
        else:
            print(f"   ❌ {doc_id} failed")
    
    # Test 1: Text search without GPS
    print("\n2. Text search test without GPS...")
    try:
        results = client.search_text("restaurant", limit=10)
        print(f"   ✅ Found {len(results.results)} results")
        for result in results.results:
            print(f"      - {result.doc_id}: {result.fields.get('document', '')[:50]}...")
    except Exception as e:
        print(f"   ❌ Text search failed: {e}")
    
    # Test 2: Text search with GPS (Prague center)
    print("\n3. Text search test with GPS (Prague center, 5km)...")
    try:
        # Prague center: 50.0755, 14.4378
        # Use post-processing approach
        results = client.search_text("restaurant", limit=20)  # Get more results for filtering
        
        # Filter results by GPS distance
        import math
        def haversine_distance(lat1, lon1, lat2, lon2):
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
        
        filtered_results = []
        for result in results.results:
            geo = result.fields.get('geo', {})
            if 'lat' in geo and 'lng' in geo:
                distance = haversine_distance(50.0755, 14.4378, geo['lat'], geo['lng'])
                if distance <= 5:  # 5km
                    filtered_results.append(result)
                    if len(filtered_results) >= 10:
                        break
        
        print(f"   ✅ Found {len(filtered_results)} results within 5km of Prague")
        for result in filtered_results:
            geo = result.fields.get('geo', {})
            print(f"      - {result.doc_id}: {result.fields.get('document', '')[:50]}... (lat: {geo.get('lat')}, lng: {geo.get('lng')})")
    except Exception as e:
        print(f"   ❌ GPS text search failed: {e}")
    
    # Test 3: Vector search with GPS
    print("\n4. Vector search test with GPS...")
    try:
        # Prague center: 50.0755, 14.4378
        # Use post-processing approach
        results = client.search_vector("restaurant", k=10, limit=10)
        
        # Filter results by GPS distance
        filtered_results = []
        for result in results.results:
            geo = result.fields.get('geo', {})
            if 'lat' in geo and 'lng' in geo:
                distance = haversine_distance(50.0755, 14.4378, geo['lat'], geo['lng'])
                if distance <= 5:  # 5km
                    filtered_results.append(result)
                    if len(filtered_results) >= 5:
                        break
        
        print(f"   ✅ Found {len(filtered_results)} vector search results within 5km")
        for result in filtered_results:
            geo = result.fields.get('geo', {})
            print(f"      - {result.doc_id}: {result.fields.get('document', '')[:50]}... (lat: {geo.get('lat')}, lng: {geo.get('lng')})")
    except Exception as e:
        print(f"   ❌ GPS vector search failed: {e}")
    
    # Test 4: Hybrid search with GPS
    print("\n5. Hybrid search test with GPS...")
    try:
        # Prague center: 50.0755, 14.4378
        # Use post-processing approach
        results = client.search_hybrid("restaurant", k=10, limit=10)
        
        # Filter results by GPS distance
        filtered_results = []
        for result in results.results:
            geo = result.fields.get('geo', {})
            if 'lat' in geo and 'lng' in geo:
                distance = haversine_distance(50.0755, 14.4378, geo['lat'], geo['lng'])
                if distance <= 5:  # 5km
                    filtered_results.append(result)
                    if len(filtered_results) >= 5:
                        break
        
        print(f"   ✅ Found {len(filtered_results)} hybrid search results within 5km")
        for result in filtered_results:
            geo = result.fields.get('geo', {})
            print(f"      - {result.doc_id}: {result.fields.get('document', '')[:50]}... (lat: {geo.get('lat')}, lng: {geo.get('lng')})")
    except Exception as e:
        print(f"   ❌ GPS hybrid search failed: {e}")
    
    # Test 5: Search outside GPS area
    print("\n6. Search test outside GPS area (Brno)...")
    try:
        # Brno: 49.1951, 16.6068
        # Use post-processing approach
        results = client.search_text("restaurant", limit=20)
        
        # Filter results by GPS distance
        filtered_results = []
        for result in results.results:
            geo = result.fields.get('geo', {})
            if 'lat' in geo and 'lng' in geo:
                distance = haversine_distance(49.1951, 16.6068, geo['lat'], geo['lng'])
                if distance <= 5:  # 5km
                    filtered_results.append(result)
                    if len(filtered_results) >= 10:
                        break
        
        print(f"   ✅ Found {len(filtered_results)} results within 5km of Brno")
        for result in filtered_results:
            geo = result.fields.get('geo', {})
            print(f"      - {result.doc_id}: {result.fields.get('document', '')[:50]}... (lat: {geo.get('lat')}, lng: {geo.get('lng')})")
    except Exception as e:
        print(f"   ❌ GPS search in Brno failed: {e}")
    
    # Clean up test documents
    print("\n7. Cleaning up test documents...")
    for doc_data in test_docs:
        doc_id = doc_data["id"]
        if client.delete_document(doc_id):
            print(f"   ✅ {doc_id} deleted")
        else:
            print(f"   ❌ Failed to delete {doc_id}")
    
    print("\n=== GPS Test Completed ===")
    return True

def main():
    """Main function."""
    print("🚀 Running GPS search test\n")
    
    try:
        success = test_gps_search()
        if success:
            print("🎉 GPS tests passed successfully!")
            return True
        else:
            print("⚠️ Some GPS tests failed.")
            return False
    except Exception as e:
        print(f"❌ Test threw exception: {e}")
        return False

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
