from tqdm import tqdm

import sqlite3 
import json
import struct

db_path = '/Users/zphilipp/git/research/dealsdb/deals_db1.db'


def compute_tfidf():
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    sql_query = """
        SELECT deal_uuid, lat, lon FROM redemption                             
    """

    cursor.execute(sql_query)
    redemptions = cursor.fetchall()
    with tqdm(total=len(redemptions)) as pbar:
        with open('redemption.index', 'wb') as index_file:
            for redemption in redemptions:

                if redemption[1] is None or redemption[2] is None:
                    continue

                deal_uuid = redemption[0]
                lat = float(redemption[1])# * (3.141592653589793 / 180.0)
                lon = float(redemption[2])# * (3.141592653589793 / 180.0)

                # Write deal_uuid, position, and length to index file
                deal_uuid_bytes = deal_uuid.encode('utf-8')

                index_file.write(struct.pack('36sff', deal_uuid_bytes, lat, lon))
                
                pbar.update(1)

    conn.close()        
        

compute_tfidf()

