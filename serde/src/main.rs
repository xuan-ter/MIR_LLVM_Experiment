use serde::{Deserialize, Serialize};
use std::time::Instant;
use std::env;

#[derive(Serialize, Deserialize, Debug, Clone)]
struct User {
    id: u64,
    name: String,
    email: String,
    is_active: bool,
    roles: Vec<String>,
    meta: MetaData,
}

#[derive(Serialize, Deserialize, Debug, Clone)]
struct MetaData {
    login_count: u32,
    last_login: String,
    preferences: std::collections::HashMap<String, String>,
}

fn main() {
    let args: Vec<String> = env::args().collect();
    let iter_count: usize = if args.len() > 1 { args[1].parse().unwrap_or(3000) } else { 3000 };

    // 1. Prepare Data
    let mut users = Vec::new();
    for i in 0..3000 {
        let mut prefs = std::collections::HashMap::new();
        prefs.insert("theme".to_string(), "dark".to_string());
        prefs.insert("lang".to_string(), "en".to_string());
        
        users.push(User {
            id: i as u64,
            name: format!("User {}", i),
            email: format!("user{}@example.com", i),
            is_active: i % 2 == 0,
            roles: vec!["admin".to_string(), "editor".to_string()],
            meta: MetaData {
                login_count: i as u32 * 10,
                last_login: "2023-01-01T12:00:00Z".to_string(),
                preferences: prefs,
            },
        });
    }

    println!("Dataset size: {} users", users.len());
    println!("Iterations: {}", iter_count);

    // 2. Serialize Benchmark
    let start_ser = Instant::now();
    let mut json_output = String::new();
    for _ in 0..iter_count {
        json_output = serde_json::to_string(&users).unwrap();
    }
    let duration_ser = start_ser.elapsed().as_secs_f64();
    println!("Serialize Time: {:.4} s", duration_ser);
    println!("JSON Size: {:.2} MB", json_output.len() as f64 / 1_000_000.0);

    // 3. Deserialize Benchmark
    let start_de = Instant::now();
    let mut _parsed_users: Vec<User> = Vec::new();
    for _ in 0..iter_count {
        _parsed_users = serde_json::from_str(&json_output).unwrap();
    }
    let duration_de = start_de.elapsed().as_secs_f64();
    println!("Deserialize Time: {:.4} s", duration_de);
    
    let total_time = duration_ser + duration_de;
    println!("Total Time: {:.4} s", total_time);
}
