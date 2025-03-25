/// This Rust program is a search server built using the Actix-web framework. It provides an HTTP endpoint for searching documents based on various criteria such as query terms, geographical coordinates, and embeddings.
///
/// The main components of the program are:
///
/// - `AppState`: Holds the application's state, including indices and data files for search, IDF, redemption, and embeddings.
/// - `SearchQuery`: Represents the query parameters for a search request.
/// - `DocumentSearch`, `Results`, `SearchResults`, `Features`: Data structures for representing search results and their features.
/// - `fnv1a_64`: Computes a 64-bit FNV-1a hash for a given byte slice.
/// - `haversine`: Calculates the Haversine distance between two geographical coordinates.
/// - `features_calculation`: Calculates features for search results based on n-grams and geographical distance.
/// - `get_idf_entry`: Retrieves an IDF entry from the IDF index.
/// - `get_search_results`: Retrieves search results from the search index based on a hash.
/// - `generate_ngrams`: Generates unigrams, bigrams, and trigrams from a query string.
/// - `fetch_embeddings`: Fetches embeddings for a query string from an external service.
/// - `search`: Handles search requests, performs the search, and returns the results as an HTTP response.
/// - `load_config`: Loads the server configuration from a file.
/// - `load_index_idf`, `load_index_embeddings`, `load_index_redemption`, `load_index_search`: Load indices from their respective files.
///
/// The `main` function initializes the server, loads the indices, and starts the HTTP server.
use actix_web::{web, App, HttpServer, HttpResponse};
use serde::{Serialize, Deserialize};
use std::fs::File;
use std::collections::HashMap;
use parking_lot::RwLock;
use std::env;
use std::io::{Read, Seek, Write};
use config::{Config as ConfigLoader, File as ConfigFile};
use std::error::Error;
use prost::Message;
use std::time::Instant;
use rayon::prelude::*;
use onnxruntime::environment::Environment;
use onnxruntime::session::Session;
use std::convert::TryFrom;

pub mod idf {
    include!(concat!(env!("OUT_DIR"), "/idf.rs"));
}

#[derive(Debug, Deserialize)]
struct CsvConfig {
    file_path: String,
    typo_dict: String,
}

#[derive(Debug, Deserialize)]
struct ServerConfig {
    address: String,
}

#[derive(Debug, Deserialize)]
struct Config {
    server: ServerConfig,
}

struct SearchData {
    file: String,
    index: RwLock<HashMap<u64, (u32, u32)>>,
    data: RwLock<File>,
}

struct Data {
    file: String,
    index: RwLock<HashMap<String, (u32, u32)>>,
    data: RwLock<File>,
}

struct RedemptionData {
    file: String,
    index: RwLock<HashMap<String, (f32, f32)>>,
}

struct EmbeddingsData {
    file: String,
    index: RwLock<HashMap<String, Vec<f64>>>,
}

struct AppState {
    redemtion: RedemptionData,
    idf: Data,
    search: SearchData,
    embeddings: EmbeddingsData,
}

#[derive(Debug, Deserialize)]
struct SearchQuery {
    q: Option<String>, 
    lat: Option<f64>,  // Latitude
    lon: Option<f64>,  // Longitude
    start: Option<i32>, // Start index
    end: Option<i32>, // End index
    limit: Option<i32>, // Limit the number of results
}

#[derive(Debug, Deserialize, Serialize, Clone)]
struct DocumentSearch {
    id:  String,
    idf: idf::IdfEntry,
    features: Features,
}

#[derive(Debug, Deserialize, Serialize, Clone)]
struct Results {
    id:  String,
    idf: idf::IdfEntry,
    document_occurences: i32,
    features: Features,
}

#[derive(Debug, Deserialize, Serialize)]
struct SearchResults {
    id: String,
    features: Features,
    //score: f32,
    //distance: f32,
    //vector_distance: f64,
}

#[derive(Debug, Deserialize, Serialize, Clone, Default)]
struct Features {
    unigram_ocurrency: i32,
    unigram_weight: f32,
    bigram_ocurrency: i32,
    bigram_weight: f32,
    trigram_ocurrency: i32,
    trigram_weight: f32,
    score: f32,
    distance: f32,
    vector_distance: f64,
}

