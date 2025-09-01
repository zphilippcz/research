# Vespa Client Library for Python

Kompletní knihovna pro práci s Vespa search engine v Pythonu. Podporuje operace s dokumenty, vyhledávání a vektorové embeddings.

## Instalace

```bash
pip install -r requirements.txt
```

## Integrace s existujícími soubory

Knihovna je plně integrována s vašimi existujícími soubory:

### server.py
- Používá `vespa_client.py` místo původních funkcí z `py_vespa.py`
- Zachovává stejné API endpointy a funkcionalitu
- Lepší error handling a logging

### py_vespa.py  
- Refaktorován pro použití nové knihovny
- Zachovává stejné command-line rozhraní
- Všechny původní funkce fungují stejně

### Spuštění integračních testů

```bash
# Test, že vše funguje správně
python test_integration.py

# Test GPS vyhledávání
python test_gps_search.py

# Spuštění serveru
python server.py

# Použití py_vespa.py
python py_vespa.py --search-text "test"
```

### GPS vyhledávání

Knihovna podporuje geografické vyhledávání pomocí GPS souřadnic s post-processing přístupem:

```python
# Textové vyhledávání s GPS filtrem
results = client.search_text("restaurace", limit=20)
# Filtrujeme výsledky podle GPS vzdálenosti v Pythonu
filtered_results = []
for result in results.results:
    geo = result.fields.get('geo', {})
    if 'lat' in geo and 'lng' in geo:
        distance = haversine_distance(50.0755, 14.4378, geo['lat'], geo['lng'])
        if distance <= 5:  # 5km
            filtered_results.append(result)

# Vektorové vyhledávání s GPS filtrem  
yql = "select * from deal where ([{targetHits:10}]nearestNeighbor(embedding, qemb))"
results = client.search_yql(yql, limit=10)
# Filtrujeme výsledky podle GPS vzdálenosti v Pythonu

# Hybridní vyhledávání s GPS filtrem
yql = "select * from sources * where (([{targetHits:10}]nearestNeighbor(embedding, qemb)) OR userQuery())"
results = client.search_yql(yql, limit=10, query_text="restaurace")
# Filtrujeme výsledky podle GPS vzdálenosti v Pythonu
```

**Poznámka:** Používá se post-processing přístup s Haversine formulí pro výpočet vzdálenosti. Vespa schéma má `type position` s `indexing: attribute | summary`. Nativní YQL geografické funkce nejsou podporovány v této verzi Vespa.

## Základní použití

### Vytvoření klienta

```python
from vespa_client import create_vespa_client

# Základní klient
client = create_vespa_client(
    endpoint="http://localhost:8080",
    namespace="mycompany",
    doc_type="deal"
)

# Klient s podporou embeddings
client = create_vespa_client(
    endpoint="http://localhost:8080",
    namespace="mycompany", 
    doc_type="deal",
    enable_embeddings=True,
    embedding_model="all-MiniLM-L6-v2"
)
```

### Kontrola zdraví

```python
if client.health_check():
    print("Vespa běží správně!")
else:
    print("Vespa neodpovídá")
```

## Operace s dokumenty

### Vložení dokumentu

```python
# Jednoduchý dokument
doc_fields = {
    "deal_id": "deal-123",
    "document": "Tento dokument popisuje skvělou nabídku",
    "category_id": "electronics",
    "price": 99.99,
    "is_active": True
}

success = client.put_document("deal-123", doc_fields)
if success:
    print("Dokument byl úspěšně vložen")
```

### Dokument s geolokací

```python
doc_fields = {
    "deal_id": "deal-456",
    "document": "Nabídka v Praze",
    "category_id": "restaurants",
    "geo": {"lat": 50.0755, "lng": 14.4378}
}

client.put_document("deal-456", doc_fields)
```

### Dokument s embeddingem

```python
from vespa_client import VespaClient, VespaConfig

config = VespaConfig(
    endpoint="http://localhost:8080",
    namespace="mycompany",
    doc_type="deal"
)

client = VespaClient(config)
client.enable_embeddings()

# Vytvoření embeddingu
text = "Tento dokument popisuje skvělou nabídku"
embedding = client.embedder.encode(text)

doc_fields = {
    "deal_id": "deal-789",
    "document": text,
    "category_id": "electronics",
    "embedding": embedding
}

client.put_document("deal-789", doc_fields)
```

### Hromadné vkládání

```python
from vespa_client import Document

documents = [
    Document("doc-1", {"deal_id": "1", "document": "První dokument"}),
    Document("doc-2", {"deal_id": "2", "document": "Druhý dokument"}),
    Document("doc-3", {"deal_id": "3", "document": "Třetí dokument"})
]

successful, failed = client.batch_put_documents(documents, batch_size=100)
print(f"Úspěšně vloženo: {successful}, selhalo: {failed}")
```

### Získání dokumentu

```python
doc = client.get_document("deal-123")
if doc:
    print(f"Dokument: {doc}")
else:
    print("Dokument nebyl nalezen")
```

### Smazání dokumentu

```python
success = client.delete_document("deal-123")
if success:
    print("Dokument byl smazán")
```

### Smazání všech dokumentů

