import struct
import response_pb2

import struct
from response_pb2 import ResponseEntry

def dump_data(data_file_path, index_file_path):

    with open(data_file_path, 'rb') as data_file, open(index_file_path, 'rb') as index_file:

        while True:
            index_bytes = index_file.read(struct.calcsize('<III'))
            if not index_bytes:
                break
            entry_id, position, length = struct.unpack('<III', index_bytes)
            
            # seek to the position in the data file
            data_file.seek(position)
            serialized_data = data_file.read(length)

            # deserialize the data
            response_entry = ResponseEntry()
            response_entry.ParseFromString(serialized_data)

            # print the data
            print(f"Entry -> pos: {position}, length: {length}\n"
                  f"ID: {response_entry.id}\n"
                  f"Title: {response_entry.title_general}\n"
                  f"Merchant: {response_entry.merchant_name}\n"
                  f"Image: {response_entry.med_image}\n"
                  f"Rating Count: {response_entry.rating_count} \n"
                  f"Rating Value: {response_entry.rating_value}")

if __name__ == "__main__":
    dump_data(
        '/Users/zphilipp/git/research/titleserver/proto/output.dat',
        '/Users/zphilipp/git/research/titleserver/proto/index.bin'
    )
