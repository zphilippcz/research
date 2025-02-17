
use actix_web::{web, App, HttpServer, HttpResponse};
use actix_files::Files;
use askama::Template;
use csv::ReaderBuilder;
use elasticsearch::{Elasticsearch, http::transport::{SingleNodeConnectionPool, TransportBuilder}};
use elasticsearch::cert::CertificateValidation;
use serde::{Serialize, Deserialize};
use std::fs::File as StdFile;
use std::collections::HashSet;
use std::collections::HashMap;
use std::sync::{Arc, Mutex};
use config::{Config as ConfigLoader, File as ConfigFile};
use std::error::Error;
use std::io::{Read};
use url::Url;


#[derive(Debug, Deserialize)]
struct ElasticsearchConfig {
    ca_cert: String,
    url: String,
    username: String,
    password: String,
}

#[derive(Debug, Deserialize)]
struct CsvConfig {
    file_path: String,
}

#[derive(Debug, Deserialize)]
struct ServerConfig {
    address: String,
}

#[derive(Debug, Deserialize)]
struct Config {
    elasticsearch: ElasticsearchConfig,
    csv: CsvConfig,
    server: ServerConfig,
}

struct AppState {
    es_client: Elasticsearch,
}

#[derive(Debug, Deserialize)]
struct SuggestQuery {
    q: Option<String>, // Existing query parameter for the search term
    lat: Option<f64>,  // Latitude
    lon: Option<f64>,  // Longitude
}

#[derive(Debug, Deserialize, Serialize)]
struct CsvRecord {
    text: String,
    tfidf: f64,
}
type CsvRecords = Vec<CsvRecord>;

#[derive(Debug, Deserialize, Serialize)]
struct Document {
    title: String,
    category: String,
}

#[derive(Template)]
#[template(path = "index.html")]
struct IndexTemplate;

/*
fn connect_to_sqlite() -> SqlResult<Connection> {
    let db_path = "/Users/zphilipp/notebooks/deals_db.db";
    Connection::open(db_path)
}
*/

fn haversine(lat1: f64, lon1: f64, lat2: f64, lon2: f64) -> f64 {
    // degree to radian
    let lat1 = lat1.to_radians();
    let lon1 = lon1.to_radians();
    let lat2 = lat2.to_radians();
    let lon2 = lon2.to_radians();

    // differences
    let dlat = lat2 - lat1;
    let dlon = lon2 - lon1;

    // Haversine formula
    let a = (dlat / 2.0).sin().powi(2)
            + lat1.cos() * lat2.cos() * (dlon / 2.0).sin().powi(2);
    let c = 2.0 * a.sqrt().atan2((1.0 - a).sqrt());

    // Earth radius in km
    let r = 6371.0;
    r * c
}

fn create_elasticsearch_client(config: &ElasticsearchConfig) -> Result<Elasticsearch, Box<dyn std::error::Error>> {
    let mut buf = Vec::new();
    StdFile::open(config.ca_cert.as_str())?.read_to_end(&mut buf)?;
    let cert = elasticsearch::cert::Certificate::from_pem(&buf)?;

    let conn_pool = SingleNodeConnectionPool::new(Url::parse(&config.url)?);

    let transport = TransportBuilder::new(conn_pool)
        .cert_validation(CertificateValidation::Full(cert))
        .auth(elasticsearch::auth::Credentials::Basic(config.username.clone(), config.password.clone()))
        .build()?;

    Ok(Elasticsearch::new(transport))
}

async fn query_elasticsearch(
    client: &Elasticsearch,
    query: &str
) -> Result<Vec<Document>, Box<dyn std::error::Error>> {

    let index_name = "deals";

    let search_query = serde_json::json!({
        "query": {
            "bool": {
                "should": [
                    { "match": { "title": { "query": query, "boost": 2 } } },
                    { "match": { "title_general": { "query": query, "boost": 1 } } },
                    { "match": { "highlights": { "query": query, "boost": 1 } } }
                ]
            }
        },
        "size": 10000
    });

    let response = client
        .search(elasticsearch::SearchParts::Index(&[index_name]))
        .body(search_query)
        .send()
        .await?;

    let response_body = response.json::<serde_json::Value>().await?;
    let mut documents = Vec::new();

    if let Some(hits) = response_body["hits"]["hits"].as_array() {
        for hit in hits {
            if let Some(source) = hit["_source"].as_object() {
                let title = source.get("title").and_then(|v| v.as_str()).unwrap_or("").chars().take(80).collect();
                let category = source.get("category").and_then(|v| v.as_str()).unwrap_or("").trim().to_string();
                documents.push(Document { title, category });
            }
        }
    }
    Ok(documents)
}

