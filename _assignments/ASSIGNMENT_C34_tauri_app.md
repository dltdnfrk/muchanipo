# C34 — Muchanipo Tauri App (Pake 패턴, 가벼운 desktop)

**작성:** 2026-04-27
**선행:** C33 backend protocol (worker-1) 부분 완료. Swift native (worker-2)는 Tauri pivot으로 stack 변경.
**도구:** GitButler 4 lanes × 2 claude + 2 codex

## Stack 확정 (이유: Pake 48k★ 가벼움 + Web 재사용 + Markdown/Mermaid 친화)

```
┌─────────────────────────────────────────┐
│ Tauri 2 (Rust shell, 시스템 WebView)    │
│   app/muchanipo-tauri/                  │
│   - src-tauri/  (Rust backend)          │
│   - src/        (React + Vite frontend) │
│   - macOS .app 5-15MB binary            │
└─────────────────────────────────────────┘
              ↓ subprocess + stdin/stdout
┌─────────────────────────────────────────┐
│ Python: muchanipo (이미 C33 worker-1)   │
│   python3 -m muchanipo serve            │
│   stdout: JSON Lines                    │
└─────────────────────────────────────────┘
```

## Pre-spawn 사전 준비 (메인 thread)
1. C33의 backend protocol(worker-1, `src/muchanipo/`) keep — Tauri에서 그대로 호출
2. C33 Swift code (`app/Muchanipo/`)는 보관용으로 c33-swift-app-shell branch에만 두고 main 안 머지

---

## Worker 1 (claude) — `c34-tauri-shell`

**목표:** Tauri 2 프로젝트 scaffold + macOS 빌드 가능한 minimal shell.

**파일:**
- 신설: `app/muchanipo-tauri/Cargo.toml`
- 신설: `app/muchanipo-tauri/src-tauri/Cargo.toml`
- 신설: `app/muchanipo-tauri/src-tauri/tauri.conf.json` (Tauri 2 schema)
- 신설: `app/muchanipo-tauri/src-tauri/src/main.rs` — Tauri Builder + window
- 신설: `app/muchanipo-tauri/package.json` — Vite + React 18 + TypeScript
- 신설: `app/muchanipo-tauri/vite.config.ts`
- 신설: `app/muchanipo-tauri/tsconfig.json`
- 신설: `app/muchanipo-tauri/index.html`
- 신설: `app/muchanipo-tauri/src/main.tsx` + `App.tsx` — 빈 React 컴포넌트
- 신설: `app/muchanipo-tauri/README.md` — `npm install && npm run tauri dev` 가이드
- 추가: `.gitignore` 에 `node_modules/`, `target/`, `dist/`

**Acceptance:**
- `cd app/muchanipo-tauri && npm install && npm run tauri dev` 시 macOS native window 뜸
- 창에 "Muchanipo" 타이틀 + 빈 React 화면

**완료 표시:** `touch _research/.c34-locks/worker-1.done`

---

## Worker 2 (claude) — `c34-tauri-frontend`

**목표:** React UI scaffold — Tailwind + shadcn/ui + 기본 페이지.

**파일:**
- 신설: `app/muchanipo-tauri/tailwind.config.js`
- 신설: `app/muchanipo-tauri/postcss.config.js`
- 신설: `app/muchanipo-tauri/src/index.css` — Tailwind directives
- 신설: `app/muchanipo-tauri/src/components/ui/` — shadcn 기본 컴포넌트 (Button, Card, Input, Textarea)
- 신설: `app/muchanipo-tauri/src/pages/HomePage.tsx` — 토픽 입력 (textarea + submit)
- 신설: `app/muchanipo-tauri/src/pages/InterviewPage.tsx` — AskUserQuestion (선택지 A-D + Other input)
- 신설: `app/muchanipo-tauri/src/pages/CouncilPage.tsx` — round progress placeholder
- 신설: `app/muchanipo-tauri/src/pages/ReportPage.tsx` — markdown viewer placeholder
- 신설: `app/muchanipo-tauri/src/lib/types.ts` — Backend Event types (worker-3 schema와 일치)

**Acceptance:**
- `npm run dev` (Vite) 시 React app 정상 부팅
- HomePage → InterviewPage → CouncilPage → ReportPage 라우팅 (`react-router-dom`)
- Tailwind 적용된 버튼·카드·인풋 보임

**완료 표시:** `touch _research/.c34-locks/worker-2.done`

---

## Worker 3 (codex) — `c34-tauri-bridge`

**목표:** Rust ↔ Python subprocess bridge. Tauri command (frontend ↔ Rust ↔ Python).

**파일:**
- 신설: `app/muchanipo-tauri/src-tauri/src/python_bridge.rs` — `tokio::process::Command` + stdout streaming
- 신설: `app/muchanipo-tauri/src-tauri/src/events.rs` — Rust struct (Backend JSON line schema)
- 수정: `main.rs` — Tauri command `start_pipeline(topic) -> stream`, `send_action(action)` 등록
- 신설: `app/muchanipo-tauri/src/lib/tauri.ts` — Frontend → Rust invoke wrapper, listen events

**Acceptance:**
- HomePage textarea submit 시 → invoke `start_pipeline` → Rust가 `python3 -m muchanipo serve` spawn → stdout JSON line을 Tauri event로 frontend에 emit
- frontend가 `listen("backend_event")`로 streaming 수신
- frontend가 `invoke("send_action", {...})`로 stdin 보냄

**완료 표시:** `touch _research/.c34-locks/worker-3.done`

---

## Worker 4 (codex) — `c34-tauri-views`

**목표:** Council 실시간 모니터 + REPORT.md 렌더 (markdown + Mermaid).

**파일:**
- 신설: `app/muchanipo-tauri/src/components/CouncilMonitor.tsx` — 10 layer × round progress bar + persona token streaming
- 신설: `app/muchanipo-tauri/src/components/ReportViewer.tsx` — `react-markdown` + `remark-gfm` + `mermaid` 통합
- 신설: `app/muchanipo-tauri/src/components/InterviewQuestion.tsx` — 선택지 A-D + Other 입력 → 사용자 선택 시 `send_action`
- 수정: `app/muchanipo-tauri/package.json` — deps: react-markdown, remark-gfm, mermaid
- 수정: `CouncilPage.tsx` + `ReportPage.tsx` — 위 컴포넌트 마운트

**Acceptance:**
- Backend event "council_round_start" 수신 → CouncilMonitor 해당 round/layer 진행 표시
- Backend event "report_chunk" 수신 → ReportViewer incremental markdown render
- Mermaid 코드 블록 자동 SVG 렌더
- Backend event "interview_question" → InterviewQuestion 표시 → 사용자 선택 → send_action

**완료 표시:** `touch _research/.c34-locks/worker-4.done`

---

## 종료 후 사용자 확인

```bash
cd app/muchanipo-tauri
npm install
npm run tauri dev
```

토픽 입력 → interview → council monitor → REPORT.md까지 native window에서 동작.

빌드 (배포):
```bash
npm run tauri build
# → app/muchanipo-tauri/src-tauri/target/release/bundle/macos/Muchanipo.app
```

---

## 종료

4 worker.done 차면 메인이 push + 4 PR + 머지.