async fn annotate(
    body: web::Json<HashMap<String, serde_json::Value>>,
) -> HttpResponse {
    let query = body.get("q").and_then(|v| v.as_str()).unwrap_or_default().to_string();
    let annotations = body.get("annotations")
        .and_then(|v| v.as_array())
        .cloned()
        .unwrap_or_else(|| Vec::new());

    //log::debug!("Query: {:?}, Annotations: {:?}", query, annotations);

    let mut file = match File::options().append(true).create(true).open("annotation.txt") {
        Ok(f) => f,
        Err(e) => {
            log::error!("Failed to open annotation file: {}", e);
            return HttpResponse::InternalServerError().finish();
        }
    };

    if let Err(e) = writeln!(
        &mut file,
        "Query: {}\nAnnotations: {}\n",
        query,
        serde_json::to_string(&annotations).unwrap_or_default()
    ) {
        log::error!("Failed to write to annotation file: {}", e);
        return HttpResponse::InternalServerError().finish();
    }

    HttpResponse::Ok().json(serde_json::json!({
        "status": "success",
        "message": "Annotation saved successfully"
    }))
}

fn fnv1a_64(data: &[u8]) -> u64 {
    const FNV_PRIME: u64 = 0x100000001b3;
    const FNV_OFFSET_BASIS: u64 = 0xCBF29CE484222325;

    let mut hash_value = FNV_OFFSET_BASIS;
    for &byte in data {
        hash_value ^= byte as u64;
        hash_value = hash_value.wrapping_mul(FNV_PRIME);
    }

    hash_value
}

fn haversine(lat1: f32, lon1: f32, lat2: f32, lon2: f32) -> f32 {
    let lat1 = lat1.to_radians();
    let lon1 = lon1.to_radians();
    let lat2 = lat2.to_radians();
    let lon2 = lon2.to_radians();
    let dlat = lat2 - lat1;
    let dlon = lon2 - lon1;
    let a = (dlat / 2.0).sin().powi(2)
            + lat1.cos() * lat2.cos() * (dlon / 2.0).sin().powi(2);
    let c = 2.0 * a.sqrt().atan2((1.0 - a).sqrt());
    let r = 6371.0;
    r * c
}



fn features_calculation(
    app_state: &web::Data<AppState>,
    results: &mut HashMap<String, Results>,
    unigrams: &[String], bigrams: &[String], trigrams: &[String],
    lat: f32, lon: f32,
    embeddings: &[f32]) {

    let start_time = Instant::now();


    results.par_iter_mut().for_each(|(_, result)| {
        let mut distance = 0.0;
        if let Some(&(lat2, lon2)) = app_state.redemtion.index.read().get(&result.id) {
            distance = haversine(lat2, lon2, lat, lon);
        }

        let mut unigram_weight = 0.0;
        let mut unigram_count = 0;
        let mut bigram_weight = 0.0;
        let mut bigram_count = 0;
        let mut trigram_weight = 0.0;
        let mut trigram_count = 0;
        let mut score = 0.0;
        let mut vector_distance = 0.0;

        // The code retrieves a document's embedding from an index,
        // compares it with another embedding, and calculates the Euclidean distance between these two embeddings.
        if let Some(documentEmbedding) = app_state.embeddings.index.read().get(&result.id) {
            for (a, b) in documentEmbedding.iter().zip(embeddings.iter()) {
                vector_distance += (a - *b as f64).powi(2);
            }
            vector_distance = vector_distance.sqrt();
        }


        for ngram in &result.idf.unigram {
            if unigrams.contains(&ngram.word) {
                unigram_weight += ngram.weight;
                unigram_count += 1;
            }
        }
        for ngram in &result.idf.bigram {
            if bigrams.contains(&ngram.word) {
                bigram_weight += ngram.weight * 10.0;
                bigram_count += 1;
            }
        }

        for ngram in &result.idf.trigram {
            if trigrams.contains(&ngram.word) {
                trigram_weight += ngram.weight * 100.0;
                trigram_count += 1;
            }
        }

        score = 1.0 / vector_distance as f32 + unigram_weight + bigram_weight + trigram_weight * 10.0 - (distance + 0.1) * 0.001;

        result.features = Features {
            unigram_ocurrency: unigram_count,
            unigram_weight: unigram_weight,
            bigram_ocurrency: bigram_count,
            bigram_weight: bigram_weight,
            trigram_ocurrency: trigram_count,
            trigram_weight: trigram_weight,
            score: score,
            distance: distance,
            vector_distance: vector_distance,
        };
    });

    let duration = start_time.elapsed();
    log::info!("features_calculation function took: {:?}", duration);
}

