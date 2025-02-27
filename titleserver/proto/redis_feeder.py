import sqlite3
import struct
import json

from titleentry_pb2 import TitleEntry
import redis

db_file = '/Users/zphilipp/git/research/dealsdb/deals_db1.db'

def store(my_data, serialized_data, redis_client):
    redis_client.set(my_data.deal_uuid, serialized_data)

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
        
        # Connect to Redis
        redis_client = redis.StrictRedis(host='127.0.0.1', port=6379, db=0)

        for row in cursor.fetchall():
            my_data = TitleEntry()

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

            # Store serialized data in Redis with deal_uuid as the key
            store(my_data, serialized_data, redis_client)

    cursor.close()
    conn.close()


if __name__ == "__main__":
    main()

