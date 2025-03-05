use actix_web::{web, App, HttpServer, HttpResponse};
use serde::{Serialize, Deserialize};
use std::fs::File;
use std::collections::HashMap;
use parking_lot::RwLock;
use std::env;
use std::io::{Read, Seek};
use config::{Config as ConfigLoader, File as ConfigFile};
use std::error::Error;
use prost::Message;
use std::time::Instant;
use rayon::prelude::*;

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

struct AppState {
    redemtion: Data,
    idf: Data,
    search: SearchData,
}

#[derive(Debug, Deserialize)]
struct SearchQuery {
    q: String, 
    lat: Option<f64>,  // Latitude
    lon: Option<f64>,  // Longitude
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
    
}

#[derive(Debug, Deserialize, Serialize, Clone, Default)]
struct Features {
    unigram_ocurrency: i32,
    unigram_weight: f32,
    bigram_occurences: i32,
    bigram_weight: f32,
    trigram_occurences: i32,
    trigram_weight: f32,
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

fn features_calculation(results: &mut Vec<Results>, unigrams: &[String], bigrams: &[String], trigrams: &[String]) {
    results.par_iter_mut().for_each(|result| {
        let mut unigram_weight = 0.0;
        let mut unigram_count = 0;
        let mut bigram_weight = 0.0;
        let mut bigram_count = 0;
        let mut trigram_weight = 0.0;
        let mut trigram_count = 0;

        for ngram in &result.idf.unigram {
            if unigrams.contains(&ngram.word) {
                unigram_weight += ngram.weight;
                unigram_count += 1;
            }
        }

        for ngram in &result.idf.bigram {
            if bigrams.contains(&ngram.word) {
                bigram_weight += ngram.weight;
                bigram_count += 1;
            }
        }

        for ngram in &result.idf.trigram {
            if trigrams.contains(&ngram.word) {
                trigram_weight += ngram.weight;
                trigram_count += 1;
            }
        }

        result.features = Features {
            unigram_ocurrency: unigram_count,
            unigram_weight: unigram_weight,
            bigram_occurences: bigram_count,
            bigram_weight: bigram_weight,
            trigram_occurences: trigram_count,
            trigram_weight: trigram_weight,
        };
    });
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

fn get_search_results(app_state: &web::Data<AppState>, hash: u64) -> Result<Vec<Results>, Box<dyn std::error::Error>> {
    let mut results = Vec::new();

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

            results.push(Results { id, idf, document_occurences, features: Default::default() });
            read_length += 40;
        }
    } else {
        println!("Hash: {} not found in index map", hash);
    }
    Ok(results)
}

fn generate_ngrams(query: &str) -> (Vec<String>, Vec<String>, Vec<String>) {
    let words: Vec<&str> = query.split_whitespace().collect();

    let mut unigrams = Vec::new();
    let mut bigrams = Vec::new();
    let mut trigrams = Vec::new();

    for i in 0..words.len() {
        unigrams.push(words[i].to_string());

        if i < words.len() - 1 {
            bigrams.push(format!("{} {}", words[i], words[i + 1]));
        }

        if words.len() >= 3 && i < words.len() - 2 {
            trigrams.push(format!("{} {} {}", words[i], words[i + 1], words[i + 2]));
        }
    }

    (unigrams, bigrams, trigrams)
}

async fn search(
    query_param: web::Query<SearchQuery>,
    app_state: web::Data<AppState>,
) -> HttpResponse {
    let start_time = Instant::now();

    let query = &query_param.q;

    log::debug!("Query: {:?}", query);
    let (unigrams, bigrams, trigrams) = generate_ngrams(query);

    log::debug!("Unigrams: {:?}", unigrams);
    log::debug!("Bigrams: {:?}", bigrams);
    log::debug!("Trigrams: {:?}", trigrams);

    let unigram_hashes: Vec<u64> = unigrams.par_iter()
        .map(|unigram| fnv1a_64(unigram.as_bytes()))
        .collect();

    log::debug!("Unigram Hashes: {:?}", unigram_hashes);

    let mut results = Vec::new();
    for &unigram_hash in &unigram_hashes {
        if let Ok(mut unigram_results) = get_search_results(&app_state, unigram_hash) {
            results.append(&mut unigram_results);
        } else {
            log::error!("Error getting search results for hash {}", unigram_hash);
        }
    }
    
    features_calculation(&mut results, &unigrams, &bigrams, &trigrams);

    results.par_sort_unstable_by(|a, b| {
        let order_a = 
            (a.document_occurences as f32) +
            (a.features.unigram_ocurrency as f32 * a.features.unigram_weight) +
            (a.features.bigram_occurences as f32 * a.features.bigram_weight) + 
            (a.features.trigram_occurences as f32 * a.features.trigram_weight);

        let order_b = 
            (b.document_occurences as f32) +
            (b.features.unigram_ocurrency as f32 * b.features.unigram_weight) +
            (b.features.bigram_occurences as f32 * b.features.bigram_weight) + 
            (b.features.trigram_occurences as f32 * b.features.trigram_weight);

        order_b.partial_cmp(&order_a).unwrap_or(std::cmp::Ordering::Equal)
    });

    let search_results: Vec<SearchResults> = results.iter().take(20).map(|result| {
        SearchResults {
            id: result.id.clone(),
            features: result.features.clone(),
        }
    }).collect();

    log::debug!("Results len: {:?}", results.len());

    let duration = start_time.elapsed();
    log::info!("Search function took: {:?}", duration);

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

    let app_state = web::Data::new(AppState {
        redemtion: Data {
            file: "/Users/zphilipp/git/research/indexer/redemption.index".to_string(),
            index: RwLock::new(HashMap::new()),
            data: RwLock::new(File::open("/Users/zphilipp/git/research/indexer/redemption.dat")?),
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

    HttpServer::new(move || {
        let app_state_clone = app_state.clone();

        App::new()
            .app_data(app_state_clone)
            .route("/search", web::get().to(search)
        )
    })
    .bind(config.server.address)?
    .run()
    .await
}