fn get_idf_entry(app_state: &web::Data<AppState>, id: &str) -> Result<idf::IdfEntry, Box<dyn std::error::Error>> {
    let index_map = app_state.idf.index.read();
    if let Some(&(position, length)) = index_map.get(id) {
        let mut idf_data = app_state.idf.data.write();
        let mut buffer = vec![0; length as usize];
        idf_data.seek(std::io::SeekFrom::Start(position as u64))?;
        idf_data.read_exact(&mut buffer)?;
        let idf_entry = idf::IdfEntry::decode(&*buffer)?;
        return Ok(idf_entry);
    }
    Err("ID not found in index".into())
}

fn get_search_results(app_state: &web::Data<AppState>, hash: u64) -> Result<HashMap<String, Results>, Box<dyn std::error::Error>> {
    let start_time = Instant::now();

    let mut results = HashMap::new();

    let index_map = app_state.search.index.read();
    if let Some(&(position, length)) = index_map.get(&hash) {
        log::debug!("Hash: {}, Position: {}, Length: {}", hash, position, length);

        let mut file = app_state.search.data.write();
        file.seek(std::io::SeekFrom::Start(position as u64))?;
        let mut buffer = vec![0u8; 40];
        let mut read_length = 0;

        while read_length < length {
            file.read_exact(&mut buffer)?;
            let id = String::from_utf8_lossy(&buffer[..36]).to_string();
            let document_occurences = u32::from_le_bytes([buffer[36], buffer[37], buffer[38], buffer[39]]) as i32;

            let idf = get_idf_entry(&app_state, &id)?;

            results.insert(id.clone(), Results { id, idf, document_occurences, features: Default::default() });
            read_length += 40;
        }
    } else {
        println!("Hash: {} not found in index map", hash);
    }

    let duration = start_time.elapsed();
    log::info!("get_search_results function took: {:?}", duration);

    Ok(results)
}

fn generate_ngrams(query: &str) -> (Vec<String>, Vec<String>, Vec<String>) {
    let words: Vec<&str> = query.split_whitespace().collect();

    let mut unigrams = Vec::new();
    let mut bigrams = Vec::new();
    let mut trigrams = Vec::new();

    for i in 0..words.len() {
        unigrams.push(words[i].to_string());
    }

    for i in 0..words.len() {
        for j in i + 1..words.len() {
            bigrams.push(format!("{} {}", words[i], words[j]));
        }
    }

    for i in 0..words.len() {
        for j in i + 1..words.len() {
            for k in j + 1..words.len() {
                trigrams.push(format!("{} {} {}", words[i], words[j], words[k]));
            }
        }
    }

    (unigrams, bigrams, trigrams)
}


async fn fetch_embeddings(query: &str) -> Vec<f32> {
    let start_time = Instant::now();

    let client = reqwest::Client::builder()
        .connection_verbose(true)
        .build()
        .expect("Failed to build client");

    let response = client.post("http://127.0.0.1:9999/get_embeddings/")
        .json(&serde_json::json!({ "query": query }))
        .send()
        .await;

    let embeddings = match response {
        Ok(resp) => {
            if resp.status().is_success() {
                resp.json::<Vec<f32>>().await.unwrap_or_else(|_| Vec::new())
            } else {
                Vec::new()
            }
        }
        Err(_) => Vec::new(),
    };

    let duration = start_time.elapsed();
    log::info!("fetch_embeddings function took: {:?}", duration);

    embeddings
}


