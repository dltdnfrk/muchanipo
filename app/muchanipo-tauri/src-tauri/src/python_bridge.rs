use std::{
    collections::HashMap,
    io::{BufRead, BufReader, Read, Write},
    path::{Path, PathBuf},
    process::{Child, ChildStdin, Command, Stdio},
    sync::{Arc, Mutex},
    thread,
    time::{Duration, Instant},
};

use serde_json::Value;
use tauri::{AppHandle, Emitter, State};

use crate::events::{BackendAction, BackendEvent};

#[derive(Clone, Default)]
pub struct PythonBridge {
    stdin: Arc<Mutex<Option<ChildStdin>>>,
    child: Arc<Mutex<Option<Child>>>,
    child_pid: Arc<Mutex<Option<u32>>>,
    child_started_at: Arc<Mutex<Option<Instant>>>,
    last_event_at: Arc<Mutex<Option<Instant>>>,
    active_app_run_id: Arc<Mutex<Option<String>>>,
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

fn mark_backend_event_seen(bridge: &PythonBridge) {
    if let Ok(mut last_event_at) = bridge.last_event_at.lock() {
        *last_event_at = Some(Instant::now());
    }
}

#[tauri::command]
pub async fn start_pipeline(
    topic: String,
    pipeline: Option<String>,
    depth: Option<String>,
    app_run_id: Option<String>,
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
    if let Ok(mut last_event_at) = bridge.last_event_at.lock() {
        *last_event_at = None;
    }
    if let Ok(mut started_at) = bridge.child_started_at.lock() {
        *started_at = None;
    }
    if let Ok(mut pid) = bridge.child_pid.lock() {
        *pid = None;
    }
    if let Ok(mut active_app_run_id) = bridge.active_app_run_id.lock() {
        *active_app_run_id = None;
    }
    // If we synchronously killed the previous child above, do not wait for the
    // background waiter thread to eventually close the old stdin handle. A
    // quick consecutive run from the UI should start cleanly rather than be
    // misclassified as "already running" by stale bridge state.
    if let Ok(mut stdin) = bridge.stdin.lock() {
        *stdin = None;
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
    let research_depth = normalize_pipeline_depth(depth.as_deref())?;
    let app_run_id = normalize_app_run_id(app_run_id.as_deref());

    // Resolve python3 by capability, not just existence: GUI .app launches
    // may find a Homebrew Python that lacks the project dependency set.
    let python_bin = resolve_python_bin()?;

    let mut command = Command::new(&python_bin);
    command
        .args(pipeline_command_args(&topic, pipeline_mode, research_depth))
        .current_dir(workspace_root())
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped());
    // GUI .app launches inherit a minimal PATH that won't include
    // ~/.npm-global/bin or ~/.local/bin where the user's CLIs live.
    // Pre-resolve each CLI and inject both PATH extensions and explicit
    // <NAME>_BIN env vars so the Python providers can find them no matter
    // what the parent environment looks like.
    command.env("PATH", merged_cli_path());
    command.env("MUCHANIPO_APP_RUN_ID", &app_run_id);

    for (cli_name, env_var) in [
        ("claude", "CLAUDE_BIN"),
        ("codex", "CODEX_BIN"),
        ("gemini", "GEMINI_BIN"),
        ("kimi", "KIMI_BIN"),
        ("opencode", "OPENCODE_BIN"),
    ] {
        if let Some(p) = which_binary(cli_name) {
            command.env(env_var, p);
        }
    }

    if let Some(envs) = envs {
        command.envs(sanitize_renderer_envs(envs)?);
    }

    let mut child = command
        .spawn()
        .map_err(|error| format!("failed to start python pipeline: {error}"))?;
    let child_pid = child.id();

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
        let mut slot = bridge.active_app_run_id.lock().map_err(lock_error)?;
        *slot = Some(app_run_id.clone());
    }
    {
        let mut slot = bridge.stdin.lock().map_err(lock_error)?;
        *slot = Some(stdin);
    }

    {
        let mut slot = bridge.child.lock().map_err(lock_error)?;
        *slot = Some(child);
    }
    {
        let mut slot = bridge.child_pid.lock().map_err(lock_error)?;
        *slot = Some(child_pid);
    }
    {
        let mut slot = bridge.child_started_at.lock().map_err(lock_error)?;
        *slot = Some(Instant::now());
    }

    let stdout_app = app.clone();
    let stderr_app = app.clone();
    let wait_app = app.clone();
    let bridge_for_wait = bridge.inner().clone();
    let bridge_for_stdout = bridge.inner().clone();
    let stdout_app_run_id = app_run_id.clone();
    let stderr_app_run_id = app_run_id.clone();
    let wait_app_run_id = app_run_id.clone();

    thread::spawn(move || {
        use std::io::Write;
        let log_path = stdout_log_path_for_app_run_id(&stdout_app_run_id);
        let mut log = std::fs::OpenOptions::new()
            .create(true)
            .append(true)
            .open(&log_path)
            .ok();
        if let Some(ref mut f) = log {
            let _ = writeln!(
                f,
                "--- new run app_run_id={} @ {:?} ---",
                stdout_app_run_id,
                std::time::SystemTime::now()
            );
        }
        for line in BufReader::new(stdout).lines() {
            match line {
                Ok(line) if line.trim().is_empty() => {}
                Ok(line) => {
                    if let Some(ref mut f) = log {
                        let _ = writeln!(f, "{}", line);
                    }
                    mark_backend_event_seen(&bridge_for_stdout);
                    if let Some(tagged_line) =
                        emit_backend_line(&stdout_app, &line, &stdout_app_run_id)
                    {
                        if should_buffer_backend_line(&line) {
                            push_event_buffer(&bridge_for_stdout, &tagged_line);
                        }
                    }
                }
                Err(error) => emit_backend_event(
                    &stdout_app,
                    with_app_run_id(
                        BackendEvent::error(format!("failed to read python stdout: {error}")),
                        &stdout_app_run_id,
                    ),
                ),
            }
        }
    });

