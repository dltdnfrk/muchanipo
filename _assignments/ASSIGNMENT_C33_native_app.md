# C33 — Muchanipo Native macOS App (Phase 1: AppKit shell, libghostty 후속)

**작성:** 2026-04-27
**선행:** C31+C32 lifecycle 모듈 완료 (321 PASS)
**도구:** GitButler 4 lanes × 2 claude + 2 codex
**원칙:** Phase 1 — libghostty 없이 native shell. 추후 polish.

## Stack

```
┌─────────────────────────────────────────┐
│ Swift + AppKit native macOS app         │
│   app/Muchanipo/                        │
│   - Xcode project (Swift 5.9+)          │
│   - macOS 14+ deployment target          │
│   - NSWindow + NSStackView (Phase 1)    │
│   - NSTextView for terminal output      │
│   - libghostty integration: Phase 2     │
└─────────────────────────────────────────┘
              ↓ subprocess + Pipe
┌─────────────────────────────────────────┐
│ Python: muchanipo                       │
│   python3 -m muchanipo serve            │
│   stdout: JSON Lines (one event/line)   │
│   stdin: user response (interview ans)  │
└─────────────────────────────────────────┘
```

## JSON Line Protocol

각 event 1 line, 형식:

```json
{"event": "phase_change", "phase": "INTERVIEW", "data": {...}}
{"event": "interview_question", "data": {"q_id": "Q1", "text": "...", "options": [...]}}
{"event": "council_round_start", "round": 3, "layer": "L3_customer_jtbd"}
{"event": "council_persona_token", "persona": "이준혁", "delta": "TAM 200..."}
{"event": "council_round_done", "round": 3, "score": 72}
{"event": "report_chunk", "section": "executive_summary", "markdown": "..."}
{"event": "done", "report_path": "/path/to/REPORT.md"}
{"event": "error", "message": "..."}
```

User response (Swift → Python via stdin):
```json
{"action": "interview_answer", "q_id": "Q1", "answer": "A"}
{"action": "approve_designdoc"}
{"action": "abort"}
```

---

## Worker 1 (claude) — `c33-backend-protocol`

**목표:** `python3 -m muchanipo serve` CLI + JSON line streaming.

**파일:**
- 신설: `src/muchanipo/__init__.py`, `src/muchanipo/__main__.py`
- 신설: `src/muchanipo/server.py` — argparse + event emitter
- 신설: `src/muchanipo/events.py` — Event dataclass + JSON serializer
- 수정: `pyproject.toml` — `[project.scripts] muchanipo = "muchanipo.__main__:main"` (있으면)
- 신설: `tests/test_muchanipo_server.py` — subprocess + JSON line parsing 검증

**Acceptance:**
- `python3 -m muchanipo serve --topic "test"` 실행 시 stdout으로 phase_change 이벤트들 흐름
- stdin에 `{"action": "interview_answer", ...}` 보내면 다음 phase 진행
- 기존 321 PASS 유지
- 신규 5+ tests

**완료 표시:** `touch _research/.c33-locks/worker-1.done`

---

## Worker 2 (claude) — `c33-swift-app-shell`

**목표:** Xcode project + minimal NSWindow + subprocess launcher.

**파일:**
- 신설: `app/Muchanipo/Muchanipo.xcodeproj/` (Xcode project)
- 신설: `app/Muchanipo/Sources/Muchanipo/AppDelegate.swift` — NSApplicationMain
- 신설: `app/Muchanipo/Sources/Muchanipo/MainWindow.swift` — NSWindowController + NSStackView
- 신설: `app/Muchanipo/Sources/Muchanipo/PythonRunner.swift` — Process + Pipe (NSPipe) wrapper
- 신설: `app/Muchanipo/Package.swift` — SwiftPM manifest (Swift 5.9, macOS 14+)
- 신설: `app/Muchanipo/README.md` — Xcode 빌드 가이드 (사용자가 Xcode 열고 빌드)

**Acceptance:**
- Xcode 열면 빌드 가능 (Cmd+R)
- 창 뜨고 textarea (NSTextView) + "▶ 시작" 버튼
- 버튼 클릭 시 PythonRunner가 `python3 -m muchanipo serve --topic "..."` 실행 → stdout 받아 NSTextView에 append
- libghostty 없이 — Phase 2에서 추가

**완료 표시:** `touch _research/.c33-locks/worker-2.done`

---

## Worker 3 (codex) — `c33-ipc-bridge`

**목표:** Swift PythonRunner의 JSON line parser + dispatcher.

**파일:**
- 신설: `app/Muchanipo/Sources/Muchanipo/Event.swift` — Codable enum (Backend Worker 1 event schema와 1:1)
- 신설: `app/Muchanipo/Sources/Muchanipo/EventStream.swift` — AsyncSequence over Pipe stdout
- 신설: `app/Muchanipo/Sources/Muchanipo/Action.swift` — Codable (Backend가 받을 JSON)
- 수정: `PythonRunner.swift` — EventStream 통합

**Acceptance:**
- Backend가 보내는 모든 event 타입 Decodable
- AsyncSequence 사용한 streaming consume (`for await event in stream`)
- 사용자 액션을 stdin에 JSON line으로 send

**완료 표시:** `touch _research/.c33-locks/worker-3.done`

---

## Worker 4 (codex) — `c33-ui-views`

**목표:** Interview AskUserQuestion view + REPORT.md viewer.

**파일:**
- 신설: `app/Muchanipo/Sources/Muchanipo/Views/InterviewView.swift` — NSStackView 기반 Q + 선택지 (NSButton radio group)
- 신설: `app/Muchanipo/Sources/Muchanipo/Views/CouncilProgressView.swift` — round-by-round progress (Phase 1: simple list, Phase 2: ghostty pane)
- 신설: `app/Muchanipo/Sources/Muchanipo/Views/ReportView.swift` — NSTextView + AttributedString markdown render (Phase 2: Mermaid SVG)
- 신설: `app/Muchanipo/Sources/Muchanipo/Views/MarkdownRenderer.swift` — Markdown → AttributedString helper

**Acceptance:**
- Interview event 받으면 InterviewView 자동 표시 — 사용자 선택 후 Action stdin으로 send
- Council event 받으면 CouncilProgressView 업데이트
- report_chunk event 받으면 ReportView에 incremental render

**완료 표시:** `touch _research/.c33-locks/worker-4.done`

---

## 공통 검증

```bash
# Backend
python3 -m pytest tests/ -q          # 321 + 신규 → PASS
python3 -m muchanipo serve --topic "test" | head -5   # JSON line 흐름

# Swift (사용자 환경에서 직접)
open app/Muchanipo/Muchanipo.xcodeproj
# Cmd+R 빌드 → 창 뜨면 OK
```

## 종료

4 worker.done 차면 메인이 push + 4 PR + 머지. 사용자가 Xcode에서 빌드 시도.

## Phase 2 (후속, 별도 sprint)
- libghostty XCFramework 빌드 + GhosttyKit 통합
- Council multi-pane (10 layer = 10 ghostty pane)
- Mermaid SVG 정적 렌더 (mermaid-cli subprocess)
- vault sidebar
