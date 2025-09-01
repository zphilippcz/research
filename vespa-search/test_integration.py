#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Integrační test pro ověření, že server.py a py_vespa.py fungují s novou knihovnou vespa_client.py
"""

import os
import sys
import time
import logging
from vespa_client import create_vespa_client

# Nastavení logování
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def test_vespa_client():
    """Test základní funkcionality Vespa klienta."""
    print("=== Test Vespa Client ===")
    
    # Vytvoření klienta
    client = create_vespa_client(
        endpoint="http://localhost:8080",
        namespace="mycompany",
        doc_type="deal",
        enable_embeddings=True
    )
    
    # Test zdraví
    print("1. Kontrola zdraví Vespa...")
    if client.health_check():
        print("✅ Vespa je zdravý")
    else:
        print("❌ Vespa neodpovídá")
        return False
    
    # Test vložení dokumentu
    print("2. Test vložení dokumentu...")
    test_doc = {
        "deal_id": "test-integration-123",
        "document": "Testovací dokument pro integrační test",
        "category_id": "test",
        "price": 100.0,
        "is_active": True
    }
    
    if client.put_document("test-integration-123", test_doc):
        print("✅ Dokument vložen")
    else:
        print("❌ Chyba při vkládání dokumentu")
        return False
    
    # Test získání dokumentu
    print("3. Test získání dokumentu...")
    doc = client.get_document("test-integration-123")
    if doc:
        print("✅ Dokument získán")
        print(f"   ID: {doc.get('id')}")
        print(f"   Fields: {doc.get('fields', {})}")
    else:
        print("❌ Dokument nebyl nalezen")
        return False
    
    # Test textového vyhledávání
    print("4. Test textového vyhledávání...")
    results = client.search_text("testovací", limit=5)
    print(f"✅ Textové vyhledávání: {len(results.results)} výsledků")
    
    # Test vektorového vyhledávání
    print("5. Test vektorového vyhledávání...")
    try:
        results = client.search_vector("testovací", k=10, limit=5)
        print(f"✅ Vektorové vyhledávání: {len(results.results)} výsledků")
    except Exception as e:
        print(f"⚠️ Vektorové vyhledávání selhalo: {e}")
    
    # Test hybridního vyhledávání
    print("6. Test hybridního vyhledávání...")
    try:
        results = client.search_hybrid("testovací", k=10, limit=5)
        print(f"✅ Hybridní vyhledávání: {len(results.results)} výsledků")
    except Exception as e:
        print(f"⚠️ Hybridní vyhledávání selhalo: {e}")
    
    # Test YQL dotazu
    print("7. Test YQL dotazu...")
    results = client.search_yql("select * from deal where category_id contains 'test'", limit=5)
    print(f"✅ YQL dotaz: {len(results.results)} výsledků")
    
    # Test smazání dokumentu
    print("8. Test smazání dokumentu...")
    if client.delete_document("test-integration-123"):
        print("✅ Dokument smazán")
    else:
        print("❌ Chyba při mazání dokumentu")
        return False
    
    print("=== Vespa Client Test Dokončen ===\n")
    return True

def test_py_vespa_import():
    """Test, že py_vespa.py lze importovat a používá novou knihovnu."""
    print("=== Test py_vespa.py Import ===")
    
    try:
        # Import py_vespa modulu
        import py_vespa
        
        print("✅ py_vespa.py importován úspěšně")
        print(f"   Vespa endpoint: {py_vespa.VESPA_ENDPOINT}")
        print(f"   Namespace: {py_vespa.NAMESPACE}")
        print(f"   Doc type: {py_vespa.DOC_TYPE}")
        print(f"   Vespa client: {type(py_vespa.vespa_client).__name__}")
        
        # Test základních funkcí
        print("   Testování funkcí...")
        
        # Test compute_embedding
        try:
            embedding = py_vespa.compute_embedding("test text")
            print(f"   ✅ compute_embedding: {len(embedding)} dimenzí")
        except Exception as e:
            print(f"   ⚠️ compute_embedding selhal: {e}")
        
        # Test put_doc
        test_doc = {
            "deal_id": "test-py-vespa-123",
            "document": "Test dokument pro py_vespa",
            "category_id": "test"
        }
        
        if py_vespa.put_doc("test-py-vespa-123", test_doc):
            print("   ✅ put_doc funguje")
            
            # Test delete_doc
            if py_vespa.delete_doc("test-py-vespa-123"):
                print("   ✅ delete_doc funguje")
            else:
                print("   ❌ delete_doc selhal")
        else:
            print("   ❌ put_doc selhal")
        
        print("=== py_vespa.py Import Test Dokončen ===\n")
        return True
        
    except Exception as e:
        print(f"❌ Chyba při importu py_vespa: {e}")
        return False

def test_server_import():
    """Test, že server.py lze importovat a používá novou knihovnu."""
    print("=== Test server.py Import ===")
    
    try:
        # Import server modulu
        import server
        
        print("✅ server.py importován úspěšně")
        print(f"   Vespa config: {type(server.vespa_config).__name__}")
        print(f"   Vespa client: {type(server.vespa_client).__name__}")
        print(f"   FastAPI app: {type(server.app).__name__}")
        
        # Test konfigurace
        print(f"   Endpoint: {server.vespa_config.endpoint}")
        print(f"   Namespace: {server.vespa_config.namespace}")
        print(f"   Doc type: {server.vespa_config.doc_type}")
        
        # Test funkcí
        print("   Testování funkcí...")
        
        # Test _perform_fulltext
        try:
            result = server._perform_fulltext("test", 5)
            print(f"   ✅ _perform_fulltext: {type(result).__name__}")
        except Exception as e:
            print(f"   ⚠️ _perform_fulltext selhal: {e}")
        
        print("=== server.py Import Test Dokončen ===\n")
        return True
        
    except Exception as e:
        print(f"❌ Chyba při importu server: {e}")
        return False

def main():
    """Hlavní funkce pro spuštění všech testů."""
    print("🚀 Spouštím integrační testy pro Vespa Client Library\n")
    
    # Kontrola, že Vespa běží
    print("Kontrola dostupnosti Vespa...")
    try:
        client = create_vespa_client()
        if client.health_check():
            print("✅ Vespa je dostupný\n")
        else:
            print("❌ Vespa není dostupný - spusťte Vespa před testováním")
            return False
    except Exception as e:
        print(f"❌ Nelze se připojit k Vespa: {e}")
        return False
    
    # Spuštění testů
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
            print(f"❌ Test {test_name} vyhodil výjimku: {e}")
            results.append((test_name, False))
    
    # Shrnutí výsledků
    print("=== Shrnutí výsledků ===")
    passed = 0
    total = len(results)
    
    for test_name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{status} {test_name}")
        if result:
            passed += 1
    
    print(f"\nCelkem: {passed}/{total} testů prošlo")
    
    if passed == total:
        print("🎉 Všechny testy prošly! Integrace je úspěšná.")
        return True
    else:
        print("⚠️ Některé testy selhaly. Zkontrolujte konfiguraci.")
        return False

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
