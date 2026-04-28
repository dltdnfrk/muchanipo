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
    // In-memory log of every JSON-line event emitted by the active Python
    // pipeline. RunProgress (or any listener that mounts after the pipeline
    // has already emitted some events) calls `get_buffered_events` on mount
    // to replay the history, then subscribes to `backend_event` for new
    // lines. Cleared whenever start_pipeline spawns a fresh child.
    event_buffer: Arc<Mutex<Vec<String>>>,
}

const EVENT_BUFFER_CAP: usize = 2000;

fn push_event_buffer(bridge: &PythonBridge, line: &str) {
    if let Ok(mut buf) = bridge.event_buffer.lock() {
        if buf.len() >= EVENT_BUFFER_CAP {
            // Drop the oldest 25% so we don't pay for many small shifts.
            let drop = EVENT_BUFFER_CAP / 4;
            buf.drain(0..drop);
        }
        buf.push(line.to_string());
    }
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
    // Reset the replay buffer for the new run so RunProgress doesn't see
    // events from a previous, unrelated pipeline.
    if let Ok(mut buf) = bridge.event_buffer.lock() {
        buf.clear();
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

    // Resolve python3 — try common locations explicitly so .app launches
    // (which start with a minimal PATH) can find it.
    let python_bin = ["/usr/local/bin/python3", "/opt/homebrew/bin/python3", "/usr/bin/python3"]
        .iter()
        .find(|p| std::path::Path::new(p).exists())
        .map(|p| p.to_string())
        .unwrap_or_else(|| "python3".to_string());

    let mut command = Command::new(&python_bin);
    command
        .args([
            "-u",  // unbuffered stdout (so events flush immediately)
            "-m",
            "muchanipo",
            "serve",
            "--topic",
            &topic,
            "--pipeline",
            pipeline_mode,
            "--no-wait",
        ])
        .current_dir(workspace_root())
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped());
    // GUI .app launches inherit a minimal PATH that won't include
    // ~/.npm-global/bin or ~/.local/bin where the user's CLIs live.
    // Pre-resolve each CLI and inject both PATH extensions and explicit
    // <NAME>_BIN env vars so the Python providers can find them no matter
    // what the parent environment looks like.
    let mut extra_path_dirs: Vec<String> = Vec::new();
    for d in candidate_user_bin_dirs() {
        if std::path::Path::new(&d).exists() {
            extra_path_dirs.push(d);
        }
    }
    let current_path = std::env::var("PATH").unwrap_or_default();
    let merged_path = if current_path.is_empty() {
        extra_path_dirs.join(":")
    } else {
        format!("{}:{}", extra_path_dirs.join(":"), current_path)
    };
    command.env("PATH", merged_path);

    for (cli_name, env_var) in [
        ("claude", "CLAUDE_BIN"),
        ("codex", "CODEX_BIN"),
        ("gemini", "GEMINI_BIN"),
        ("kimi", "KIMI_BIN"),
    ] {
        if let Some(p) = which_binary(cli_name) {
            command.env(env_var, p);
        }
    }

    if let Some(envs) = envs {
        command.envs(
            envs.into_iter()
                .filter(|(key, value)| !key.trim().is_empty() && !value.trim().is_empty()),
        );
    }

    let mut child = command
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
    let wait_app = app.clone();
    let bridge_for_wait = bridge.inner().clone();
    let bridge_for_stdout = bridge.inner().clone();

    thread::spawn(move || {
        for line in BufReader::new(stdout).lines() {
            match line {
                Ok(line) if line.trim().is_empty() => {}
                Ok(line) => {
                    push_event_buffer(&bridge_for_stdout, &line);
                    emit_backend_line(&stdout_app, &line);
                }
                Err(error) => emit_backend_event(
                    &stdout_app,
                    BackendEvent::error(format!("failed to read python stdout: {error}")),
                ),
            }
        }
    });

    thread::spawn(move || {
        use std::io::Write;
        let log_path = std::env::temp_dir().join("muchanipo-python-stderr.log");
        let mut log = std::fs::OpenOptions::new().create(true).append(true).open(&log_path).ok();
        if let Some(ref mut f) = log {
            let _ = writeln!(f, "--- new run @ {:?} ---", std::time::SystemTime::now());
        }
        for line in BufReader::new(stderr).lines() {
            match line {
                Ok(line) if line.trim().is_empty() => {}
                Ok(line) => {
                    if let Some(ref mut f) = log {
                        let _ = writeln!(f, "{}", line);
                    }
                    emit_backend_event(
                        &stderr_app,
                        BackendEvent::error(format!("python stderr: {line}")),
                    );
                }
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
                            &wait_app,
                            BackendEvent::error(format!("python pipeline exited with {status}")),
                        ),
                        Err(error) => emit_backend_event(
                            &wait_app,
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
pub async fn get_buffered_events(
    bridge: State<'_, PythonBridge>,
) -> Result<Vec<String>, String> {
    let buf = bridge.event_buffer.lock().map_err(lock_error)?;
    Ok(buf.clone())
}

#[derive(serde::Serialize)]
pub struct CliStatus {
    pub name: String,
    pub installed: bool,
    pub path: Option<String>,
    pub version: Option<String>,
    pub error: Option<String>,
}

#[tauri::command]
pub async fn check_cli_status() -> Result<Vec<CliStatus>, String> {
    let candidates = [
        ("claude", vec!["--version"]),
        ("codex", vec!["--version"]),
        ("gemini", vec!["--version"]),
        ("kimi", vec!["--version"]),
    ];
    let mut out = Vec::with_capacity(candidates.len());
    for (name, args) in &candidates {
        let path = which_binary(name);
        let mut status = CliStatus {
            name: name.to_string(),
            installed: path.is_some(),
            path: path.clone(),
            version: None,
            error: None,
        };
        if let Some(bin) = path {
            match Command::new(&bin).args(args).output() {
                Ok(o) if o.status.success() => {
                    let v = String::from_utf8_lossy(&o.stdout).trim().to_string();
                    status.version = Some(if v.is_empty() {
                        String::from_utf8_lossy(&o.stderr).trim().to_string()
                    } else {
                        v
                    });
                }
                Ok(o) => {
                    status.error = Some(
                        String::from_utf8_lossy(&o.stderr).trim().to_string(),
                    );
                }
                Err(e) => status.error = Some(e.to_string()),
            }
        }
        out.push(status);
    }
    Ok(out)
}

fn which_binary(name: &str) -> Option<String> {
    // .app launches start with a minimal PATH, so probe a few common
    // locations explicitly in addition to PATH.
    let mut candidates: Vec<String> = candidate_user_bin_dirs()
        .into_iter()
        .map(|dir| format!("{}/{}", dir, name))
        .collect();
    candidates.extend([
        format!("/usr/local/bin/{}", name),
        format!("/opt/homebrew/bin/{}", name),
    ]);
    for c in candidates.iter() {
        if std::path::Path::new(c).exists() {
            return Some(c.clone());
        }
    }
    // PATH-based fallback via `command -v`.
    let out = Command::new("/bin/sh").arg("-c").arg(format!("command -v {}", name)).output().ok()?;
    if !out.status.success() {
        return None;
    }
    let s = String::from_utf8_lossy(&out.stdout).trim().to_string();
    if s.is_empty() { None } else { Some(s) }
}

fn candidate_user_bin_dirs() -> Vec<String> {
    let mut dirs = Vec::new();
    if let Ok(home) = std::env::var("HOME") {
        let p1 = PathBuf::from(&home).join(".npm-global").join("bin");
        let p2 = PathBuf::from(&home).join(".local").join("bin");
        dirs.push(p1.to_string_lossy().to_string());
        dirs.push(p2.to_string_lossy().to_string());
    }
    dirs
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
    // CARGO_MANIFEST_DIR = .../<root>/app/muchanipo-tauri/src-tauri (the dir
    // containing Cargo.toml, NOT Cargo.toml itself). Three parent() steps
    // climb out of src-tauri → muchanipo-tauri → app → <root>.
    let manifest = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    let candidate = manifest
        .parent() // muchanipo-tauri
        .and_then(|p| p.parent()) // app
        .and_then(|p| p.parent()) // <root>
        .map(PathBuf::from);

    // Sanity-check: the resolved root should contain the muchanipo Python
    // package. If not (e.g. .app was moved), fall back to walking upward
    // from cwd and finally to cwd.
    if let Some(ref root) = candidate {
        if root.join("muchanipo").join("__init__.py").exists()
            || root.join("src").join("muchanipo").join("__init__.py").exists()
        {
            return root.clone();
        }
    }

    if let Ok(mut cwd) = std::env::current_dir() {
        loop {
            if cwd.join("muchanipo").join("__init__.py").exists() {
                return cwd;
            }
            if !cwd.pop() {
                break;
            }
        }
    }

    candidate.unwrap_or_else(|| std::env::current_dir().unwrap_or_else(|_| PathBuf::from(".")))
}

fn lock_error<T>(error: std::sync::PoisonError<T>) -> String {
    format!("python bridge state lock poisoned: {error}")
}
