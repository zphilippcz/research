/**
 *
 * curl -v -H 'Content-Type: application/json' -d \
      '{"ids":["tj-nail-spa-lounge","safas-salon-day-spa-6","donelle-lamar-co-llc","zhuzhu-beauty-and-nail-salon","studio-anew-6","sea-spa-nails-salon","beach-club-salon-and-spa-6","ivona-tint-salon-and-spa-1","hello-beyoutiful-spa-10","paradise-day-spa-2-5"]}' -X POST http://127.0.0.1:8081/
*/
use actix_web::{web, App, HttpServer, Result, HttpResponse, Error, error};
use serde::Deserialize;
use serde::Serialize;
use rusqlite::{Connection};
use std::sync::{Arc, Mutex};
use std::env;
use futures::StreamExt;

#[derive(Serialize, Debug)]
struct TitleInfo {
    title: String,
    highlights: String,
    title_general: String,
    small_image: String,
    merchant_name: Option<String>,
}

type DbConnection = Arc<Mutex<Connection>>;

#[derive(Serialize, Deserialize, Debug)]
struct MyObj {
    ids: Vec<String>,
}

const MAX_SIZE: usize = 256*256; // max payload size is 256k


async fn submit(db: web::Data<DbConnection>, mut payload: web::Payload) -> Result<HttpResponse, Error> {
    log::debug!("Received request");
    // payload is a stream of Bytes objects
    let mut body = web::BytesMut::new();
    while let Some(chunk) = payload.next().await {
        let chunk = chunk?;
        // limit max size of in-memory payload
        if (body.len() + chunk.len()) > MAX_SIZE {
            return Err(error::ErrorBadRequest("overflow"));
        }
        body.extend_from_slice(&chunk);
    }

    // body is loaded, now we can deserialize serde-json
    let obj = serde_json::from_slice::<MyObj>(&body)?;
    let ids: Vec<String> = obj.ids;
    let titles_info = get_titles_internal(ids, db).await?;
    
    
    Ok(HttpResponse::Ok()
        .json(titles_info))
}

async fn get_titles_internal(ids: Vec<String>, db: web::Data<DbConnection>) -> Result<Vec<TitleInfo>, Error> {

    let conn = db.lock().unwrap_or_else(|poisoned| poisoned.into_inner());
    let mut titles_info: Vec<TitleInfo> = Vec::new();


    if !ids.is_empty() {
        let placeholders: Vec<String> = ids.iter().map(|_| "?".to_string()).collect();
        
        let query_str = format!(
            "SELECT
                d.title,
                d.highlights,
                d.title_general, 
                d.med_image,
                m.name
            FROM deals d
            LEFT JOIN merchant m
                ON d.merchant_id = m.id
            WHERE deal_id IN ({})", placeholders.join(", ")
        );

        let mut stmt = conn.prepare(&query_str).unwrap();
        let title_iter = stmt.query_map(rusqlite::params_from_iter(
            ids.iter().map(|id| id.to_string())
        ), |row| {
            Ok(TitleInfo {
                title: row.get(0)?,
                highlights: row.get(1)?,
                title_general: row.get(2)?,
                small_image: row.get(3)?,
                merchant_name: row.get(4).ok(),
            })
        }).unwrap();

        for title_info in title_iter {
            titles_info.push(title_info.unwrap());
        }
    }
    Ok(titles_info)
}

#[actix_web::main]
async fn main() -> std::io::Result<()> {
    env::set_var("RUST_LOG", "debug");
    env_logger::init();

    let connection = Connection::open("/Users/zphilipp/git/research/dealsdb/deals_db.db").unwrap();
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