    thread::spawn(move || {
        use std::io::Write;
        let log_path = stderr_log_path_for_app_run_id(&stderr_app_run_id);
        let mut log = std::fs::OpenOptions::new()
            .create(true)
            .append(true)
            .open(&log_path)
            .ok();
        if let Some(ref mut f) = log {
            let _ = writeln!(
                f,
                "--- new run app_run_id={} @ {:?} ---",
                stderr_app_run_id,
                std::time::SystemTime::now()
            );
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
                        with_app_run_id(stderr_line_to_backend_event(&line), &stderr_app_run_id),
                    );
                }
                Err(error) => emit_backend_event(
                    &stderr_app,
                    with_app_run_id(
                        BackendEvent::error(format!("failed to read python stderr: {error}")),
                        &stderr_app_run_id,
                    ),
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
                            with_app_run_id(
                                BackendEvent::error(format!(
                                    "python pipeline exited with {status}"
                                )),
                                &wait_app_run_id,
                            ),
                        ),
                        Err(error) => emit_backend_event(
                            &wait_app,
                            with_app_run_id(
                                BackendEvent::error(format!(
                                    "failed to wait for python pipeline: {error}"
                                )),
                                &wait_app_run_id,
                            ),
                        ),
                    }
                }
            }
        }

        clear_runtime_state_for_app_run_id(&bridge_for_wait, &wait_app_run_id);
    });

    Ok(())
}

fn clear_runtime_state_for_app_run_id(bridge: &PythonBridge, app_run_id: &str) {
    let Ok(mut active_app_run_id) = bridge.active_app_run_id.lock() else {
        return;
    };
    if active_app_run_id.as_deref() != Some(app_run_id) {
        return;
    }

    if let Ok(mut stdin) = bridge.stdin.lock() {
        *stdin = None;
    }
    if let Ok(mut pid) = bridge.child_pid.lock() {
        *pid = None;
    }
    if let Ok(mut started_at) = bridge.child_started_at.lock() {
        *started_at = None;
    }
    *active_app_run_id = None;
}

fn normalize_pipeline_depth(depth: Option<&str>) -> Result<&'static str, String> {
    match depth.map(str::trim).filter(|value| !value.is_empty()) {
        None => Ok("deep"),
        Some("shallow") => Ok("shallow"),
        Some("deep") => Ok("deep"),
        Some("max") => Ok("max"),
        Some(other) => Err(format!(
            "unsupported research depth: {other}; expected shallow, deep, or max"
        )),
    }
}

fn pipeline_command_args(topic: &str, pipeline_mode: &str, research_depth: &str) -> Vec<String> {
    [
        "-u",
        "-m",
        "muchanipo",
        "serve",
        "--topic",
        topic,
        "--pipeline",
        pipeline_mode,
        "--depth",
        research_depth,
    ]
    .iter()
    .map(|value| (*value).to_string())
    .collect()
}

fn sanitize_renderer_envs(envs: HashMap<String, String>) -> Result<Vec<(String, String)>, String> {
    let mut out = Vec::new();
    for (key, value) in envs {
        let key = key.trim().to_string();
        let value = value.trim().to_string();
        if key.is_empty() || value.is_empty() {
            continue;
        }
        if !is_allowed_renderer_env(&key) {
            return Err(format!("unsupported pipeline env from renderer: {key}"));
        }
        if is_boolean_renderer_env(&key) && !is_boolean_env_value(&value) {
            return Err(format!("{key} must be a boolean-like value"));
        }
        out.push((key, value));
    }
    Ok(out)
}

fn is_allowed_renderer_env(key: &str) -> bool {
    matches!(
        key,
        "MUCHANIPO_USE_CLI"
            | "OPENCODE_USE_CLI"
            | "MUCHANIPO_OFFLINE"
            | "MUCHANIPO_SOURCE_RESEARCH"
            | "MUCHANIPO_ONLINE"
            | "MUCHANIPO_REQUIRE_LIVE"
            | "MUCHANIPO_VERIFICATION_ROUTING"
            | "MUCHANIPO_API_ROUTING"
            | "MUCHANIPO_MODEL_ROUTING"
            | "MUCHANIPO_PROVIDER_CHAIN"
            | "MUCHANIPO_OPENCODE_MODEL"
            | "MUCHANIPO_INTERVIEW_COUNSELLING"
            | "MUCHANIPO_PREFER_CLI"
            | "ANTHROPIC_API_KEY"
            | "GEMINI_API_KEY"
            | "KIMI_API_KEY"
            | "OPENAI_API_KEY"
            | "OPENCODE_API_KEY"
            | "OPENCODE_GO_API_KEY"
            | "XIAOMI_MIMO_API_KEY"
            | "MIMO_API_KEY"
            | "MIMO_BASE_URL"
            | "XIAOMI_MIMO_BASE_URL"
            | "MIMO_MODEL"
            | "MUCHANIPO_MIMO_MODEL"
            | "OPENALEX_EMAIL"
            | "MUCHANIPO_CONTACT_EMAIL"
            | "UNPAYWALL_EMAIL"
            | "PLANNOTATOR_API_KEY"
            | "MUCHANIPO_VAULT_ROOT"
            | "MUCHANIPO_COUNCIL_VISUALIZER"
            | "MUCHANIPO_COUNCIL_VISUALIZER_MODEL"
    )
}

fn is_boolean_renderer_env(key: &str) -> bool {
    matches!(
        key,
        "MUCHANIPO_USE_CLI"
            | "OPENCODE_USE_CLI"
            | "MUCHANIPO_OFFLINE"
            | "MUCHANIPO_ONLINE"
            | "MUCHANIPO_REQUIRE_LIVE"
            | "MUCHANIPO_SOURCE_RESEARCH"
            | "MUCHANIPO_INTERVIEW_COUNSELLING"
            | "MUCHANIPO_PREFER_CLI"
    )
}

fn is_boolean_env_value(value: &str) -> bool {
    matches!(value, "1" | "0" | "true" | "false" | "yes" | "no")
}

fn resolve_python_bin() -> Result<String, String> {
    let candidates = python_bin_candidates();
    select_python_bin(
        &candidates,
        python_candidate_exists,
        python_imports_pipeline_deps,
    )
    .ok_or_else(|| {
        format!(
            "no Python interpreter with Muchanipo dependencies found; tried {}. \
Install project deps into one of those interpreters or set MUCHANIPO_PYTHON.",
            candidates.join(", ")
        )
    })
}

fn python_bin_candidates() -> Vec<String> {
    let mut candidates = Vec::new();
    if let Ok(override_bin) = std::env::var("MUCHANIPO_PYTHON") {
        push_unique_candidate(&mut candidates, override_bin.trim());
    }
    for candidate in [
        "python",
        "/usr/local/bin/python3",
        "/opt/homebrew/bin/python3",
        "/usr/bin/python3",
        "python3",
    ] {
        push_unique_candidate(&mut candidates, candidate);
    }
    candidates
}

