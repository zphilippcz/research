import sqlite3
import struct
import json

from idf_pb2 import IdfEntry

db_file = '/Users/zphilipp/git/research/dealsdb/deals_db1.db'

def main():
    conn = sqlite3.connect(db_file)
    cursor = conn.cursor()

    with open('embeddings.index', 'wb') as index_file:
        cursor.execute("""
            SELECT
                deal_id, embedings
            FROM embedings""")

        for row in cursor.fetchall():
            embedings = json.loads(row[1])
            index_entry = struct.pack('<36s384d', row[0].encode('utf-8'), *embedings)
            index_file.write(index_entry)

    cursor.close()
    conn.close()

if __name__ == "__main__":
    main()
