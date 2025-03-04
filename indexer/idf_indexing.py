import sqlite3
import struct
import json

from idf_pb2 import IdfEntry

db_file = '/Users/zphilipp/git/research/dealsdb/deals_db1.db'

def main():
    conn = sqlite3.connect(db_file)
    cursor = conn.cursor()

    with open('idf.dat', 'wb') as data_file, open('idf.index', 'wb') as index_file:
        cursor.execute("""
            SELECT
                deal_uuid,
                unigram, bigram, trigram
            FROM idf """)
        
        for row in cursor.fetchall():
            my_data = IdfEntry()
            my_data.deal_uuid = row[0]
            #print (row)
            if row[1] is not None:
                for item in json.loads(row[1]):
                    ngram = my_data.unigram.add()
                    ngram.word = item[0]
                    ngram.weight = item[1]

            if row[2] is not None:
                for item in json.loads(row[2]):
                    ngram = my_data.bigram.add()
                    ngram.word = item[0]
                    ngram.weight = item[1]

            if row[3] is not None:
                for item in json.loads(row[3]):
                    ngram = my_data.trigram.add()
                    ngram.word = item[0]
                    ngram.weight = item[1]

            serialized_data = my_data.SerializeToString()
            serialized_length = len(serialized_data)

            position = data_file.tell()
            data_file.write(serialized_data)

            # Pack as (id, position, length)
            index_entry = struct.pack('<36sII', my_data.deal_uuid.encode('utf-8'), position, serialized_length)
            #index_entry = struct.pack('<III', my_data.deal_id, position, serialized_length)
            index_file.write(index_entry)

    cursor.close()
    conn.close()

if __name__ == "__main__":
    main()