fn push_unique_candidate(candidates: &mut Vec<String>, candidate: &str) {
    if !candidate.is_empty() && !candidates.iter().any(|existing| existing == candidate) {
        candidates.push(candidate.to_string());
    }
}

fn select_python_bin<F, G>(
    candidates: &[String],
    mut is_available: F,
    mut supports_pipeline: G,
) -> Option<String>
where
    F: FnMut(&str) -> bool,
    G: FnMut(&str) -> bool,
{
    candidates
        .iter()
        .filter(|candidate| is_available(candidate.as_str()))
        .find(|candidate| supports_pipeline(candidate.as_str()))
        .cloned()
}

fn python_candidate_exists(bin: &str) -> bool {
    matches!(bin, "python" | "python3") || std::path::Path::new(bin).exists()
}

fn python_imports_pipeline_deps(bin: &str) -> bool {
    Command::new(bin)
        .args(["-c", "import httpx"])
        .current_dir(workspace_root())
        .env("PATH", merged_cli_path())
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .status()
        .map(|status| status.success())
        .unwrap_or(false)
}

#[tauri::command]
pub async fn get_buffered_events(
    app_run_id: Option<String>,
    bridge: State<'_, PythonBridge>,
) -> Result<Vec<String>, String> {
    let buf = bridge.event_buffer.lock().map_err(lock_error)?;
    let Some(app_run_id) = app_run_id
        .map(|value| value.trim().to_string())
        .filter(|value| !value.is_empty())
    else {
        return Ok(buf.clone());
    };
    Ok(buf
        .iter()
        .filter(|line| backend_line_matches_app_run_id(line, &app_run_id))
        .cloned()
        .collect())
}

#[derive(serde::Serialize)]
pub struct PipelineRuntimeStatus {
    pub running: bool,
    pub stdin_open: bool,
    pub child_tracked: bool,
    pub buffered_event_count: usize,
    pub child_pid: Option<u32>,
    pub app_run_id: Option<String>,
    pub runtime_age_ms: Option<u128>,
    pub last_event_elapsed_ms: Option<u128>,
    pub app_binary_path: Option<String>,
    pub workspace_root: String,
}

#[tauri::command]
pub async fn pipeline_runtime_status(
    bridge: State<'_, PythonBridge>,
) -> Result<PipelineRuntimeStatus, String> {
    let stdin_open = bridge.stdin.lock().map_err(lock_error)?.is_some();
    let mut child_running = false;
    let mut child_tracked = false;
    let mut child_exited = false;
    let mut exited_app_run_id = None;

    match bridge.child.try_lock() {
        Ok(mut child_slot) => {
            if let Some(child) = child_slot.as_mut() {
                child_tracked = true;
                match child.try_wait() {
                    Ok(Some(_status)) => {
                        child_exited = true;
                        exited_app_run_id = bridge
                            .active_app_run_id
                            .lock()
                            .ok()
                            .and_then(|active| active.clone());
                        *child_slot = None;
                    }
                    Ok(None) => {
                        child_running = true;
                    }
                    Err(_error) => {
                        child_tracked = true;
                    }
                }
            }
        }
        Err(_error) => {
            // The wait thread holds this lock while the child is active.
            // Treat an open stdin pipe as runtime evidence without blocking
            // the UI thread behind a long-running pipeline.
            child_tracked = true;
            child_running = stdin_open;
        }
    }

    if child_exited {
        if let Some(app_run_id) = exited_app_run_id.as_deref() {
            clear_runtime_state_for_app_run_id(&bridge, app_run_id);
        }
    }

    let buffered_event_count = bridge.event_buffer.lock().map_err(lock_error)?.len();
    let child_pid = *bridge.child_pid.lock().map_err(lock_error)?;
    let app_run_id = bridge.active_app_run_id.lock().map_err(lock_error)?.clone();
    let runtime_age_ms = bridge
        .child_started_at
        .lock()
        .map_err(lock_error)?
        .as_ref()
        .map(|started_at| started_at.elapsed().as_millis());
    let last_event_elapsed_ms = bridge
        .last_event_at
        .lock()
        .map_err(lock_error)?
        .as_ref()
        .map(|last_event_at| last_event_at.elapsed().as_millis());
    Ok(PipelineRuntimeStatus {
        running: child_running || (stdin_open && !child_exited),
        stdin_open: stdin_open && !child_exited,
        child_tracked,
        buffered_event_count,
        child_pid,
        app_run_id,
        runtime_age_ms,
        last_event_elapsed_ms,
        app_binary_path: std::env::current_exe()
            .ok()
            .map(|path| path.display().to_string()),
        workspace_root: workspace_root().display().to_string(),
    })
}

#[derive(serde::Serialize)]
pub struct CliStatus {
    pub name: String,
    pub installed: bool,
    pub path: Option<String>,
    pub version: Option<String>,
    pub error: Option<String>,
    pub version_timed_out: bool,
    pub pipeline_supported: bool,
    pub smoke_supported: bool,
    pub diagnosis: Option<String>,
}

#[derive(serde::Serialize)]
pub struct CliSmokeResult {
    pub name: String,
    pub ok: bool,
    pub output: Option<String>,
    pub error: Option<String>,
    pub timed_out: bool,
}

#[derive(serde::Serialize)]
pub struct CliAuthLaunch {
    pub name: String,
    pub command: String,
    pub login_command: String,
}

#[tauri::command]
pub async fn check_cli_status() -> Result<Vec<CliStatus>, String> {
    let candidates = [
        ("claude", vec!["--version"]),
        ("codex", vec!["--version"]),
        ("gemini", vec!["--version"]),
        ("kimi", vec!["--version"]),
        ("opencode", vec!["--version"]),
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
            version_timed_out: false,
            pipeline_supported: true,
            smoke_supported: true,
            diagnosis: cli_diagnosis(name).map(str::to_string),
        };
        if let Some(bin) = path {
            match run_command_with_timeout(&bin, args, None, Duration::from_secs(8)) {
                Ok(o) if o.timed_out => {
                    status.version_timed_out = true;
                    status.error = Some("version check timed out".to_string());
                }
                Ok(o) => {
                    let stdout = o.stdout.trim();
                    let stderr = o.stderr.trim();
                    if o.success {
                        status.version = Some(if stdout.is_empty() {
                            stderr.to_string()
                        } else {
                            stdout.to_string()
                        });
                    } else {
                        status.error = Some(if stderr.is_empty() {
                            format!("version check exited with {:?}", o.code)
                        } else {
                            stderr.to_string()
                        });
                    }
                }
                Err(e) => status.error = Some(e.to_string()),
            }
        }
        out.push(status);
    }
    Ok(out)
}

