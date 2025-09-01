#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Příklad použití Vespa Client Library

Tento skript demonstruje základní funkce knihovny.
"""

import logging
from vespa_client import create_vespa_client, Document

# Nastavení logování
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def main():
    print("=== Vespa Client Library - Příklad použití ===\n")
    
    # Vytvoření klienta
    print("1. Vytvářím Vespa klienta...")
    client = create_vespa_client(
        endpoint="http://localhost:8080",
        namespace="mycompany",
        doc_type="deal",
        enable_embeddings=True
    )
    
    # Kontrola zdraví
    print("2. Kontroluji zdraví Vespa...")
    if client.health_check():
        print("✅ Vespa běží správně!")
    else:
        print("❌ Vespa neodpovídá - ujistěte se, že je spuštěn")
        return
    
    # Vložení testovacích dokumentů
    print("\n3. Vkládám testovací dokumenty...")
    
    test_documents = [
        {
            "id": "deal-1",
            "fields": {
                "deal_id": "deal-1",
                "document": "Skvělá nabídka na iPhone 15 s 20% slevou",
                "category_id": "electronics",
                "price": 19999.0,
                "is_active": True
            }
        },
        {
            "id": "deal-2", 
            "fields": {
                "deal_id": "deal-2",
                "document": "Restaurace v centru Prahy - oběd za 150 Kč",
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
                "document": "Letní dovolená v Řecku - all inclusive",
                "category_id": "travel",
                "price": 25000.0,
                "is_active": True
            }
        }
    ]
    
    # Vložení dokumentů s embeddings
    for doc_data in test_documents:
        doc_id = doc_data["id"]
        fields = doc_data["fields"]
        
        # Vytvoření embeddingu pro text
        text = fields["document"]
        embedding = client.embedder.encode(text)
        fields["embedding"] = embedding
        
        if client.put_document(doc_id, fields):
            print(f"✅ Dokument {doc_id} vložen")
        else:
            print(f"❌ Chyba při vkládání dokumentu {doc_id}")
    
    # Textové vyhledávání
    print("\n4. Textové vyhledávání...")
    results = client.search_text("iPhone", limit=5)
    print(f"Nalezeno {len(results.results)} výsledků pro 'iPhone':")
    for result in results.results:
        print(f"  - {result.doc_id}: {result.score:.4f}")
        print(f"    Text: {result.fields.get('document', '')[:60]}...")
    
    # Vektorové vyhledávání
    print("\n5. Vektorové vyhledávání...")
    results = client.search_vector("dovolená", k=10, limit=5)
    print(f"Nalezeno {len(results.results)} výsledků pro 'dovolená':")
    for result in results.results:
        print(f"  - {result.doc_id}: {result.score:.4f}")
        print(f"    Text: {result.fields.get('document', '')[:60]}...")
    
    # Hybridní vyhledávání
    print("\n6. Hybridní vyhledávání...")
    results = client.search_hybrid("nabídka", k=10, limit=5)
    print(f"Nalezeno {len(results.results)} výsledků pro 'nabídka':")
    for result in results.results:
        print(f"  - {result.doc_id}: {result.score:.4f}")
        print(f"    Text: {result.fields.get('document', '')[:60]}...")
    
    # Filtrování podle ceny
    print("\n7. Filtrování podle ceny...")
    yql = "select * from deal where price < 1000 and is_active = true"
    results = client.search_yql(yql, limit=5)
    print(f"Nalezeno {len(results.results)} levných nabídek:")
    for result in results.results:
        price = result.fields.get('price', 0)
        print(f"  - {result.doc_id}: {price} Kč")
        print(f"    Text: {result.fields.get('document', '')[:60]}...")
    
    # Filtrování podle kategorie
    print("\n8. Filtrování podle kategorie...")
    yql = "select * from deal where category_id contains 'electronics'"
    results = client.search_yql(yql, limit=5)
    print(f"Nalezeno {len(results.results)} elektronických nabídek:")
    for result in results.results:
        print(f"  - {result.doc_id}: {result.fields.get('category_id')}")
        print(f"    Text: {result.fields.get('document', '')[:60]}...")
    
    # Získání konkrétního dokumentu
    print("\n9. Získání konkrétního dokumentu...")
    doc = client.get_document("deal-1")
    if doc:
        print(f"Dokument deal-1:")
        print(f"  ID: {doc.get('id')}")
        print(f"  Fields: {doc.get('fields', {})}")
    else:
        print("Dokument deal-1 nebyl nalezen")
    
    # Statistiky
    print("\n10. Získání statistik...")
    stats = client.get_statistics()
    if stats:
        print("✅ Statistiky získány")
        # Můžete procházet stats pro konkrétní metriky
    else:
        print("❌ Nepodařilo se získat statistiky")
    
    print("\n=== Příklad dokončen ===")
    print("Pro vyčištění testovacích dat můžete spustit:")
    print("client.delete_all_documents()")

if __name__ == "__main__":
    main()
