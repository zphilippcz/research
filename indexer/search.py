import struct
import fnvhash
import sys
import redis

r = redis.Redis(host='localhost', port=6379, db=0)

def get_documents(index_file_path, data_file_path, word):
    # Vytvoření hash slova
    word_hash = fnvhash.fnv1a_64(word.encode('utf-8'))
    
    # Otevření indexu
    with open(index_file_path, 'rb') as index_file:
        while True:
            # Read index row (key, position, list_length)
            record = index_file.read(16)  # 8 bytes for key (Q), 4 bytes for position (I), 4 bytes for list_length (I)
            if not record:
                break  # Konec souboru
            
            key, position, list_length = struct.unpack('QII', record)
            
            if key == word_hash:
                # Pokud se hash shoduje, načti dokumenty ze souboru
                with open(data_file_path, 'rb') as data_file:
                    data_file.seek(position)
                    documents = data_file.read(list_length)
                    results = []
                    for i in range(0, len(documents), 40):
                        deal_uuid, count = struct.unpack('36sI', documents[i:i+40])
                        results.append((deal_uuid.decode('utf-8').strip('\x00'), count))
                    return results  # Vrať seznam dokumentů

    return None  # Slovo se nenalezlo

# Příklad použití
index_file_path = 'search.index'
data_file_path = 'search.dat'
if len(sys.argv) != 2:
    print("Použití: python search.py <search_word>")
    sys.exit(1)

search_word = sys.argv[1]

documents = get_documents(index_file_path, data_file_path, search_word)
if documents is not None:
    for uuid, count in documents:
        # Připojení k Redis serveru
        

        # Přečtení hodnoty z Redis pro daný UUID
        #value = r.get(uuid)
        print(f"Deal UUID: {uuid}, Count: {count}")
        #if value:
        #    print(f"Deal UUID: {uuid}, Count: {count}, Redis Value: {value}")
        #else:
        #    print(f"Deal UUID: {uuid}, Count: {count}, Redis Value: Not found")
        #print(f"Deal UUID: {uuid}, Count: {count}")
else:
    print("Slovo nenalezeno.")