import sqlite3
import struct
import json

from titleentry_pb2 import TitleEntry

db_file = '/Users/zphilipp/git/research/dealsdb/deals_db1.db'

def main():
    conn = sqlite3.connect(db_file)
    cursor = conn.cursor()

    with open('output.dat', 'wb') as data_file, open('index.bin', 'wb') as index_file:
        cursor.execute("""
            SELECT
                d.id,
                d.deal_id,
                d.deal_uuid,
                d.title_general, 
                d.med_image,
                d.rating_count,
                d.rating_value,
                m.name,
                d.small_image,
                d.gallery_title,
                d.currency,
                d.is_bookable,
                d.start_at,
                d.end_at
            FROM deals d
            LEFT JOIN merchant m
            ON d.merchant_id = m.id""")
        
        for row in cursor.fetchall():
            my_data = TitleEntry()

            #my_data.id = row[0]
            my_data.id = row[2]
            my_data.deal_id = row[1]
            my_data.deal_uuid = row[2]
            my_data.title_general = row[3]
            my_data.med_image = row[4]
            my_data.rating_count = row[5] if row[5] is not None else 0
            my_data.rating_value = row[6] if row[6] is not None else 0
            my_data.merchant_name = row[7] if row[7] is not None else ''
            my_data.small_image = row[8] if row[8] is not None else ''
            my_data.gallery_title = row[9]
            my_data.currency = row[10]
            my_data.is_bookable = bool(row[11]) if row[11] is not None else False
            my_data.start_at = row[12]
            my_data.end_at = row[13]

            serialized_data = my_data.SerializeToString()
            serialized_length = len(serialized_data)  # Calculate the length of the serialized data

            position = data_file.tell()
            data_file.write(serialized_data)

            # Pack as (id, position, length)
            #index_entry = struct.pack('<III', my_data.id, position, serialized_length)
            index_entry = struct.pack('<36sII', my_data.id.encode('utf-8'), position, serialized_length)

            index_file.write(index_entry)

    cursor.close()
    conn.close()

if __name__ == "__main__":
    main()

