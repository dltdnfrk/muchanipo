// Prevents additional console window on Windows in release.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod events;
mod python_bridge;

use python_bridge::{check_cli_status, get_buffered_events, send_action, start_pipeline, PythonBridge};

#[tauri::command]
fn ping() -> &'static str {
    "pong"
}

fn main() {
    tauri::Builder::default()
        .manage(PythonBridge::default())
        .invoke_handler(tauri::generate_handler![ping, start_pipeline, send_action, check_cli_status, get_buffered_events])
        .run(tauri::generate_context!())
        .expect("error while running Muchanipo Tauri app");
}
