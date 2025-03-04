import struct

def load_and_print_data(index_file_path, data_file_path):

    with open(index_file_path, 'rb') as index_file:
        while True:

            record = index_file.read(16)
            if not record:
                break
            
            key, position, list_length = struct.unpack('QII', record)
            print(f"Word Hash: {key}, position: {position}, list_length: {list_length}")
            
            if 1:#key == 2477301745829165648:
                
                with open(data_file_path, 'rb') as data_file:
                    data_file.seek(position)
                    documents = data_file.read(list_length)
                    print(f"Documents: {documents}")
                    doc = {}
                    for i in range(0, len(documents), 40):
                        deal_uuid, count = struct.unpack('36sI', documents[i:i+40])
                        doc[deal_uuid.decode('utf-8')] = count

                    for key, value in doc.items():    
                        print(f"{key} {value}")

index_file_path = 'search.index'
data_file_path = 'search.dat'

load_and_print_data(index_file_path, data_file_path)