async fn suggest(
    query_param: web::Query<SuggestQuery>,
    unigrams_clone: web::Data<Arc<Mutex<CsvRecords>>>,
    app_state: web::Data<AppState>,
) -> HttpResponse {

    let query = query_param.q.clone().unwrap_or_default();
    let lat = query_param.lat; // Get latitude
    let lon = query_param.lon; // Get longitude
    //println!("Query: {} Lat: {} Lon: {}", query,
    //    lat.map_or("None".to_string(), |l| format!("{:.5}", l)),
    //    lon.map_or("None".to_string(), |l| format!("{:.5}", l))
    //);
    
    if query.is_empty() {
        return HttpResponse::Ok().json(serde_json::json!({
            "deals": [],
            "categories": [],
            "queries": [],
        }));
    }
     // lock the CSV records
    let records = unigrams_clone.lock().unwrap();

     // collect tuples of (text, tfidf)
    let mut matching_records: Vec<&CsvRecord> = records.iter()
         .filter(|r| r.text.starts_with(&query)) // Check if text starts with the query
         .collect();
 
     // sort matching records by tfidf value in desc. order
    matching_records.sort_by(|a, b| b.tfidf.partial_cmp(&a.tfidf).unwrap());
 
    // extract sorted texts
    let sorted_texts: Vec<String> = matching_records.iter()
         .map(|r| r.text.clone()) // extract the text
         .take(10) // take only the first 10
         .collect();

    match query_elasticsearch(&app_state.es_client, &query).await {

        Ok(documents) => {
            // Create a HashSet to track unique categories
            let mut unique_categories = HashSet::new();
            let mut deals: Vec<String> = Vec::new();
            
            let _categories: Vec<String> = documents.iter()
                .filter(|doc| !doc.category.is_empty()) // filter ocuments with empty categories text
                .take(10) // and take only the first 10
                .map(|doc| {
                    deals.push(doc.title.clone());
                    let category = doc.category.clone();
                    unique_categories.insert(category.clone()); // Insert category into the HashSet
                    category
                })
                .collect();

            let response = serde_json::json!({
                "deals": deals.iter().take(5).collect::<Vec<_>>(),
                "categories": unique_categories,
                "queries": sorted_texts
            });

            HttpResponse::Ok().json(response)
        },
        Err(err) => HttpResponse::InternalServerError().body(format!("Elasticsearch query failed: {}", err)),
    }
}

async fn index() -> HttpResponse {
    let template = IndexTemplate {};
    match template.render() {
        Ok(body) => HttpResponse::Ok().content_type("text/html").body(body),
        Err(err) => HttpResponse::InternalServerError().body(format!("Error rendering template: {}", err)),
    }
}

async fn top(unigrams_clone: web::Data<Arc<Mutex<Vec<CsvRecord>>>>) -> HttpResponse {

    let unigrams_clone = unigrams_clone.lock().unwrap(); // Handle the possibility of poisoning

    let mut sorted_records: Vec<&CsvRecord> = unigrams_clone.iter().collect();
    sorted_records.sort_by(|a, b| b.tfidf.partial_cmp(&a.tfidf).unwrap());

    // Limits for the count of records with the same first two characters
    let mut char_count: HashMap<String, usize> = HashMap::new(); // to count occurrences
    let mut filtered_records: Vec<String> = Vec::new();

    for record in sorted_records.iter() {
        let first_two_chars = record.text.chars().take(2).collect::<String>();
        // Let's count occurrences
        let count = char_count.entry(first_two_chars.clone()).or_insert(0);
        
        if *count < 1 { // If current count for the first two chars is less than 2
            filtered_records.push(record.text.clone());
            *count += 1; // Increment the count
        }
    }

    // Take only the top 10 records after filtering
    let top_records = filtered_records.into_iter().take(10).collect::<Vec<_>>();

    let response = serde_json::json!({
        "queries": top_records,
        "categories": [],
        "deals": []
    });

    HttpResponse::Ok().json(response)
}

fn parse_unigram(config: &CsvConfig) -> Result<Vec<CsvRecord>, HttpResponse> {

    let file = match StdFile::open(config.file_path.as_str()) {
        Ok(file) => file,
        Err(err) => return Err(HttpResponse::InternalServerError().body(format!("Could not open file: {}", err))),
    };
    let file = file;
    let mut rdr = ReaderBuilder::new().has_headers(true).from_reader(file);
    let records: Vec<CsvRecord> = rdr.deserialize().filter_map(Result::ok).collect();
    Ok(records)
}

fn load_config() -> Result<Config, Box<dyn Error>> {
    let settings = ConfigLoader::builder()
        .add_source(ConfigFile::with_name("config")) // Load config.toml
        .build()?;

    settings.try_deserialize().map_err(|e| Box::new(e) as Box<dyn Error>)
}

#[actix_web::main]
async fn main() -> std::io::Result<()> {

    let config: Config = load_config().expect("Failed to load configuration");
    
    let es_config = &config.elasticsearch;
    let csv_config = &config.csv;
    
    let unigrams = match parse_unigram(csv_config) {
        Ok(records) => Arc::new(Mutex::new(records)),
        Err(_err) => {
            return Err(std::io::Error::new(std::io::ErrorKind::Other, "CSV parsing failed"));
        },
    };

    let es_client = create_elasticsearch_client(es_config).expect("Failed to create Elasticsearch client");
    let app_state = web::Data::new(AppState {
        es_client,
    });

    HttpServer::new(move || {
        let unigrams_clone = Arc::clone(&unigrams);
        let app_state_clone = app_state.clone();

        App::new()
            .app_data(web::Data::new(unigrams_clone))
            .app_data(app_state_clone)
            .route("/", web::get().to(index))
            .route("/top", web::get().to(top))
            .route("/suggest", web::get().to(suggest))
            .route("/top", web::get().to(top))
            .service(Files::new("/static", "./static").show_files_listing())
    })
    .bind(config.server.address)?
    .run()
    .await
}