#[tauri::command]
pub async fn check_cli_smoke(name: String) -> Result<CliSmokeResult, String> {
    let name = name.trim().to_lowercase();
    if !matches!(
        name.as_str(),
        "claude" | "codex" | "gemini" | "kimi" | "opencode"
    ) {
        return Err(format!("unsupported CLI: {name}"));
    }
    let Some(bin) = which_binary(&name) else {
        return Ok(CliSmokeResult {
            name,
            ok: false,
            output: None,
            error: Some("binary not found".to_string()),
            timed_out: false,
        });
    };
    let (args, input): (Vec<&str>, Option<&str>) = match name.as_str() {
        "claude" => (
            vec!["-p", "--output-format", "text", "Reply with OK only."],
            None,
        ),
        "codex" => (
            vec![
                "exec",
                "--skip-git-repo-check",
                "--sandbox",
                "read-only",
                "Reply with OK only.",
            ],
            None,
        ),
        "gemini" => (
            vec!["-p", "Reply with OK only.", "-m", "gemini-2.5-flash"],
            None,
        ),
        "kimi" => (
            vec![
                "--work-dir",
                ".",
                "--print",
                "--final-message-only",
                "--input-format",
                "text",
            ],
            Some("Reply with OK only."),
        ),
        "opencode" => (
            vec![
                "run",
                "--pure",
                "--model",
                "opencode-go/kimi-k2.6",
                "--format",
                "json",
                "Reply with OK only.",
            ],
            None,
        ),
        _ => unreachable!(),
    };
    let output = run_command_with_timeout(&bin, &args, input, Duration::from_secs(90))
        .map_err(|error| error.to_string())?;
    let stdout = output.stdout.trim().to_string();
    let stderr = output.stderr.trim().to_string();
    let error = if output.timed_out {
        Some("smoke test timed out".to_string())
    } else if !output.success {
        Some(if stderr.is_empty() {
            format!("smoke test exited with {:?}", output.code)
        } else {
            stderr
        })
    } else {
        None
    };
    Ok(CliSmokeResult {
        name,
        ok: output.success && !output.timed_out,
        output: if stdout.is_empty() {
            None
        } else {
            Some(strip_kimi_resume_hint(&stdout))
        },
        error,
        timed_out: output.timed_out,
    })
}

#[tauri::command]
pub async fn open_cli_auth(name: String) -> Result<CliAuthLaunch, String> {
    let name = name.trim().to_lowercase();
    if !matches!(
        name.as_str(),
        "claude" | "codex" | "gemini" | "kimi" | "opencode"
    ) {
        return Err(format!("unsupported CLI: {name}"));
    }
    if which_binary(&name).is_none() {
        return Err(format!("{name} CLI is not installed or not on PATH"));
    }

    let login_command = cli_login_command(&name);
    let command = terminal_login_script(&name, login_command);
    let osa = format!(
        "tell application \"Terminal\"\nactivate\ndo script \"{}\"\nend tell",
        escape_applescript_string(&command)
    );
    let output = Command::new("/usr/bin/osascript")
        .arg("-e")
        .arg(osa)
        .output()
        .map_err(|error| {
            cli_auth_fallback_error(&format!("failed to open Terminal: {error}"), login_command)
        })?;

    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr).trim().to_string();
        let detail = if stderr.is_empty() {
            format!("osascript exited with {:?}", output.status.code())
        } else {
            stderr
        };
        return Err(cli_auth_fallback_error(&detail, login_command));
    }

    Ok(CliAuthLaunch {
        name,
        command,
        login_command: login_command.to_string(),
    })
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
    let out = Command::new("/bin/sh")
        .arg("-c")
        .arg(format!("command -v {}", name))
        .output()
        .ok()?;
    if !out.status.success() {
        return None;
    }
    let s = String::from_utf8_lossy(&out.stdout).trim().to_string();
    if s.is_empty() {
        None
    } else {
        Some(s)
    }
}

fn cli_login_command(name: &str) -> &'static str {
    match name {
        "claude" => "claude auth login",
        "codex" => "codex login",
        "gemini" => "gemini -i /auth",
        "kimi" => "kimi login",
        "opencode" => "opencode auth login",
        _ => unreachable!("validated by open_cli_auth"),
    }
}

fn terminal_login_script(name: &str, login_command: &str) -> String {
    format!(
        "cd {}; export PATH={}; clear; echo {}; echo {}; {}; echo; echo {}",
        shell_quote(&workspace_root().to_string_lossy()),
        shell_quote(&merged_cli_path()),
        shell_quote(&format!("Muchanipo: connecting {name} CLI")),
        shell_quote("Complete the login flow in this Terminal window."),
        login_command,
        shell_quote("When finished, return to Muchanipo and click 다시 확인 or 실호출 테스트.")
    )
}

fn cli_auth_fallback_error(detail: &str, login_command: &str) -> String {
    format!(
        "{}. Manual fallback: open Terminal, run `cd {}`, then run `{}`.",
        detail,
        shell_quote(&workspace_root().to_string_lossy()),
        login_command
    )
}

fn shell_quote(raw: &str) -> String {
    format!("'{}'", raw.replace('\'', "'\\''"))
}

fn escape_applescript_string(raw: &str) -> String {
    raw.replace('\\', "\\\\").replace('"', "\\\"")
}

struct CapturedCommand {
    success: bool,
    code: Option<i32>,
    stdout: String,
    stderr: String,
    timed_out: bool,
}

fn run_command_with_timeout(
    bin: &str,
    args: &[&str],
    input: Option<&str>,
    timeout: Duration,
) -> Result<CapturedCommand, std::io::Error> {
    let mut child = Command::new(bin)
        .args(args)
        .current_dir(workspace_root())
        .env("PATH", merged_cli_path())
        .stdin(if input.is_some() {
            Stdio::piped()
        } else {
            Stdio::null()
        })
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()?;

    let stdout_reader = child.stdout.take().map(|mut pipe| {
        thread::spawn(move || {
            let mut out = String::new();
            let _ = pipe.read_to_string(&mut out);
            out
        })
    });
    let stderr_reader = child.stderr.take().map(|mut pipe| {
        thread::spawn(move || {
            let mut out = String::new();
            let _ = pipe.read_to_string(&mut out);
            out
        })
    });

    if let Some(body) = input {
        if let Some(mut stdin) = child.stdin.take() {
            if let Err(error) = stdin.write_all(body.as_bytes()) {
                let _ = child.kill();
                let _ = child.wait();
                return Err(error);
            }
        }
    }

    let started = Instant::now();
    let mut timed_out = false;
    let status = loop {
        if let Some(status) = child.try_wait()? {
            break status;
        }
        if started.elapsed() >= timeout {
            timed_out = true;
            let _ = child.kill();
            break child.wait()?;
        }
        thread::sleep(Duration::from_millis(50));
    };

    let stdout = stdout_reader
        .and_then(|handle| handle.join().ok())
        .unwrap_or_default();
    let stderr = stderr_reader
        .and_then(|handle| handle.join().ok())
        .unwrap_or_default();

    Ok(CapturedCommand {
        success: status.success() && !timed_out,
        code: status.code(),
        stdout,
        stderr,
        timed_out,
    })
}

