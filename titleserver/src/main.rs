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
    include!(concat!(env!("OUT_DIR"), "/response.rs"));
}

struct AppState {
    index_map: Mutex<HashMap<u32, (u32, u32)>>,
    data_file: Mutex<File>,
}

#[derive(Serialize, Debug)]
struct TitleInfo {
    id: String,
    title_general: String,
    med_image: String,
    rating_count: i32,
    rating_value: f32,
    merchant_name: String,
    value: f32,
    price: f32,
    discount: i32,
}

#[derive(Debug, Deserialize, Serialize)]
struct DocumentSearch {
    id: String,
    score: f64,
}

type DbConnection = Arc<Mutex<Connection>>;

#[derive(Serialize, Deserialize, Debug)]
struct MyObj {
    ids: Vec<DocumentSearch>,
}

const MAX_SIZE: usize = 256*256; // max payload size is 256k


async fn submit(db: web::Data<DbConnection>, mut payload: web::Payload) -> Result<HttpResponse, Error> {
    log::debug!("Received request");
    
    // payload is a stream of Bytes objects
    let mut body = web::BytesMut::new();
    while let Some(chunk) = payload.next().await {
        let chunk = chunk?;
        
        if (body.len() + chunk.len()) > MAX_SIZE {
            return Err(error::ErrorBadRequest("overflow"));
        }
        body.extend_from_slice(&chunk);
    }
    let obj = serde_json::from_slice::<MyObj>(&body)?;
    let ids: Vec<String> = obj.ids.iter().map(|doc| doc.id.clone()).collect();
    let titles_info = get_titles_internal(ids, db).await?;
    
    Ok(HttpResponse::Ok()
        .json(titles_info))
}

async fn get_titles_internal(ids: Vec<String>, db: web::Data<DbConnection>) -> Result<Vec<TitleInfo>, Error> {
    let conn = db.lock().unwrap();
    let mut titles_info: Vec<TitleInfo> = Vec::new();

    if !ids.is_empty() {
        let placeholders: Vec<String> = ids.iter().map(|_| "?".to_string()).collect();
        let query_str = format!(
            "SELECT
                d.deal_id,
                d.title_general, 
                d.med_image,
                d.rating_count,
                d.rating_value,
                m.name
            FROM deals d
            LEFT JOIN merchant m
                ON d.merchant_id = m.id
            WHERE deal_id IN ({})", placeholders.join(", ")
        );

        let mut stmt = conn.prepare(&query_str).unwrap();
        let title_iter = stmt.query_map(rusqlite::params_from_iter(ids.iter()), |row| {
            Ok(TitleInfo {
                id: row.get(0)?,
                title_general: row.get(1)?,
                med_image: row.get(2)?,
                rating_count: row.get(3)?,
                rating_value: row.get(4)?,
                merchant_name: row.get(5)?,
                value: 0.0,
                price: 0.0,
                discount: 0,
            })
        }).unwrap();

        titles_info = title_iter.filter_map(Result::ok).collect();
    }
    Ok(titles_info)
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

    let mut buffer = [0u8; 12]; // Buffer for three 32-bit values
    while let Ok(read_bytes) = file.read(&mut buffer) {
        if read_bytes < chunk_size {
            break; // If we read less than 8 bytes, we end
        }
        let id = u32::from_le_bytes([buffer[0], buffer[1], buffer[2], buffer[3]]);
        let position = u32::from_le_bytes([buffer[4], buffer[5], buffer[6], buffer[7]]);
        let length = u32::from_le_bytes([buffer[8], buffer[9], buffer[10], buffer[11]]);
        let info = (position, length);
        
        let mut index_map = state.index_map.lock().unwrap();
        index_map.insert(id, info);
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

    let connection = Connection::open("/Users/zphilipp/git/research/dealsdb/deals_db1.db").unwrap();
    let db_connection = Arc::new(Mutex::new(connection));

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
            .route("/", web::post().to(submit))
            //.route("/reload_index", web::get().to(reload_index))
            .route("/get_title_by_ids/{id}", web::get().to(get_title_by_ids))
    })
    .bind("127.0.0.1:8081")?
    .run()
    .await
}

