use std::{
    collections::HashMap,
    io::{BufRead, BufReader, Write},
    path::PathBuf,
    process::{Child, ChildStdin, Command, Stdio},
    sync::{Arc, Mutex},
    thread,
};

use tauri::{AppHandle, Emitter, State};

use crate::events::{BackendAction, BackendEvent};

#[derive(Clone, Default)]
pub struct PythonBridge {
    stdin: Arc<Mutex<Option<ChildStdin>>>,
    child: Arc<Mutex<Option<Child>>>,
}

#[tauri::command]
pub async fn start_pipeline(
    topic: String,
    pipeline: Option<String>,
    envs: Option<HashMap<String, String>>,
    app: AppHandle,
    bridge: State<'_, PythonBridge>,
) -> Result<(), String> {
    let topic = topic.trim().to_string();
    if topic.is_empty() {
        return Err("topic is required".to_string());
    }

    // Cleanup existing child (zombie prevention)
    {
        let mut child_lock = bridge.child.lock().map_err(lock_error)?;
        if let Some(mut c) = child_lock.take() {
            let _ = c.kill();
            let _ = c.wait();
        }
    }

    {
        let stdin = bridge.stdin.lock().map_err(lock_error)?;
        if stdin.is_some() {
            return Err("pipeline is already running".to_string());
        }
    }

    // pipeline 모드 (기본 "full" — PRD-v2 §2.1 8-stage MBB)
    let pipeline_mode = match pipeline.as_deref() {
        Some("stub") => "stub",
        _ => "full",
    };

    let mut child = Command::new("python3")
        .args([
            "-m", "muchanipo", "serve",
            "--topic", &topic,
            "--pipeline", pipeline_mode,
            "--no-wait",
        ])
        .current_dir(workspace_root())
        .envs(envs.unwrap_or_default())
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .map_err(|error| format!("failed to start python pipeline: {error}"))?;

    let stdout = child
        .stdout
        .take()
        .ok_or_else(|| "failed to open python stdout".to_string())?;
    let stderr = child
        .stderr
        .take()
        .ok_or_else(|| "failed to open python stderr".to_string())?;
    let stdin = child
        .stdin
        .take()
        .ok_or_else(|| "failed to open python stdin".to_string())?;

    {
        let mut slot = bridge.stdin.lock().map_err(lock_error)?;
        *slot = Some(stdin);
    }

    {
        let mut slot = bridge.child.lock().map_err(lock_error)?;
        *slot = Some(child);
    }

    let stdout_app = app.clone();
    let stderr_app = app.clone();
    let bridge_for_wait = bridge.inner().clone();

    thread::spawn(move || {
        for line in BufReader::new(stdout).lines() {
            match line {
                Ok(line) if line.trim().is_empty() => {}
                Ok(line) => emit_backend_line(&stdout_app, &line),
                Err(error) => emit_backend_event(
                    &stdout_app,
                    BackendEvent::error(format!("failed to read python stdout: {error}")),
                ),
            }
        }
    });

    thread::spawn(move || {
        for line in BufReader::new(stderr).lines() {
            match line {
                Ok(line) if line.trim().is_empty() => {}
                Ok(line) => emit_backend_event(
                    &stderr_app,
                    BackendEvent::error(format!("python stderr: {line}")),
                ),
                Err(error) => emit_backend_event(
                    &stderr_app,
                    BackendEvent::error(format!("failed to read python stderr: {error}")),
                ),
            }
        }
    });

    thread::spawn(move || {
        {
            let mut lock = bridge_for_wait.child.lock().map_err(lock_error).ok();
            if let Some(ref mut l) = lock {
                if let Some(ref mut c) = **l {
                    match c.wait() {
                        Ok(status) if status.success() => {}
                        Ok(status) => emit_backend_event(
                            &stdout_app,
                            BackendEvent::error(format!("python pipeline exited with {status}")),
                        ),
                        Err(error) => emit_backend_event(
                            &stdout_app,
                            BackendEvent::error(format!("failed to wait for python pipeline: {error}")),
                        ),
                    }
                }
            }
        }

        if let Ok(mut stdin) = bridge_for_wait.stdin.lock() {
            *stdin = None;
        }
    });

    Ok(())
}

#[tauri::command]
pub async fn send_action(
    action: BackendAction,
    bridge: State<'_, PythonBridge>,
) -> Result<(), String> {
    let line = action
        .into_json_line()
        .map_err(|error| format!("failed to encode backend action: {error}"))?;
    let mut stdin = bridge.stdin.lock().map_err(lock_error)?;
    let stdin = stdin
        .as_mut()
        .ok_or_else(|| "pipeline is not running".to_string())?;

    stdin
        .write_all(line.as_bytes())
        .and_then(|_| stdin.flush())
        .map_err(|error| format!("failed to write backend action: {error}"))
}

fn emit_backend_line(app: &AppHandle, line: &str) {
    match BackendEvent::from_json_line(line) {
        Ok(event) => emit_backend_event(app, event),
        Err(error) => emit_backend_event(
            app,
            BackendEvent::error(format!("invalid backend event JSON: {error}; line={line}")),
        ),
    }
}

fn emit_backend_event(app: &AppHandle, event: BackendEvent) {
    if let Err(error) = app.emit("backend_event", event) {
        eprintln!("failed to emit backend_event: {error}");
    }
}

fn workspace_root() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .and_then(|path| path.parent())
        .and_then(|path| path.parent())
        .and_then(|path| path.parent())
        .map(PathBuf::from)
        .unwrap_or_else(|| std::env::current_dir().unwrap_or_else(|_| PathBuf::from(".")))
}

fn lock_error<T>(error: std::sync::PoisonError<T>) -> String {
    format!("python bridge state lock poisoned: {error}")
}