fn should_buffer_backend_line(line: &str) -> bool {
    // High-frequency live-only events can evict stage/final-report events
    // from the bounded replay buffer during long runs.
    !line.contains("\"event\":\"council_persona_token\"")
        && !line.contains("\"event\": \"council_persona_token\"")
        && !line.contains("\"event\":\"pipeline_heartbeat\"")
        && !line.contains("\"event\": \"pipeline_heartbeat\"")
}

fn cli_diagnosis(name: &str) -> Option<&'static str> {
    match name {
        "claude" => Some("Pipeline uses `claude -p`; run the smoke test to verify OAuth/auth."),
        "codex" => Some("Pipeline uses `codex exec`; version success does not prove native module/auth health."),
        "gemini" => Some("Pipeline uses `gemini -p`; smoke test may expose OAuth, rate-limit, or CLI flag issues."),
        "kimi" => Some("Pipeline uses `kimi --print`; run the smoke test to verify local Kimi auth."),
        "opencode" => Some("Pipeline uses `opencode run`; smoke test verifies OpenCode auth/model access."),
        _ => None,
    }
}

fn strip_kimi_resume_hint(raw: &str) -> String {
    raw.lines()
        .filter(|line| !line.trim().starts_with("To resume this session:"))
        .collect::<Vec<_>>()
        .join("\n")
        .trim()
        .to_string()
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

fn merged_cli_path() -> String {
    let mut dirs: Vec<String> = Vec::new();
    for d in candidate_user_bin_dirs() {
        if std::path::Path::new(&d).exists() {
            dirs.push(d);
        }
    }
    for d in [
        "/opt/homebrew/bin",
        "/usr/local/bin",
        "/usr/bin",
        "/bin",
        "/opt/homebrew/sbin",
        "/usr/local/sbin",
    ] {
        if std::path::Path::new(d).exists() && !dirs.iter().any(|item| item == d) {
            dirs.push(d.to_string());
        }
    }
    let current_path = std::env::var("PATH").unwrap_or_default();
    if current_path.is_empty() {
        dirs.join(":")
    } else {
        format!("{}:{}", dirs.join(":"), current_path)
    }
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

fn emit_backend_line(app: &AppHandle, line: &str, app_run_id: &str) -> Option<String> {
    match BackendEvent::from_json_line(line) {
        Ok(event) => {
            let event = with_app_run_id(event, app_run_id);
            let tagged_line = serde_json::to_string(&event).ok();
            emit_backend_event(app, event);
            tagged_line
        }
        Err(error) => {
            emit_backend_event(
                app,
                with_app_run_id(
                    BackendEvent::warning(format!(
                        "invalid backend event JSON: {error}; line={line}"
                    )),
                    app_run_id,
                ),
            );
            None
        }
    }
}

fn emit_backend_event(app: &AppHandle, event: BackendEvent) {
    if let Err(error) = app.emit("backend_event", event) {
        eprintln!("failed to emit backend_event: {error}");
    }
}

fn with_app_run_id(mut event: BackendEvent, app_run_id: &str) -> BackendEvent {
    if !app_run_id.trim().is_empty() {
        event.fields.insert(
            "app_run_id".to_string(),
            Value::String(app_run_id.to_string()),
        );
    }
    event
}

fn backend_line_matches_app_run_id(line: &str, app_run_id: &str) -> bool {
    BackendEvent::from_json_line(line)
        .ok()
        .and_then(|event| {
            event
                .fields
                .get("app_run_id")
                .and_then(|value| value.as_str())
                .map(str::to_string)
        })
        .as_deref()
        == Some(app_run_id)
}

fn stderr_line_to_backend_event(line: &str) -> BackendEvent {
    if line.starts_with("muchanipo provider_call_start ") {
        let mut fields = serde_json::Map::new();
        fields.insert("message".to_string(), Value::String(line.to_string()));
        fields.insert(
            "source".to_string(),
            Value::String("python_stderr".to_string()),
        );
        return BackendEvent {
            event: "provider_activity".to_string(),
            fields,
        };
    }
    BackendEvent::warning(format!("python stderr: {line}"))
}

fn normalize_app_run_id(value: Option<&str>) -> String {
    value
        .map(str::trim)
        .filter(|value| !value.is_empty())
        .map(ToString::to_string)
        .unwrap_or_else(|| {
            let millis = std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .map(|duration| duration.as_millis())
                .unwrap_or_default();
            format!("run-tauri-{millis}")
        })
}

fn stdout_log_path_for_app_run_id(app_run_id: &str) -> PathBuf {
    std::env::temp_dir().join(format!(
        "muchanipo-python-{}-stdout.jsonl",
        sanitize_app_run_id_for_filename(app_run_id)
    ))
}

fn stderr_log_path_for_app_run_id(app_run_id: &str) -> PathBuf {
    std::env::temp_dir().join(format!(
        "muchanipo-python-{}-stderr.log",
        sanitize_app_run_id_for_filename(app_run_id)
    ))
}

fn sanitize_app_run_id_for_filename(app_run_id: &str) -> String {
    let sanitized: String = app_run_id
        .chars()
        .map(|ch| {
            if ch.is_ascii_alphanumeric() || ch == '-' || ch == '_' {
                ch
            } else {
                '-'
            }
        })
        .collect::<String>()
        .trim_matches('-')
        .to_string();
    if sanitized.is_empty() {
        "run".to_string()
    } else {
        sanitized
    }
}

fn workspace_root() -> PathBuf {
    let configured_candidate = std::env::var_os("MUCHANIPO_WORKSPACE_ROOT")
        .or_else(|| std::env::var_os("MUCHANIPO_WORKSPACE"))
        .map(PathBuf::from);

    // CARGO_MANIFEST_DIR = .../<root>/app/muchanipo-tauri/src-tauri (the dir
    // containing Cargo.toml, NOT Cargo.toml itself). Three parent() steps
    // climb out of src-tauri → muchanipo-tauri → app → <root>.
    let manifest = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    let candidate = manifest
        .parent() // muchanipo-tauri
        .and_then(|p| p.parent()) // app
        .and_then(|p| p.parent()) // <root>
        .map(PathBuf::from);

    let cwd = std::env::current_dir().ok();
    let exe_dir = std::env::current_exe()
        .ok()
        .and_then(|path| path.parent().map(PathBuf::from));

    resolve_workspace_root(configured_candidate, candidate, cwd, exe_dir)
}

fn resolve_workspace_root(
    configured_candidate: Option<PathBuf>,
    manifest_candidate: Option<PathBuf>,
    cwd: Option<PathBuf>,
    exe_dir: Option<PathBuf>,
) -> PathBuf {
    // Sanity-check: the resolved root should contain the muchanipo Python
    // package. If not (e.g. .app was moved), fall back to walking upward from
    // the launch directory, then from the packaged executable location.
    for root in [configured_candidate.as_ref(), manifest_candidate.as_ref()]
        .into_iter()
        .flatten()
    {
        if is_workspace_root(root) {
            return root.to_path_buf();
        }
    }

    for start in [cwd.as_ref(), exe_dir.as_ref()].into_iter().flatten() {
        if let Some(root) = find_workspace_root_from(start.clone()) {
            return root;
        }
    }

    cwd.or(exe_dir)
        .or(manifest_candidate)
        .or(configured_candidate)
        .unwrap_or_else(|| PathBuf::from("."))
}

fn find_workspace_root_from(mut path: PathBuf) -> Option<PathBuf> {
    loop {
        if is_workspace_root(&path) {
            return Some(path);
        }
        if !path.pop() {
            return None;
        }
    }
}

fn is_workspace_root(path: &Path) -> bool {
    path.join("muchanipo").join("__init__.py").exists()
        || path
            .join("src")
            .join("muchanipo")
            .join("__init__.py")
            .exists()
}

fn lock_error<T>(error: std::sync::PoisonError<T>) -> String {
    format!("python bridge state lock poisoned: {error}")
}

#[cfg(test)]
mod tests {
    use super::*;

    fn env_map(entries: &[(&str, &str)]) -> HashMap<String, String> {
        entries
            .iter()
            .map(|(key, value)| ((*key).to_string(), (*value).to_string()))
            .collect()
    }

    #[test]
    fn sanitize_renderer_envs_allows_only_expected_app_keys() {
        let sanitized = sanitize_renderer_envs(env_map(&[
            ("MUCHANIPO_USE_CLI", "1"),
            ("OPENCODE_USE_CLI", "0"),
            ("MUCHANIPO_OFFLINE", "true"),
            ("MUCHANIPO_SOURCE_RESEARCH", "1"),
            ("MUCHANIPO_ONLINE", "1"),
            ("MUCHANIPO_REQUIRE_LIVE", "yes"),
            ("MUCHANIPO_VERIFICATION_ROUTING", "mimo_opencode_go_only"),
            ("MUCHANIPO_API_ROUTING", "mimo_opencode_go_only"),
            ("MUCHANIPO_MODEL_ROUTING", "mimo_opencode_go_only"),
            ("MUCHANIPO_PROVIDER_CHAIN", "opencode"),
            ("MUCHANIPO_OPENCODE_MODEL", "opencode/mimo-v2.5-pro"),
            ("MUCHANIPO_INTERVIEW_COUNSELLING", "1"),
            ("MUCHANIPO_PREFER_CLI", "0"),
            ("ANTHROPIC_API_KEY", "sk-ant"),
            ("GEMINI_API_KEY", "g-key"),
            ("KIMI_API_KEY", "k-key"),
            ("OPENAI_API_KEY", "sk-openai"),
            ("OPENCODE_API_KEY", "oc-key"),
            ("OPENCODE_GO_API_KEY", "oc-go-key"),
            ("XIAOMI_MIMO_API_KEY", "tp-key"),
            ("MIMO_BASE_URL", "https://token-plan-ams.xiaomimimo.com/v1"),
            ("MIMO_MODEL", "mimo-v2.5-pro"),
            ("OPENALEX_EMAIL", "dev@example.com"),
            ("MUCHANIPO_CONTACT_EMAIL", "dev@example.com"),
            ("UNPAYWALL_EMAIL", "dev@example.com"),
            ("PLANNOTATOR_API_KEY", "p-key"),
            ("MUCHANIPO_COUNCIL_VISUALIZER", "ollama"),
            ("MUCHANIPO_COUNCIL_VISUALIZER_MODEL", "qwen3.6-a3b:latest"),
        ]))
        .expect("expected allowlisted envs");

        assert_eq!(sanitized.len(), 28);
        assert!(sanitized.iter().any(|(key, _)| key == "MUCHANIPO_USE_CLI"));
        assert!(sanitized.iter().any(|(key, _)| key == "MUCHANIPO_OFFLINE"));
        assert!(sanitized
            .iter()
            .any(|(key, _)| key == "MUCHANIPO_SOURCE_RESEARCH"));
        assert!(sanitized.iter().any(|(key, _)| key == "MUCHANIPO_ONLINE"));
        assert!(sanitized
            .iter()
            .any(|(key, _)| key == "MUCHANIPO_REQUIRE_LIVE"));
    }

    #[test]
    fn sanitize_renderer_envs_rejects_execution_affecting_keys() {
        for key in [
            "PATH",
            "PYTHONPATH",
            "CLAUDE_BIN",
            "CODEX_BIN",
            "GEMINI_BIN",
            "OPENCODE_BIN",
            "GEMINI_ENDPOINT_TEMPLATE",
            "HTTPS_PROXY",
        ] {
            let err = sanitize_renderer_envs(env_map(&[(key, "evil")])).unwrap_err();
            assert!(err.contains("unsupported pipeline env"));
        }
    }

    #[test]
    fn sanitize_renderer_envs_rejects_invalid_cli_flag_values() {
        let err = sanitize_renderer_envs(env_map(&[("MUCHANIPO_USE_CLI", "maybe")])).unwrap_err();
        assert!(err.contains("MUCHANIPO_USE_CLI"));

        let err = sanitize_renderer_envs(env_map(&[("OPENCODE_USE_CLI", "maybe")])).unwrap_err();
        assert!(err.contains("OPENCODE_USE_CLI"));
    }

    #[test]
    fn sanitize_renderer_envs_rejects_invalid_offline_flag_values() {
        let err = sanitize_renderer_envs(env_map(&[("MUCHANIPO_OFFLINE", "maybe")])).unwrap_err();
        assert!(err.contains("MUCHANIPO_OFFLINE"));
    }

    #[test]
    fn sanitize_renderer_envs_rejects_invalid_live_flag_values() {
        let err =
            sanitize_renderer_envs(env_map(&[("MUCHANIPO_REQUIRE_LIVE", "maybe")])).unwrap_err();
        assert!(err.contains("MUCHANIPO_REQUIRE_LIVE"));
    }

    #[test]
    fn normalize_pipeline_depth_defaults_to_deep_and_accepts_valid_depths() {
        assert_eq!(normalize_pipeline_depth(None).unwrap(), "deep");
        assert_eq!(normalize_pipeline_depth(Some("")).unwrap(), "deep");
        assert_eq!(
            normalize_pipeline_depth(Some("shallow")).unwrap(),
            "shallow"
        );
        assert_eq!(normalize_pipeline_depth(Some("deep")).unwrap(), "deep");
        assert_eq!(normalize_pipeline_depth(Some("max")).unwrap(), "max");
    }

    #[test]
    fn normalize_pipeline_depth_rejects_unknown_depth() {
        let err = normalize_pipeline_depth(Some("quick")).unwrap_err();

        assert!(err.contains("unsupported research depth"));
        assert!(err.contains("shallow"));
        assert!(err.contains("deep"));
        assert!(err.contains("max"));
    }

    #[test]
    fn pipeline_command_args_include_selected_depth() {
        let args = pipeline_command_args("topic", "full", "max");

        assert_eq!(
            args,
            vec![
                "-u",
                "-m",
                "muchanipo",
                "serve",
                "--topic",
                "topic",
                "--pipeline",
                "full",
                "--depth",
                "max",
            ]
        );
    }

    #[test]
    fn select_python_bin_skips_available_but_unsupported_interpreter() {
        let candidates = vec![
            "/opt/homebrew/bin/python3".to_string(),
            "/usr/local/bin/python3".to_string(),
            "python3".to_string(),
        ];

        let selected = select_python_bin(
            &candidates,
            |_| true,
            |candidate| candidate == "/usr/local/bin/python3",
        );

        assert_eq!(selected, Some("/usr/local/bin/python3".to_string()));
    }

    #[test]
    fn select_python_bin_returns_none_when_no_candidate_supports_pipeline() {
        let candidates = vec![
            "/opt/homebrew/bin/python3".to_string(),
            "/usr/local/bin/python3".to_string(),
        ];

        let selected = select_python_bin(&candidates, |_| true, |_| false);

        assert_eq!(selected, None);
    }

    #[test]
    fn sanitize_renderer_envs_skips_empty_entries() {
        let sanitized = sanitize_renderer_envs(env_map(&[
            ("ANTHROPIC_API_KEY", ""),
            ("", "value"),
            ("GEMINI_API_KEY", "g-key"),
        ]))
        .expect("expected empty entries to be ignored");

        assert_eq!(
            sanitized,
            vec![("GEMINI_API_KEY".to_string(), "g-key".to_string())]
        );
    }

    #[test]
    fn shell_quote_handles_single_quotes() {
        assert_eq!(shell_quote("a'b"), "'a'\\''b'");
    }

    #[test]
    fn applescript_escape_handles_quotes_and_backslashes() {
        assert_eq!(
            escape_applescript_string("say \"hi\" \\ done"),
            "say \\\"hi\\\" \\\\ done"
        );
    }

    #[test]
    fn cli_login_commands_are_known() {
        assert_eq!(cli_login_command("claude"), "claude auth login");
        assert_eq!(cli_login_command("codex"), "codex login");
        assert_eq!(cli_login_command("gemini"), "gemini -i /auth");
        assert_eq!(cli_login_command("kimi"), "kimi login");
    }

    #[test]
    fn cli_auth_error_includes_manual_terminal_fallback() {
        let message = cli_auth_fallback_error("Terminal automation blocked", "codex login");

        assert!(message.contains("Terminal automation blocked"));
        assert!(message.contains("Manual fallback: open Terminal"));
        assert!(message.contains("codex login"));
        assert!(message.contains("cd "));
    }

    #[test]
    fn replay_buffer_skips_council_token_deltas() {
        assert!(!should_buffer_backend_line(
            r#"{"event":"council_persona_token","delta":"x"}"#
        ));
        assert!(!should_buffer_backend_line(
            r#"{"event":"pipeline_heartbeat","stage":"research"}"#
        ));
        assert!(should_buffer_backend_line(
            r#"{"event":"final_report","markdown":"done"}"#
        ));
    }

    #[test]
    fn backend_warning_event_shape_is_non_fatal() {
        let event = BackendEvent::warning("heads up");

        assert_eq!(event.event, "warning");
        assert_eq!(
            event.fields.get("message").and_then(|value| value.as_str()),
            Some("heads up")
        );
    }

    #[test]
    fn app_run_id_is_injected_without_overwriting_backend_run_id() {
        let event = BackendEvent::from_json_line(
            r#"{"event":"run_started","run_id":"python-run","stage":"intake"}"#,
        )
        .expect("valid backend event");

        let event = with_app_run_id(event, "run-ui-123");

        assert_eq!(
            event.fields.get("run_id").and_then(|value| value.as_str()),
            Some("python-run")
        );
        assert_eq!(
            event
                .fields
                .get("app_run_id")
                .and_then(|value| value.as_str()),
            Some("run-ui-123")
        );
    }

    #[test]
    fn app_run_scoped_stderr_log_path_is_unique_and_sanitized() {
        let first = stderr_log_path_for_app_run_id("run-one");
        let second = stderr_log_path_for_app_run_id("../run two!!");
        let stdout = stdout_log_path_for_app_run_id("../run two!!");

        assert_ne!(first, second);
        assert!(first
            .file_name()
            .and_then(|value| value.to_str())
            .unwrap_or_default()
            .contains("run-one"));
        assert_eq!(
            second.file_name().and_then(|value| value.to_str()),
            Some("muchanipo-python-run-two-stderr.log")
        );
        assert_eq!(
            stdout.file_name().and_then(|value| value.to_str()),
            Some("muchanipo-python-run-two-stdout.jsonl")
        );
    }

    #[test]
    fn stale_waiter_does_not_clear_newer_app_run_runtime_state() {
        let bridge = PythonBridge::default();
        {
            let mut active = bridge
                .active_app_run_id
                .lock()
                .expect("active app run lock");
            *active = Some("run-new".to_string());
        }
        {
            let mut pid = bridge.child_pid.lock().expect("child pid lock");
            *pid = Some(4242);
        }
        {
            let mut started_at = bridge.child_started_at.lock().expect("child started lock");
            *started_at = Some(Instant::now());
        }

        clear_runtime_state_for_app_run_id(&bridge, "run-old");

        assert_eq!(
            bridge
                .active_app_run_id
                .lock()
                .expect("active app run lock")
                .as_deref(),
            Some("run-new")
        );
        assert_eq!(
            *bridge.child_pid.lock().expect("child pid lock"),
            Some(4242)
        );
        assert!(bridge
            .child_started_at
            .lock()
            .expect("child started lock")
            .is_some());

        clear_runtime_state_for_app_run_id(&bridge, "run-new");

        assert_eq!(
            bridge
                .active_app_run_id
                .lock()
                .expect("active app run lock")
                .as_deref(),
            None
        );
        assert_eq!(*bridge.child_pid.lock().expect("child pid lock"), None);
        assert!(bridge
            .child_started_at
            .lock()
            .expect("child started lock")
            .is_none());
    }

    #[test]
    fn workspace_root_detection_accepts_src_layout() {
        let root =
            std::env::temp_dir().join(format!("muchanipo-tauri-src-layout-{}", std::process::id()));
        let package_dir = root.join("src").join("muchanipo");
        std::fs::create_dir_all(&package_dir).expect("create src package dir");
        std::fs::write(package_dir.join("__init__.py"), "").expect("write package marker");

        assert!(is_workspace_root(&root));
    }

    #[test]
    fn workspace_root_fallback_walks_up_to_src_layout() {
        let root = std::env::temp_dir().join(format!(
            "muchanipo-tauri-walk-src-layout-{}",
            std::process::id()
        ));
        let package_dir = root.join("src").join("muchanipo");
        let nested = root.join("app").join("muchanipo-tauri");
        std::fs::create_dir_all(&package_dir).expect("create src package dir");
        std::fs::create_dir_all(&nested).expect("create nested app dir");
        std::fs::write(package_dir.join("__init__.py"), "").expect("write package marker");

        assert_eq!(find_workspace_root_from(nested), Some(root));
    }

    #[test]
    fn workspace_root_resolution_uses_packaged_exe_path_when_manifest_is_stale() {
        let root = std::env::temp_dir().join(format!(
            "muchanipo-tauri-exe-src-layout-{}",
            std::process::id()
        ));
        let stale_manifest_root = std::env::temp_dir().join(format!(
            "muchanipo-tauri-stale-src-layout-{}",
            std::process::id()
        ));
        let launch_dir =
            std::env::temp_dir().join(format!("muchanipo-tauri-launch-dir-{}", std::process::id()));
        let package_dir = root.join("src").join("muchanipo");
        let exe_dir = root
            .join("target")
            .join("release")
            .join("bundle")
            .join("macos")
            .join("Muchanipo.app")
            .join("Contents")
            .join("MacOS");
        std::fs::create_dir_all(&package_dir).expect("create src package dir");
        std::fs::create_dir_all(&stale_manifest_root).expect("create stale manifest root");
        std::fs::create_dir_all(&launch_dir).expect("create launch dir");
        std::fs::create_dir_all(&exe_dir).expect("create exe dir");
        std::fs::write(package_dir.join("__init__.py"), "").expect("write package marker");

        assert_eq!(
            resolve_workspace_root(
                None,
                Some(stale_manifest_root),
                Some(launch_dir),
                Some(exe_dir)
            ),
            root
        );
    }

    #[test]
    fn workspace_root_resolution_prefers_valid_configured_workspace() {
        let root = std::env::temp_dir().join(format!(
            "muchanipo-tauri-configured-src-layout-{}",
            std::process::id()
        ));
        let stale_manifest_root = std::env::temp_dir().join(format!(
            "muchanipo-tauri-configured-stale-manifest-{}",
            std::process::id()
        ));
        let launch_dir = std::env::temp_dir().join(format!(
            "muchanipo-tauri-configured-launch-dir-{}",
            std::process::id()
        ));
        let package_dir = root.join("src").join("muchanipo");
        std::fs::create_dir_all(&package_dir).expect("create src package dir");
        std::fs::create_dir_all(&stale_manifest_root).expect("create stale manifest root");
        std::fs::create_dir_all(&launch_dir).expect("create launch dir");
        std::fs::write(package_dir.join("__init__.py"), "").expect("write package marker");

        assert_eq!(
            resolve_workspace_root(
                Some(root.clone()),
                Some(stale_manifest_root),
                Some(launch_dir),
                None
            ),
            root
        );
    }

    #[test]
    fn workspace_root_resolution_ignores_invalid_configured_workspace() {
        let root = std::env::temp_dir().join(format!(
            "muchanipo-tauri-invalid-config-src-layout-{}",
            std::process::id()
        ));
        let invalid_config = std::env::temp_dir().join(format!(
            "muchanipo-tauri-invalid-config-{}",
            std::process::id()
        ));
        let package_dir = root.join("src").join("muchanipo");
        let exe_dir = root
            .join("target")
            .join("release")
            .join("bundle")
            .join("macos")
            .join("Muchanipo.app")
            .join("Contents")
            .join("MacOS");
        std::fs::create_dir_all(&package_dir).expect("create src package dir");
        std::fs::create_dir_all(&invalid_config).expect("create invalid config dir");
        std::fs::create_dir_all(&exe_dir).expect("create exe dir");
        std::fs::write(package_dir.join("__init__.py"), "").expect("write package marker");

        assert_eq!(
            resolve_workspace_root(Some(invalid_config), None, None, Some(exe_dir)),
            root
        );
    }

    #[test]
    fn workspace_root_resolution_does_not_return_stale_manifest_candidate() {
        let stale_manifest_root = std::env::temp_dir().join(format!(
            "muchanipo-tauri-stale-manifest-{}",
            std::process::id()
        ));
        let launch_dir = std::env::temp_dir().join(format!(
            "muchanipo-tauri-launch-fallback-{}",
            std::process::id()
        ));
        std::fs::create_dir_all(&stale_manifest_root).expect("create stale manifest root");
        std::fs::create_dir_all(&launch_dir).expect("create launch dir");

        assert_eq!(
            resolve_workspace_root(
                None,
                Some(stale_manifest_root),
                Some(launch_dir.clone()),
                None
            ),
            launch_dir
        );
    }
}
