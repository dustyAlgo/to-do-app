//! Minimal Rust API. Internal only: reached through the authenticated FastAPI route `GET /api/rust`.

use axum::{routing::get, Json, Router};
use serde_json::{json, Value};

async fn hello() -> Json<Value> {
    Json(json!({ "message": "hello rust api" }))
}

async fn health() -> &'static str {
    "ok"
}

fn app() -> Router {
    // TODO: add more worker endpoints here
    Router::new()
        .route("/hello", get(hello))
        .route("/health", get(health))
}

#[tokio::main]
async fn main() {
    let addr = std::env::var("BIND_ADDR").unwrap_or_else(|_| "0.0.0.0:8080".to_string());
    let listener = tokio::net::TcpListener::bind(&addr)
        .await
        .expect("failed to bind");
    println!("rust-api listening on {addr}");
    axum::serve(listener, app()).await.expect("server error");
}

#[cfg(test)]
mod tests {
    use super::*;

    #[tokio::test]
    async fn hello_returns_message() {
        let Json(body) = hello().await;
        assert_eq!(body["message"], "hello rust api");
    }
}