async fn search(
    query_param: web::Query<SearchQuery>,
    app_state: web::Data<AppState>,
) -> HttpResponse {
    let start_time = Instant::now();

    let query = query_param.q.as_deref().unwrap_or("").to_lowercase();
    let lat = query_param.lat.unwrap_or(0.0) as f32;
    let lon = query_param.lon.unwrap_or(0.0) as f32;

    let start = query_param.start.unwrap_or(0) as i32;
    let limit = query_param.limit.unwrap_or(21) as i32;
    let end = query_param.end.unwrap_or(start + limit) as i32;

    let embeddings = fetch_embeddings(&query).await;

    //log::debug!("Embeddings: {:?}", embeddings);
    log::debug!("Query: {}, Lat: {}, Lon: {}, Limit: {}, Start: {}", query, lat, lon, limit, start);

    let (unigrams, bigrams, trigrams) = generate_ngrams(&query);

    log::debug!("Unigrams: {:?}", unigrams);
    log::debug!("Bigrams: {:?}", bigrams);
    log::debug!("Trigrams: {:?}", trigrams);

    let unigram_hashes: Vec<u64> = unigrams.par_iter()
        .map(|unigram| fnv1a_64(unigram.as_bytes()))
        .collect();

    log::debug!("Unigram Hashes: {:?}", unigram_hashes);

    let mut results = HashMap::new();
    for &unigram_hash in &unigram_hashes {
        if let Ok(unigram_results) = get_search_results(&app_state, unigram_hash) {
            log::debug!("Results for unigram hash {} len: {:?}", unigram_hash, unigram_results.len());
            results.extend(unigram_results);
        } else {
            log::error!("Error getting search results for hash {}", unigram_hash);
        }
    }

    log::debug!("Results len: {:?}", results.len());

    features_calculation(&app_state, &mut results, &unigrams, &bigrams, &trigrams, lat, lon, &embeddings);

    let mut search_results: Vec<SearchResults> = results.values()
        .map(|result| {
            SearchResults {
                id: result.id.clone(),
                features: result.features.clone(),
            }
        })
        .collect();

    search_results.sort_by(|a, b| b.features.score.partial_cmp(&a.features.score).unwrap_or(std::cmp::Ordering::Equal));

    let search_results: Vec<SearchResults> = search_results
        .into_iter()
        .skip(start as usize)
        .take(end as usize - start as usize)
        .collect();

    log::debug!("Results len: {:?}", results.len());

    let duration = start_time.elapsed();
    log::info!("search function took: {:?}", duration);

    HttpResponse::Ok().json(serde_json::json!({
        "results": search_results,
        "query": unigrams,
        "hash": unigram_hashes,
        "length": results.len(),
        "duration": format!("{:?}", duration)
    }))
}

fn load_config() -> Result<Config, Box<dyn Error>> {
    let settings = ConfigLoader::builder()
        .add_source(ConfigFile::with_name("config"))
        .build()?;

    settings.try_deserialize().map_err(|e| Box::new(e) as Box<dyn Error>)
}

async fn load_index_idf(source: &Data) -> Result<(), Box<dyn std::error::Error>> {
    log::debug!("Loading index from file: {}", source.file);

    let file_path = source.file.clone();
    let mut file = File::open(file_path).map_err(|err| {
        log::error!("Error opening index file: {}", err);
        Box::new(err) as Box<dyn std::error::Error>
    })?;
    log::debug!("Index file opened successfully");
    
    const CHUNK_SIZE: usize = 44;

    let mut buffer = vec![0u8; CHUNK_SIZE];
    while let Ok(read_bytes) = file.read(&mut buffer) {
        if read_bytes < CHUNK_SIZE {
            break;
        }
        let id = String::from_utf8_lossy(&buffer[..36]).to_string();
        let position = u32::from_le_bytes([buffer[36], buffer[37], buffer[38], buffer[39]]);
        let length = u32::from_le_bytes([buffer[40], buffer[41], buffer[42], buffer[43]]);

        let info = (position, length);
        
        let mut index_map = source.index.write();
        index_map.insert(id, info);
    }
    log::debug!("Index file successfully read.");

    Ok(())
}

async fn load_index_embeddings(source: &EmbeddingsData) -> Result<(), Box<dyn std::error::Error>> {
    log::debug!("Loading index embeddings from file: {}", source.file);

    let file_path = source.file.clone();
    let mut file = File::open(file_path).map_err(|err| {
        log::error!("Error opening index file: {}", err);
        Box::new(err) as Box<dyn std::error::Error>
    })?;
    log::debug!("Index file opened successfully");
    
    const CHUNK_SIZE: usize = 36 + 384 * 8;

    let mut buffer = vec![0u8; CHUNK_SIZE];
    while let Ok(read_bytes) = file.read(&mut buffer) {
        if read_bytes < CHUNK_SIZE {
            break;
        }
        let id = String::from_utf8_lossy(&buffer[..36]).to_string();
        let mut embedding = vec![0f64; 384];
        for i in 0..384 {
            embedding[i] = f64::from_le_bytes([
                buffer[36 + i * 8],
                buffer[36 + i * 8 + 1],
                buffer[36 + i * 8 + 2],
                buffer[36 + i * 8 + 3],
                buffer[36 + i * 8 + 4],
                buffer[36 + i * 8 + 5],
                buffer[36 + i * 8 + 6],
                buffer[36 + i * 8 + 7],
            ]);
        }
        //log::debug!("ID: {} Embedding: {:?}", id, embedding);

        let mut index_map = source.index.write();
        index_map.insert(id, embedding);
    }
    log::debug!("Index file successfully read.");

    Ok(())
}

