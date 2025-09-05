# Vespa Client Library for Python

Complete library for working with Vespa search engine in Python. Supports document operations, search, and vector embeddings.

## Installation

```bash
pip install -r requirements.txt
```

## Integration with existing files

The library is fully integrated with your existing files:

### server.py
- Uses `vespa_client.py` instead of original functions from `py_vespa.py`
- Maintains the same API endpoints and functionality
- Better error handling and logging

### py_vespa.py  
- Refactored to use the new library
- Maintains the same command-line interface
- All original functions work the same way

### Running integration tests

```bash
# Test that everything works correctly
python test_integration.py

# Test GPS search
python test_gps_search.py

# Start server
python server.py

# Use py_vespa.py
python py_vespa.py --search-text "test"
```

### GPS search

The library supports geographic search using GPS coordinates with post-processing approach:

```python
# Text search with GPS filter
results = client.search_text("restaurant", limit=20)
# Filter results by GPS distance in Python
filtered_results = []
for result in results.results:
    geo = result.fields.get('geo', {})
    if 'lat' in geo and 'lng' in geo:
        distance = haversine_distance(50.0755, 14.4378, geo['lat'], geo['lng'])
        if distance <= 5:  # 5km
            filtered_results.append(result)

# Vector search with GPS filter  
yql = "select * from deal where ([{targetHits:10}]nearestNeighbor(embedding, qemb))"
results = client.search_yql(yql, limit=10)
# Filter results by GPS distance in Python

# Hybrid search with GPS filter
yql = "select * from sources * where (([{targetHits:10}]nearestNeighbor(embedding, qemb)) OR userQuery())"
results = client.search_yql(yql, limit=10, query_text="restaurant")
# Filter results by GPS distance in Python
```

**Note:** Uses post-processing approach with Haversine formula for distance calculation. Vespa schema has `type position` with `indexing: attribute | summary`. Native YQL geographic functions are not supported in this version of Vespa.

## Basic usage

### Creating a client

```python
from vespa_client import create_vespa_client

# Basic client
client = create_vespa_client(
    endpoint="http://localhost:8080",
    namespace="mycompany",
    doc_type="deal"
)

# Client with embedding support
client = create_vespa_client(
    endpoint="http://localhost:8080",
    namespace="mycompany", 
    doc_type="deal",
    enable_embeddings=True,
    embedding_model="all-MiniLM-L6-v2"
)
```

### Health check

```python
if client.health_check():
    print("Vespa is running correctly!")
else:
    print("Vespa is not responding")
```

## Document operations

### Inserting a document

```python
# Simple document
doc_fields = {
    "deal_id": "deal-123",
    "document": "This document describes a great offer",
    "category_id": "electronics",
    "price": 99.99,
    "is_active": True
}

success = client.put_document("deal-123", doc_fields)
if success:
    print("Document was successfully inserted")
```

### Document with geolocation

```python
doc_fields = {
    "deal_id": "deal-456",
    "document": "Offer in Prague",
    "category_id": "restaurants",
    "geo": {"lat": 50.0755, "lng": 14.4378}
}

client.put_document("deal-456", doc_fields)
```

### Document with embedding

```python
from vespa_client import VespaClient, VespaConfig

config = VespaConfig(
    endpoint="http://localhost:8080",
    namespace="mycompany",
    doc_type="deal"
)

client = VespaClient(config)
client.enable_embeddings()

# Create embedding
text = "This document describes a great offer"
embedding = client.embedder.encode(text)

doc_fields = {
    "deal_id": "deal-789",
    "document": text,
    "category_id": "electronics",
    "embedding": embedding
}

client.put_document("deal-789", doc_fields)
```

### Batch insertion

```python
from vespa_client import Document

documents = [
    Document("doc-1", {"deal_id": "1", "document": "First document"}),
    Document("doc-2", {"deal_id": "2", "document": "Second document"}),
    Document("doc-3", {"deal_id": "3", "document": "Third document"})
]

successful, failed = client.batch_put_documents(documents, batch_size=100)
print(f"Successfully inserted: {successful}, failed: {failed}")
```

### Getting a document

```python
doc = client.get_document("deal-123")
if doc:
    print(f"Document: {doc}")
else:
    print("Document not found")
```

### Deleting a document

```python
success = client.delete_document("deal-123")
if success:
    print("Document was deleted")
```

### Deleting all documents

```python
success = client.delete_all_documents()
if success:
    print("All documents were deleted")
```

## Search

### Text search

```python
results = client.search_text("great offer", limit=10)
print(f"Found {len(results.results)} results")

for result in results.results:
    print(f"- {result.doc_id}: {result.score}")
    print(f"  Text: {result.fields.get('document', '')[:100]}...")
```

### Vector search

```python
# Must have embeddings enabled
client.enable_embeddings()

results = client.search_vector(
    query="great offer",
    k=100,  # targetHits for nearest neighbor
    limit=10,
    rank_profile="vector"
)

for result in results.results:
    print(f"- {result.doc_id}: {result.score}")
```

### Hybrid search

```python
results = client.search_hybrid(
    query="great offer",
    k=100,
    limit=10,
    rank_profile="hybrid"
)

for result in results.results:
    print(f"- {result.doc_id}: {result.score}")
```

### Custom YQL query

```python
yql = "select * from deal where category_id contains 'electronics'"
results = client.search_yql(yql, limit=10)

for result in results.results:
    print(f"- {result.doc_id}: {result.fields.get('category_id')}")
```

### Filtering by price

```python
yql = "select * from deal where price < 100 and is_active = true"
results = client.search_yql(yql, limit=10)

for result in results.results:
    price = result.fields.get('price', 0)
    print(f"- {result.doc_id}: {price} CZK")
```

## Advanced features

### Custom configuration

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

### Statistics

```python
stats = client.get_statistics()
if stats:
    print("Vespa statistics:", stats)
```

### Embedding model

```python
# Custom embedding model
client.enable_embeddings(
    model_name="all-mpnet-base-v2",  # 768 dimensions
    dimension=768
)

# Batch encoding
texts = ["First text", "Second text", "Third text"]
embeddings = client.embedder.encode_batch(texts)
```

## Usage examples

### Indexing data from database

```python
import sqlite3
from vespa_client import create_vespa_client, Document

client = create_vespa_client(enable_embeddings=True)

# Connect to database
conn = sqlite3.connect("deals.db")
cursor = conn.cursor()

cursor.execute("SELECT id, title, description, category FROM deals")
rows = cursor.fetchall()

documents = []
for row in rows:
    deal_id, title, description, category = row
    
    # Create embedding
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

# Batch insertion
successful, failed = client.batch_put_documents(documents)
print(f"Indexed {successful} documents, {failed} failed")

conn.close()
```

### Search API

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

## Document structure

According to `deal.sd` schema:

```python
{
    "deal_id": "string",           # Deal ID
    "document": "string",          # Document text (indexed)
    "category_id": "string",       # Category
    "price": 99.99,               # Price (double)
    "is_active": True,            # Active deal (boolean)
    "geo": {"lat": 50.0, "lng": 14.0},  # Geoposition
    "embedding": [0.1, 0.2, ...]  # Vector (384 dimensions)
}
```

## Ranking profiles

- `default` - Text search (BM25)
- `vector` - Vector search (cosine similarity)
- `hybrid` - Combination of text and vector

## Error states

The library logs errors and returns failure information:

```python
results = client.search_text("query")
if results.errors:
    print("Errors:", results.errors)
```

## Logging

```python
import logging

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger('vespa_client')
```

## License

MIT License