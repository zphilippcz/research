/**
 *
 * curl -v -H 'Content-Type: application/json' -d \
      '{"ids":["tj-nail-spa-lounge","safas-salon-day-spa-6","donelle-lamar-co-llc","zhuzhu-beauty-and-nail-salon","studio-anew-6","sea-spa-nails-salon","beach-club-salon-and-spa-6","ivona-tint-salon-and-spa-1","hello-beyoutiful-spa-10","paradise-day-spa-2-5"]}' -X POST http://127.0.0.1:8081/
*/
use actix_web::{web, App, HttpServer, Result, HttpResponse, Error, error};
use serde::Deserialize;
use serde::Serialize;
use rusqlite::{Connection};
use futures::StreamExt;
use prost::Message;
use std::fs::File;
use std::io::{Read, Seek};
use std::collections::HashMap;
use std::sync::{Arc, Mutex};
use std::env;

pub mod response {
    #[derive(Serialize, Debug)]
    include!(concat!(env!("OUT_DIR"), "/titleentry.rs"));
}

struct AppState {
    index_map: Mutex<HashMap<u32, (u32, u32)>>,
    data_file: Mutex<File>,
}


async fn reload_index(state: web::Data<AppState>) -> Result<(), Error> {
    let file_path = "/Users/zphilipp/git/research/titleserver/proto/index.bin";
    log::debug!("Loading index from file: {}", file_path);

    let mut file = File::open(file_path).map_err(|_| {
        log::error!("Error opening index file");
        error::ErrorInternalServerError("Error opening index file")
    })?;
    log::debug!("Index file opened successfully");
    
    let chunk_size = std::mem::size_of::<(u32, u32)>();

    /*
     * Example for reading 3 32-bit values from a buffer
     * let mut buffer = [0u8; 12]; // Buffer for three 32-bit values
     * let id = u32::from_le_bytes([buffer[0], buffer[1], buffer[2], buffer[3]]);
     * let position = u32::from_le_bytes([buffer[4], buffer[5], buffer[6], buffer[7]]);
     * let length = u32::from_le_bytes([buffer[8], buffer[9], buffer[10], buffer[11]]);
     * let info = (position, length);
     */
    let mut buffer = [0u8; 44]; // Buffer for 36B string and two 32-bit values
    while let Ok(read_bytes) = file.read(&mut buffer) {
        if read_bytes < chunk_size {
            break; // If we read less than 8 bytes, we end
        }

        let id_str = String::from_utf8_lossy(&buffer[..36]).to_string();
        let position = u32::from_le_bytes([buffer[36], buffer[37], buffer[38], buffer[39]]);
        let length = u32::from_le_bytes([buffer[40], buffer[41], buffer[42], buffer[43]]);
        let info = (position, length);

        let mut index_map = state.index_map.lock().unwrap();
        index_map.insert(id_str, info);
    }
    log::debug!("Index file successfully readed.");

    Ok(())
}

async fn get_title_by_ids(state: web::Data<AppState>, ids: web::Path<String>) -> Result<HttpResponse, Error> {
    let map = state.index_map.lock().unwrap();
    let ids_vec: Vec<u32> = ids.split(',').filter_map(|s| s.parse().ok()).collect();
    log::debug!("Get response for ids: {:?}", ids_vec);

    let mut results = Vec::new();

    for id in ids_vec {
        if let Some((position, length)) = map.get(&id).cloned() {
            if position != 0 && length != 0 {
                let mut data_file = state.data_file.lock().unwrap();

                if data_file.seek(std::io::SeekFrom::Start(position as u64)).is_err() {
                    return Err(error::ErrorBadRequest("Failed to seek to position"));
                }

                let mut buffer = vec![0; length as usize];
                if data_file.read_exact(&mut buffer).is_err() {
                    return Err(error::ErrorBadRequest("Failed to read message"));
                }

                match response::ResponseEntry::decode(&buffer[..]) {
                    Ok(entry) => {
                        let title_info = TitleInfo {
                            id: entry.id.to_string(),
                            title_general: entry.title_general.clone(),
                            med_image: entry.med_image.clone(),
                            rating_count: entry.rating_count as i32,
                            rating_value: entry.rating_value,
                            merchant_name: entry.merchant_name.clone(),
                            value: entry.value,
                            price: entry.price,
                            discount: entry.discount as i32,
                        };
                        results.push(title_info);
                    }
                    Err(_) => return Err(error::ErrorInternalServerError("Error decoding message")),
                }
            }
        }
    }

    if results.is_empty() {
        Ok(HttpResponse::NotFound().body("No valid IDs found or position/length is invalid"))
    } else {
        Ok(HttpResponse::Ok().json(results))
    }
}

#[actix_web::main]
async fn main() -> std::io::Result<()> {
    env::set_var("RUST_LOG", "debug");
    env_logger::init();


    let file_path = "/Users/zphilipp/git/research/titleserver/proto/output.dat";
    let data_file = File::open(file_path)?;

    let data = web::Data::new(AppState {
        index_map: Mutex::new(HashMap::new()),
        data_file: Mutex::new(data_file),
    });

    reload_index(data.clone()).await.unwrap();

    HttpServer::new(move || {
        App::new()
            .app_data(web::Data::new(db_connection.clone()))
            .app_data(data.clone())
            //.route("/reload_index", web::get().to(reload_index))
            .route("/get_title_by_ids/{id}", web::get().to(get_title_by_ids))
    })
    .bind("127.0.0.1:8081")?
    .run()
    .await
}