async fn load_index_redemption(source: &RedemptionData) -> Result<(), Box<dyn std::error::Error>> {
    log::debug!("Loading index from file: {}", source.file);

    let file_path = source.file.clone();
    let mut file = File::open(file_path).map_err(|err| {
        log::error!("Error opening index file: {}", err);
        Box::new(err) as Box<dyn std::error::Error>
    })?;
    log::debug!("Index file opened successfully");
    
    const CHUNK_SIZE: usize = 44;

    let mut buffer = vec![0u8; CHUNK_SIZE];
    while let Ok(read_bytes) = file.read(&mut buffer) {
        if read_bytes < CHUNK_SIZE {
            break;
        }
        let id = String::from_utf8_lossy(&buffer[..36]).to_string();
        let lat = f32::from_le_bytes([buffer[36], buffer[37], buffer[38], buffer[39]]);
        let lon = f32::from_le_bytes([buffer[40], buffer[41], buffer[42], buffer[43]]);

        let info = (lat, lon);
        let mut index_map = source.index.write();
        index_map.insert(id, info);
    }
    log::debug!("Index file successfully read.");

    Ok(())
}

async fn load_index_search(source: &SearchData) -> Result<(), Box<dyn std::error::Error>> {
    log::debug!("Loading index from file: {}", source.file);

    let file_path = source.file.clone();
    let mut file = File::open(file_path).map_err(|err| {
        log::error!("Error opening index file: {}", err);
        Box::new(err) as Box<dyn std::error::Error>
    })?;
    log::debug!("Index file opened successfully");
    
    const CHUNK_SIZE: usize = std::mem::size_of::<(u64, u32, u32)>();

    let mut buffer = vec![0u8; CHUNK_SIZE];
    while let Ok(read_bytes) = file.read(&mut buffer) {
        if read_bytes < CHUNK_SIZE {
            break;
        }
        let kw = u64::from_le_bytes([
            buffer[0], buffer[1], buffer[2], buffer[3],
            buffer[4], buffer[5], buffer[6], buffer[7]
        ]);
        let position = u32::from_le_bytes([buffer[8], buffer[9], buffer[10], buffer[11]]);
        let length = u32::from_le_bytes([buffer[12], buffer[13], buffer[14], buffer[15]]);

        let info = (position, length);
        
        let mut index_map = source.index.write();
        index_map.insert(kw, info);
    }
    log::debug!("Index file successfully read.");

    Ok(())
}

#[actix_web::main]
async fn main() -> std::io::Result<()> {
    env_logger::init();
    env::set_var("RUST_LOG", "debug"); 

    let config: Config = load_config().expect("Failed to load configuration");
    log::debug!("Server address: {}", config.server.address);

    let environment = Environment::builder()
        .with_name("search_server")
        .build()
        .expect("Failed to create ONNX Runtime environment");

    let session = environment
        .new_session_builder()
        .map_err(|e| std::io::Error::new(std::io::ErrorKind::Other, e))?
        .with_model_from_file("/Users/zphilipp/git/research/relevance/model.onnx")
        .map_err(|e| std::io::Error::new(std::io::ErrorKind::Other, e))?;

    let app_state = web::Data::new(AppState {
        embeddings: EmbeddingsData {
            file: "/Users/zphilipp/git/research/indexer/embeddings.index".to_string(),
            index: RwLock::new(HashMap::new()),
        },
        redemtion: RedemptionData {
            file: "/Users/zphilipp/git/research/indexer/redemption.index".to_string(),
            index: RwLock::new(HashMap::new()),
        },
        idf: Data {
            file: "/Users/zphilipp/git/research/indexer/idf.index".to_string(),
            index: RwLock::new(HashMap::new()),
            data: RwLock::new(File::open("/Users/zphilipp/git/research/indexer/idf.dat")?),
        },
        search: SearchData {
            file: "/Users/zphilipp/git/research/indexer/search.index".to_string(),
            index: RwLock::new(HashMap::new()),
            data: RwLock::new(File::open("/Users/zphilipp/git/research/indexer/search.dat")?),
        },
    });
    load_index_idf(&app_state.idf).await.unwrap();
    load_index_search(&app_state.search).await.unwrap();
    load_index_redemption(&app_state.redemtion).await.unwrap();
    load_index_embeddings(&app_state.embeddings).await.unwrap();

    HttpServer::new(move || {
        let app_state_clone = app_state.clone();

        App::new()
            .app_data(app_state_clone)
            .route("/search", web::get().to(search))
            .route("/annotate", web::post().to(annotate))
        
    })
    .bind(config.server.address)?
    .run()
    .await
}
