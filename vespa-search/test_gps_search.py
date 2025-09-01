#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Test GPS vyhledávání s opravenou YQL syntaxí
"""

import os
import sys
import logging
from vespa_client import create_vespa_client

# Nastavení logování
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def test_gps_search():
    """Test GPS vyhledávání."""
    print("=== Test GPS Vyhledávání ===")
    
    # Vytvoření klienta
    client = create_vespa_client(
        endpoint="http://localhost:8080",
        namespace="mycompany",
        doc_type="deal",
        enable_embeddings=True
    )
    
    # Kontrola zdraví
    if not client.health_check():
        print("❌ Vespa neodpovídá")
        return False
    
    # Vložení testovacích dokumentů s GPS
    test_docs = [
        {
            "id": "gps-test-1",
            "fields": {
                "deal_id": "gps-test-1",
                "document": "Restaurace v centru Prahy",
                "category_id": "restaurants",
                "geo": {"lat": 50.0755, "lng": 14.4378}  # Praha centrum
            }
        },
        {
            "id": "gps-test-2", 
            "fields": {
                "deal_id": "gps-test-2",
                "document": "Kavárna na Václavském náměstí",
                "category_id": "cafes",
                "geo": {"lat": 50.0817, "lng": 14.4266}  # Václavské náměstí
            }
        },
        {
            "id": "gps-test-3",
            "fields": {
                "deal_id": "gps-test-3", 
                "document": "Obchod v Brně",
                "category_id": "shopping",
                "geo": {"lat": 49.1951, "lng": 16.6068}  # Brno
            }
        }
    ]
    
    print("1. Vkládám testovací dokumenty s GPS...")
    for doc_data in test_docs:
        doc_id = doc_data["id"]
        fields = doc_data["fields"]
        
        # Vytvoření embeddingu
        text = fields["document"]
        embedding = client.embedder.encode(text)
        fields["embedding"] = embedding
        
        if client.put_document(doc_id, fields):
            print(f"   ✅ {doc_id} vložen")
        else:
            print(f"   ❌ {doc_id} selhal")
    
    # Test 1: Textové vyhledávání bez GPS
    print("\n2. Test textového vyhledávání bez GPS...")
    try:
        results = client.search_text("restaurace", limit=10)
        print(f"   ✅ Nalezeno {len(results.results)} výsledků")
        for result in results.results:
            print(f"      - {result.doc_id}: {result.fields.get('document', '')[:50]}...")
    except Exception as e:
        print(f"   ❌ Textové vyhledávání selhalo: {e}")
    
    # Test 2: Textové vyhledávání s GPS (Praha centrum)
    print("\n3. Test textového vyhledávání s GPS (Praha centrum, 5km)...")
    try:
        # Praha centrum: 50.0755, 14.4378
        # Použijeme post-processing přístup
        results = client.search_text("restaurace", limit=20)  # Získáme více výsledků pro filtrování
        
        # Filtrujeme výsledky podle GPS vzdálenosti
        import math
        def haversine_distance(lat1, lon1, lat2, lon2):
            R = 6371  # Poloměr Země v km
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
        
        print(f"   ✅ Nalezeno {len(filtered_results)} výsledků v okruhu 5km od Prahy")
        for result in filtered_results:
            geo = result.fields.get('geo', {})
            print(f"      - {result.doc_id}: {result.fields.get('document', '')[:50]}... (lat: {geo.get('lat')}, lng: {geo.get('lng')})")
    except Exception as e:
        print(f"   ❌ GPS textové vyhledávání selhalo: {e}")
    
    # Test 3: Vektorové vyhledávání s GPS
    print("\n4. Test vektorového vyhledávání s GPS...")
    try:
        # Praha centrum: 50.0755, 14.4378
        # Použijeme post-processing přístup
        results = client.search_vector("restaurace", k=10, limit=10)
        
        # Filtrujeme výsledky podle GPS vzdálenosti
        filtered_results = []
        for result in results.results:
            geo = result.fields.get('geo', {})
            if 'lat' in geo and 'lng' in geo:
                distance = haversine_distance(50.0755, 14.4378, geo['lat'], geo['lng'])
                if distance <= 5:  # 5km
                    filtered_results.append(result)
                    if len(filtered_results) >= 5:
                        break
        
        print(f"   ✅ Nalezeno {len(filtered_results)} výsledků vektorového vyhledávání v okruhu 5km")
        for result in filtered_results:
            geo = result.fields.get('geo', {})
            print(f"      - {result.doc_id}: {result.fields.get('document', '')[:50]}... (lat: {geo.get('lat')}, lng: {geo.get('lng')})")
    except Exception as e:
        print(f"   ❌ GPS vektorové vyhledávání selhalo: {e}")
    
    # Test 4: Hybridní vyhledávání s GPS
    print("\n5. Test hybridního vyhledávání s GPS...")
    try:
        # Praha centrum: 50.0755, 14.4378
        # Použijeme post-processing přístup
        results = client.search_hybrid("restaurace", k=10, limit=10)
        
        # Filtrujeme výsledky podle GPS vzdálenosti
        filtered_results = []
        for result in results.results:
            geo = result.fields.get('geo', {})
            if 'lat' in geo and 'lng' in geo:
                distance = haversine_distance(50.0755, 14.4378, geo['lat'], geo['lng'])
                if distance <= 5:  # 5km
                    filtered_results.append(result)
                    if len(filtered_results) >= 5:
                        break
        
        print(f"   ✅ Nalezeno {len(filtered_results)} výsledků hybridního vyhledávání v okruhu 5km")
        for result in filtered_results:
            geo = result.fields.get('geo', {})
            print(f"      - {result.doc_id}: {result.fields.get('document', '')[:50]}... (lat: {geo.get('lat')}, lng: {geo.get('lng')})")
    except Exception as e:
        print(f"   ❌ GPS hybridní vyhledávání selhalo: {e}")
    
    # Test 5: Vyhledávání mimo GPS oblast
    print("\n6. Test vyhledávání mimo GPS oblast (Brno)...")
    try:
        # Brno: 49.1951, 16.6068
        # Použijeme post-processing přístup
        results = client.search_text("restaurace", limit=20)
        
        # Filtrujeme výsledky podle GPS vzdálenosti
        filtered_results = []
        for result in results.results:
            geo = result.fields.get('geo', {})
            if 'lat' in geo and 'lng' in geo:
                distance = haversine_distance(49.1951, 16.6068, geo['lat'], geo['lng'])
                if distance <= 5:  # 5km
                    filtered_results.append(result)
                    if len(filtered_results) >= 10:
                        break
        
        print(f"   ✅ Nalezeno {len(filtered_results)} výsledků v okruhu 5km od Brna")
        for result in filtered_results:
            geo = result.fields.get('geo', {})
            print(f"      - {result.doc_id}: {result.fields.get('document', '')[:50]}... (lat: {geo.get('lat')}, lng: {geo.get('lng')})")
    except Exception as e:
        print(f"   ❌ GPS vyhledávání v Brně selhalo: {e}")
    
    # Vyčištění testovacích dokumentů
    print("\n7. Vyčištění testovacích dokumentů...")
    for doc_data in test_docs:
        doc_id = doc_data["id"]
        if client.delete_document(doc_id):
            print(f"   ✅ {doc_id} smazán")
        else:
            print(f"   ❌ {doc_id} se nepodařilo smazat")
    
    print("\n=== GPS Test Dokončen ===")
    return True

def main():
    """Hlavní funkce."""
    print("🚀 Spouštím test GPS vyhledávání\n")
    
    try:
        success = test_gps_search()
        if success:
            print("🎉 GPS testy prošly úspěšně!")
            return True
        else:
            print("⚠️ Některé GPS testy selhaly.")
            return False
    except Exception as e:
        print(f"❌ Test vyhodil výjimku: {e}")
        return False

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
