/**
 *
 * curl -v -H 'Content-Type: application/json' -d \
      '{"ids":["tj-nail-spa-lounge","safas-salon-day-spa-6","donelle-lamar-co-llc","zhuzhu-beauty-and-nail-salon","studio-anew-6","sea-spa-nails-salon","beach-club-salon-and-spa-6","ivona-tint-salon-and-spa-1","hello-beyoutiful-spa-10","paradise-day-spa-2-5"]}' -X POST http://127.0.0.1:8081/
*/
use actix_web::{web, App, HttpServer, Responder, Result, HttpResponse, Error, error};
use serde::Deserialize;
use serde::Serialize;
use rusqlite::{Connection};
use std::sync::{Arc, Mutex};
use std::env;
use futures::StreamExt;
use prost::Message;
use std::fs::File;
use std::io::{self, Read, Seek, SeekFrom};
use response::ResponseEntry;

pub mod response {
    include!(concat!(env!("OUT_DIR"), "/response.rs"));
}

#[derive(Serialize, Debug)]
struct TitleInfo {
    id: String,
    title_general: String,
    med_image: String,
    rating_count: i32,
    rating_value: f64,
    merchant_name: String,
    title: String,
    value: f64,
    price: f64,
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
                title: "".to_string(),
                value: 0.0,
                price: 0.0,
                discount: 0,
            })
        }).unwrap();

        titles_info = title_iter.filter_map(Result::ok).collect();
    }
    Ok(titles_info)
}


#[actix_web::main]
async fn main() -> std::io::Result<()> {
    env::set_var("RUST_LOG", "debug");
    env_logger::init();

    let connection = Connection::open("/Users/zphilipp/git/research/dealsdb/deals_db1.db").unwrap();
    let db_connection = Arc::new(Mutex::new(connection));

    HttpServer::new(move || {
        App::new()
            .app_data(web::Data::new(db_connection.clone()))
            //.route("/title", web::post().to(get_titles))
            .route("/", web::post().to(submit))
            //.route("/titles", web::post().to(submit))
    })
    .bind("127.0.0.1:8081")?
    .run()
    .await
}

