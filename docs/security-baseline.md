# Muchanipo Security Baseline

Muchanipo is not an Express web server today, so the immediate baseline is not `helmet()`. The product is a Tauri desktop shell over a local Python pipeline, so the equivalent protection lives in Tauri policy, renderer-to-backend boundaries, and local-runtime hygiene.

## Current shape

- Tauri + Vite + React desktop app under `app/muchanipo-tauri/`.
- Python CLI/event pipeline under `src/muchanipo/server.py`.
- No Express/Helmet server in the runtime path today.

## Baseline rules

### Tauri CSP

`app/muchanipo-tauri/src-tauri/tauri.conf.json` must declare a non-empty Content Security Policy instead of disabling CSP with `null`.

Required properties:

- `default-src 'self'`
- scripts limited to self
- frames, objects, forms disabled by default
- no wildcard source (`*`)
- dev HTTP allowed only for the loopback Vite server: `http://127.0.0.1:1420`
- provider/network origins must be named explicitly, not opened broadly

### Loopback-only dev server

The Vite dev server must bind to localhost only:

```text
http://127.0.0.1:1420
npm run dev -- --host 127.0.0.1
```

Do not use `0.0.0.0` unless a future reviewed remote-device workflow explicitly requires it.

### Tauri capabilities

The default desktop capability should stay minimal:

```json
[
  "core:default",
  "core:window:allow-start-dragging"
]
```

Avoid broad `shell`, `fs`, `http`, `process`, clipboard, or notification permissions in the default capability. Add narrower capabilities only when a concrete feature needs them and has tests.

### Renderer environment allowlist

Renderer-provided environment variables are execution-affecting input. The Rust bridge must keep a narrow allowlist and reject process-control keys such as:

- `PATH`
- `PYTHONPATH`
- `*_BIN`
- proxy overrides
- endpoint templates

Boolean flags must be boolean-like, and provider base URLs must be HTTP(S) URLs without newline characters. Secrets may be passed only through explicitly allowed provider keys.

### Local Python/runtime boundary

If Muchanipo later exposes an HTTP API, it should default to:

- bind to `127.0.0.1`, not all interfaces
- no debug mode in production-like runs
- strict CORS allowlist
- no token, credential, or log dumping in responses
- no broad static file serving from user/workspace directories
- server implementation headers hidden where the framework supports it

### No Express/Helmet server

If Muchanipo later adds an Express/Node server, add Helmet at the server edge:

```js
app.disable("x-powered-by");
app.use(helmet());
```

Until then, do not add unused Express/Helmet dependencies just for appearance. The active security baseline is Tauri CSP + minimal capabilities + renderer/backend boundary tests.

## Regression tests

The security baseline is guarded by:

```bash
python -m pytest tests/test_security_baseline.py -q
```

Run the Tauri/Rust checks when changing bridge security behavior:

```bash
cd app/muchanipo-tauri
RUSTUP_TOOLCHAIN=stable cargo test
```
