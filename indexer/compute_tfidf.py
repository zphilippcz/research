from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.preprocessing import normalize
from tqdm import tqdm
from methods import clean_text
import numpy as np
import sqlite3 
import json

db_path = '/Users/zphilipp/git/research/dealsdb/deals_db1.db'

# TF-IDF
def get_important_words(documents, ngram_range, min_tfidf=0.00001):
    vectorizer = TfidfVectorizer(ngram_range=ngram_range)
    tfidf_matrix = vectorizer.fit_transform(list(documents.values()))
    tfidf_normalized = normalize(tfidf_matrix, norm='l2')

    important_words = {}
    feature_names = vectorizer.get_feature_names_out()
    document_keys = list(documents.keys())

    # Avoiding explicit conversion to dense array
    with tqdm(total=tfidf_normalized.shape[0]) as pbar:
        for idx in range(tfidf_normalized.shape[0]):
            document_vector = tfidf_normalized[idx].toarray().flatten()  # Convert to array
            indices = np.where(document_vector > min_tfidf)[0]
            words = sorted(
                [(feature_names[i], document_vector[i]) for i in indices],
                key=lambda x: x[1],
                reverse=True
            )
            important_words[document_keys[idx]] = words
            pbar.update(1)

    return important_words

def fetch_tree(item_id, cursor):
    cursor.execute("SELECT parent_id, name FROM category WHERE id = ?", (item_id,))
    item = cursor.fetchone()
    #print(item)
    if not item:
        return None
    
    # Vytvoření uzlu
    return {
        'value': item[1],
        'parent_id': item[0]
    }

def get_taxonomy_path(id, cursor):
    data = fetch_tree(id, cursor)
    category_string = ""
    while data is not None:    
        data = fetch_tree(data["parent_id"], cursor)
        try:
            category_string = data["value"] + " / " + category_string
        except TypeError as e:
            #print (data)
            break
    
    return category_string[:-2]  


def compute_tfidf():
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    sql_query = """
        SELECT                                 
            d.deal_uuid,
            
            COALESCE(MAX(d.title_general), '') || ' ' ||
            COALESCE(MAX(d.highlights), '') || ' ' ||
            COALESCE(GROUP_CONCAT(o.title, ','), '') || ' ' ||
            COALESCE(MAX(m.name), '') AS text,
            
            d.customer_category_id
        FROM deals d
            LEFT JOIN merchant m ON (d.merchant_id=m.id)
            LEFT JOIN options o ON (o.deal_id=d.id)
        -- where d.id=151
        GROUP BY d.deal_uuid
    """

    cursor.execute(sql_query)

    
    documents = {}
    for row in cursor.fetchall():
        category = get_taxonomy_path(row[2], cursor)
        document = row[1].encode().decode('unicode_escape')
        document = clean_text(document + '. ' + category.strip() + '.')
        documents[row[0]] = document

    with tqdm(total=len(documents)) as pbar:
        for id, value in get_important_words(documents, ngram_range=(1, 1), min_tfidf=0.03).items():
            sql_query = """
                INSERT OR REPLACE INTO idf (deal_uuid, unigram) VALUES (?, ?)
                ON CONFLICT(deal_uuid) DO UPDATE SET unigram = ?"""
            ngram = json.dumps(value[:15])
            cursor.execute(sql_query, (id, ngram, ngram))
            conn.commit()
            pbar.update(1)
            
    with tqdm(total=len(documents)) as pbar:
        for id, value in get_important_words(documents, ngram_range=(2, 2), min_tfidf=0.03).items():
            sql_query = """
                INSERT OR REPLACE INTO idf (deal_uuid, bigram) VALUES (?, ?)
                ON CONFLICT(deal_uuid) DO UPDATE SET bigram = ?"""
            ngram = json.dumps(value[:15])
            cursor.execute(sql_query, (id, ngram, ngram))
            conn.commit()
            pbar.update(1)
            
    with tqdm(total=len(documents)) as pbar:
        for id, value in get_important_words(documents, ngram_range=(3, 3), min_tfidf=0.03).items():
            sql_query = """
                INSERT INTO idf (deal_uuid, trigram) VALUES (?, ?)
                ON CONFLICT(deal_uuid) DO UPDATE SET trigram = ?"""
            ngram = json.dumps(value[:15])
            cursor.execute(sql_query, (id, ngram, ngram))
            conn.commit()
            pbar.update(1)


compute_tfidf()

