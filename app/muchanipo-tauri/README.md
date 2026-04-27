# Muchanipo Tauri App

Tauri 2 desktop shell for Muchanipo (Pake-style — system WebView, small binary).

## Stack

- Tauri 2 (Rust shell, system WebView)
- Vite + React 18 + TypeScript (frontend)
- Subprocess bridge to `python3 -m muchanipo serve` (worker-3, follow-up)

## Prerequisites

- Node 18+ and npm
- Rust 1.77+ (`rustup`)
- macOS: Xcode Command Line Tools (`xcode-select --install`)

## Run (dev)

```bash
cd app/muchanipo-tauri
npm install
npm run tauri dev
```

A native macOS window titled **Muchanipo** opens with a blank React screen.

## Build (release)

```bash
cd app/muchanipo-tauri
npm install
npm run tauri build
# → src-tauri/target/release/bundle/macos/Muchanipo.app
```

## Layout

```
app/muchanipo-tauri/
├── package.json           # Vite + React + Tauri CLI
├── Cargo.toml             # Cargo workspace
├── index.html
├── src/                   # React frontend
│   ├── main.tsx
│   └── App.tsx
└── src-tauri/             # Rust backend
    ├── Cargo.toml
    ├── build.rs
    ├── tauri.conf.json
    ├── capabilities/default.json
    └── src/main.rs
```
