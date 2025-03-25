import sqlite3
import fnvhash
import struct
import re
#from nltk.stem import WordNetLemmatizer
from tqdm import tqdm

from methods import clean_text

def fnv1a_64(data: bytes) -> int:
    # FNV-1a 64-bit parameters
    FNV_prime = 0x100000001b3
    FNV_offset_basis = 0xCBF29CE484222325

    hash_value = FNV_offset_basis
    for byte in data:
        hash_value ^= byte  # XOR byte
        hash_value *= FNV_prime  # Multiply by prime

        # Udržování v rozsahu 64-bits
        hash_value &= 0xFFFFFFFFFFFFFFFF  

    return hash_value

# Připojení k databázi
conn = sqlite3.connect('/Users/zphilipp/git/research/dealsdb/deals_db1.db')
cursor = conn.cursor()

# Vyhledání dokumentů
cursor.execute("""
    SELECT
        d.deal_uuid,
        COALESCE(MAX(d.title_general), '') || ' ' ||
        -- COALESCE(MAX(d.highlights), '') || ' ' ||
        COALESCE(MAX(o.title, ','), '') || ' ' ||
        COALESCE(MAX(m.name), '') AS text
    FROM deals d
        LEFT JOIN merchant m ON (d.merchant_id=m.id)
        LEFT JOIN options o ON (o.deal_id=d.id)
      --WHERE d.deal_uuid ='00009bea-7546-431c-bee3-05650f9e7ff8' or d.deal_uuid ='0001d669-8196-4057-a776-bcc60e765bc5'
    GROUP BY d.deal_uuid
            --limit 2
""")


documents = cursor.fetchall()
conn.close()
test = []
words_map = {}


#documents = [
#    ('00000000-1111-1111-1111-111111111111', 'massage'),    
#    ('11111111-1111-1111-1111-111111111111', 'oil massage'),
#    ('12222222-1111-1111-1111-111111111111', 'oil massage for free oil terapy'),
#    ('13333333-1111-1111-1111-111111111111', 'oil massage for free massage oil terapy terapy'),   
#]
with tqdm(total=len(documents), desc="indexing") as pbar:
    for deal_uuid, text in documents:

        #print (text, deal_uuid)
        text = clean_text(text)
        deal_uuid = deal_uuid.encode('utf-8')
        words = text.lower().split()
        #print(f"Words: {words}")
        words = [fnv1a_64(word.encode('utf-8')) for word in words]
        #print(f"Words: {words}")
        word_count = {word: words.count(word) for word in set(words)}

        for word, count in word_count.items():
            #if word == 2477301745829165648:
            #    test.append({"id": deal_uuid})
            if word not in words_map:
                words_map[word] = []
            words_map[word].append((deal_uuid, count))
        
        pbar.update(1)
        
#for key, value in words_map.items():
#    print(f"Word: {key} -> Occurrences: {value}")


#print(len(test))
tqdm.write(f"Total words: {len(words_map)}")
tqdm.write(f"Total documents: {len(documents)}")

print("Writing to files...")

with open('search.dat', 'wb') as data_file, open('search.index', 'wb') as index_file:
    for key, documents in words_map.items():
        
        list_length = len(documents) * struct.calcsize('36sI')
        for deal_uuid, count in documents:
            data_file.write(struct.pack('36sI', deal_uuid, count))
        position = data_file.tell() - list_length
        #print(f"Key: {key}, Position: {position}, List Length: {list_length}")

        index_file.write(struct.pack('QII', key, position, list_length))

tqdm.write(f"Writing to files...: {data_file}.")
tqdm.write(f"Writing to files...: {index_file}.")
print("Done")