```python
success = client.delete_all_documents()
if success:
    print("Všechny dokumenty byly smazány")
```

## Vyhledávání

### Textové vyhledávání

```python
results = client.search_text("skvělá nabídka", limit=10)
print(f"Nalezeno {len(results.results)} výsledků")

for result in results.results:
    print(f"- {result.doc_id}: {result.score}")
    print(f"  Text: {result.fields.get('document', '')[:100]}...")
```

### Vektorové vyhledávání

```python
# Musí být povoleno embeddings
client.enable_embeddings()

results = client.search_vector(
    query="skvělá nabídka",
    k=100,  # targetHits pro nearest neighbor
    limit=10,
    rank_profile="vector"
)

for result in results.results:
    print(f"- {result.doc_id}: {result.score}")
```

### Hybridní vyhledávání

```python
results = client.search_hybrid(
    query="skvělá nabídka",
    k=100,
    limit=10,
    rank_profile="hybrid"
)

for result in results.results:
    print(f"- {result.doc_id}: {result.score}")
```

### Vlastní YQL dotaz

```python
yql = "select * from deal where category_id contains 'electronics'"
results = client.search_yql(yql, limit=10)

for result in results.results:
    print(f"- {result.doc_id}: {result.fields.get('category_id')}")
```

### Filtrování podle ceny

```python
yql = "select * from deal where price < 100 and is_active = true"
results = client.search_yql(yql, limit=10)

for result in results.results:
    price = result.fields.get('price', 0)
    print(f"- {result.doc_id}: {price} Kč")
```

## Pokročilé funkce

### Vlastní konfigurace

```python
from vespa_client import VespaConfig, VespaClient

config = VespaConfig(
    endpoint="http://localhost:8080",
    namespace="mycompany",
    doc_type="deal",
    timeout=60,
    max_retries=10,
    backoff_factor=1.0
)

client = VespaClient(config)
```

### Statistiky

```python
stats = client.get_statistics()
if stats:
    print("Vespa statistiky:", stats)
```

### Embedding model

```python
# Vlastní embedding model
client.enable_embeddings(
    model_name="all-mpnet-base-v2",  # 768 dimenzí
    dimension=768
)

# Batch encoding
texts = ["První text", "Druhý text", "Třetí text"]
embeddings = client.embedder.encode_batch(texts)
```

## Příklady použití

### Indexování dat z databáze

```python
import sqlite3
from vespa_client import create_vespa_client, Document

client = create_vespa_client(enable_embeddings=True)

# Připojení k databázi
conn = sqlite3.connect("deals.db")
cursor = conn.cursor()

cursor.execute("SELECT id, title, description, category FROM deals")
rows = cursor.fetchall()

documents = []
for row in rows:
    deal_id, title, description, category = row
    
    # Vytvoření embeddingu
    text = f"{title}. {description}"
    embedding = client.embedder.encode(text)
    
    doc = Document(
        doc_id=str(deal_id),
        fields={
            "deal_id": str(deal_id),
            "document": text,
            "category_id": category,
            "embedding": embedding
        }
    )
    documents.append(doc)

# Hromadné vložení
successful, failed = client.batch_put_documents(documents)
print(f"Indexováno {successful} dokumentů, {failed} selhalo")

conn.close()
```

### Vyhledávací API

```python
from flask import Flask, request, jsonify
from vespa_client import create_vespa_client

app = Flask(__name__)
client = create_vespa_client(enable_embeddings=True)

@app.route('/search', methods=['GET'])
def search():
    query = request.args.get('q', '')
    search_type = request.args.get('type', 'text')  # text, vector, hybrid
    limit = int(request.args.get('limit', 10))
    
    if search_type == 'text':
        results = client.search_text(query, limit=limit)
    elif search_type == 'vector':
        results = client.search_vector(query, limit=limit)
    elif search_type == 'hybrid':
        results = client.search_hybrid(query, limit=limit)
    else:
        return jsonify({'error': 'Invalid search type'}), 400
    
    return jsonify({
        'results': [
            {
                'id': result.doc_id,
                'score': result.score,
                'fields': result.fields
            }
            for result in results.results
        ],
        'total_hits': results.total_hits
    })

if __name__ == '__main__':
    app.run(debug=True)
```

## Struktura dokumentu

Podle schématu `deal.sd`:

```python
{
    "deal_id": "string",           # ID nabídky
    "document": "string",          # Text dokumentu (indexovaný)
    "category_id": "string",       # Kategorie
    "price": 99.99,               # Cena (double)
    "is_active": True,            # Aktivní nabídka (boolean)
    "geo": {"lat": 50.0, "lng": 14.0},  # Geopozice
    "embedding": [0.1, 0.2, ...]  # Vektor (384 dimenzí)
}
```

## Ranking profily

- `default` - Textové vyhledávání (BM25)
- `vector` - Vektorové vyhledávání (cosine similarity)
- `hybrid` - Kombinace textu a vektoru

## Chybové stavy

Knihovna loguje chyby a vrací informace o selhání:

```python
results = client.search_text("query")
if results.errors:
    print("Chyby:", results.errors)
```

## Logování

```python
import logging

# Nastavení logování
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger('vespa_client')
```

## Licence

MIT License
