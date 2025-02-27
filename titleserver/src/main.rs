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
use redis::AsyncCommands;

pub mod response {
    include!(concat!(env!("OUT_DIR"), "/titleentry.rs"));
}

struct AppState {
    //index_map: Mutex<HashMap<u32, (u32, u32)>>,
    index_map: Mutex<HashMap<String, (u32, u32)>>,
    data_file: Mutex<File>,
    redis_con: Mutex<redis::aio::Connection>,
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
        //log::debug!("Read id: {}, position: {}, length: {}", id_str, position, length);

        let mut index_map = state.index_map.lock().unwrap();
        index_map.insert(id_str, info);
    }
    log::debug!("Index file successfully readed.");

    Ok(())
}


async fn get_title_by_ids(state: web::Data<AppState>, ids: web::Path<String>) -> Result<HttpResponse, Error> {
    let map = state.index_map.lock().unwrap();
    let ids_vec: Vec<String> = ids.split(',').map(|s| s.to_string()).collect();
    log::debug!("Get response from data file for ids: {:?}", ids_vec);

    let mut results = Vec::new();

    for id in &ids_vec {
        log::debug!("Get title for id: {}", id);
        if let Some((position, length)) = map.get(id).cloned() {
            log::debug!("Found id: {}, position: {}, length: {}", id, position, length);

            if position != 0 && length != 0 {
                let mut data_file = state.data_file.lock().unwrap();

                if data_file.seek(std::io::SeekFrom::Start(position as u64)).is_err() {
                    return Err(error::ErrorBadRequest("Failed to seek to position"));
                }

                let mut buffer = vec![0; length as usize];
                if data_file.read_exact(&mut buffer).is_err() {
                    return Err(error::ErrorBadRequest("Failed to read message"));
                }

                match response::TitleEntry::decode(&buffer[..]) {
                    Ok(entry) => {
                        results.push(entry);
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

async fn get_title_by_ids_redis(state: web::Data<AppState>, ids: web::Path<String>) -> Result<HttpResponse, Error> {
    let ids_vec: Vec<String> = ids.split(',').map(|s| s.to_string()).collect();
    log::debug!("Get response for ids from Redis: {:?}", ids_vec);

    let mut con = state.redis_con.lock().unwrap();
    let mut results = Vec::new();
    
    for id in &ids_vec {
        log::debug!("Get title for id: {}", id);
        let title: Option<Vec<u8>> = con.get(id).await.map_err(|e| {
            log::error!("Error getting title from Redis: {}", e);
            error::ErrorInternalServerError("Error getting title from Redis")
        })?;
        if let Some(title) = title {
            match response::TitleEntry::decode(&title[..]) {
                Ok(entry) => {
                    results.push(entry);
                }
                Err(_) => return Err(error::ErrorInternalServerError("Error decoding message from Redis")),
            }
        }
    }

    if results.is_empty() {
        Ok(HttpResponse::NotFound().body("No valid IDs found in Redis"))
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


    let redis_url = "redis://127.0.0.1:6379";
    let client = redis::Client::open(redis_url).map_err(|e| {
        log::error!("Error connecting to Redis: {}", e);
        std::io::Error::new(std::io::ErrorKind::Other, "Error connecting to Redis")
    })?;
    let con = client.get_async_connection().await.map_err(|e| {
        log::error!("Error getting Redis connection: {}", e);
        std::io::Error::new(std::io::ErrorKind::Other, "Error getting Redis connection")
    })?;
    
    let data = web::Data::new(AppState {
        index_map: Mutex::new(HashMap::new()),
        data_file: Mutex::new(data_file),
        redis_con: Mutex::new(con),
    });

    reload_index(data.clone()).await.unwrap();

    HttpServer::new(move || {
        App::new()
            .app_data(data.clone())
            //.route("/reload_index", web::get().to(reload_index))
            .route("/get_title_by_ids/{id}", web::get().to(get_title_by_ids))
            .route("/get_title_by_ids_redis/{id}", web::get().to(get_title_by_ids_redis))
    })
    .bind("127.0.0.1:8081")?
    .run()
    .await
}

