# C29 — Issue #5~#13 Fix Sprint (4 codex workers, GitButler virtual branches)

**작성:** 2026-04-26
**선행:** PR #1, #2, #4 머지 완료 (256 PASS)
**도구:** GitButler virtual branches (`but` CLI) — 4 worker 동시 작업해도 충돌 X

---

## 사전 준비 (메인 thread가 미리 함)

이미 4 virtual branch 생성됨:
- `c29-config-rubric` ← Worker 1
- `c29-orchestrator-lock` ← Worker 2
- `c29-init-imports` ← Worker 3
- `c29-misc-fixes` ← Worker 4

`but status -fv`로 확인 가능. 모두 `gitbutler/workspace` 위에 동시 적용 상태.

---

## Worker 별 작업 분배

각 worker는 **자기 branch만 수정**. 다른 worker 영역 손대지 말 것.

### Worker 1 — `c29-config-rubric` (CRITICAL #5 + #6)

**Issue #5: 하드코딩 개인 경로 (`~/Documents/Hyunjun/`)**
- 12곳 이상 하드코딩됨
- 환경변수 `MUCHANIPO_VAULT_PATH` 도입
- 영향: `config/config.json`, `src/eval/eval-agent.py`, `src/hitl/vault-router.py`, `signoff-queue.py`, `src/migrate/v03_to_v04.py`, `muchanipo.md`, `agents/arc-wiki.md`
- helper: `src/runtime/paths.py` 신설 — `get_vault_path()` 단일 진입점

**Issue #6: 점수 체계 불일치 (40/100/13축 혼재)**
- `rubric.json`을 Single Source of Truth로
- `eval-agent.py` 40점 체계 → 100점(v2.2 13축)으로 통일
- skill 문서 `muchanipo.md`도 100점 체계로 통일

**작업 흐름:**
```bash
but mark c29-config-rubric           # 변경 → 이 branch로 라우팅
# 코드 수정
python3 -m pytest tests/ -q          # 회귀 PASS 확인
but commit -m "fix(c29-#5): hardcoded vault path → MUCHANIPO_VAULT_PATH" --status-after
but commit -m "fix(c29-#6): rubric.json SSoT — eval-agent 40→100점 통일" --status-after
touch _research/.c29-locks/worker-1.done
```

---

### Worker 2 — `c29-orchestrator-lock` (CRITICAL #7 + #8)

**Issue #7: orchestrator.py 서브스크립트 경로 모두 오류**
- `SCRIPT_DIR(src/runtime/)` 기준 → 실제 파일은 `src/ingest/`, `src/search/`, `src/council/`
- 실행 시 모든 step skip
- 수정: 프로젝트 루트 기준 상대 경로

**Issue #8: Lock 파일 TOCTOU 경쟁 조건**
- `orchestrator.py`의 `acquire_lock()` race
- 두 프로세스 동시 lock 획득 가능 → 데이터 손상
- 수정: `fcntl.flock()` 또는 `os.O_CREAT | os.O_EXCL` 원자적 lock

**작업 흐름:**
```bash
but mark c29-orchestrator-lock
# 코드 수정 + tests/test_orchestrator.py 신규
python3 -m pytest tests/ -q
but commit -m "fix(c29-#7): orchestrator subscript paths from project root" --status-after
but commit -m "fix(c29-#8): atomic lock with fcntl.flock + O_CREAT|O_EXCL" --status-after
touch _research/.c29-locks/worker-2.done
```

---

### Worker 3 — `c29-init-imports` (HIGH #10)

**Issue #10: `__init__.py` 부재 + sys.path.insert 해킹**
- src/ 하위 모든 디렉토리 `__init__.py` 없음
- 모듈 import에 `sys.path.insert` 해킹 20+ 곳
- 영향: 순환 경로, IDE 지원 불가, 테스트 불안정

**수정 작업:**
1. 각 src/ 하위 디렉토리에 `__init__.py` 생성 (intent/, council/, eval/, runtime/, hitl/, ingest/, search/, frameworks/, report/, migrate/, dream/, persona/ 등)
2. `pyproject.toml` 신설 — `[tool.setuptools.packages.find]` 또는 packages 명시
3. 모든 sys.path.insert 호출 제거 (테스트 conftest.py도 함께 정리)
4. 회귀 PASS 보장 — 256+ 유지

**작업 흐름:**
```bash
but mark c29-init-imports
# __init__.py 작성 + pyproject.toml + sys.path.insert 제거
python3 -m pytest tests/ -q          # 회귀 PASS — 256+ 유지 필수
but commit -m "fix(c29-#10): add __init__.py + pyproject.toml + remove sys.path hacks" --status-after
touch _research/.c29-locks/worker-3.done
```

---

### Worker 4 — `c29-misc-fixes` (HIGH #9 + #11 + #12 + #13)

**Issue #9: Skill 파일 간 모순 4건**
- Self-evaluation: `skills/muchanipo.md` "PROHIBITED" vs `muchanipo.md` "Option B 허용"
- Orchestrator: skills "너가 orchestrator" vs `orchestrator.py` 존재 + README 안내
- Council: `muchanipo.md` "너가 council" vs `arc-council.md` "parallel Agent"
- 루프: "NEVER STOP" vs Circuit Breaker 5회 PAUSE
- 수정: 각 모순에 단일 정책 결정 후 한쪽으로 통일

**Issue #11: MemPalace search_mempalace 영구 stub**
- `src/search/insight-forge.py`의 `search_mempalace()` 항상 빈 리스트
- Council의 "원본 문서 직접 검색" 무력화
- 수정: 로컬 wiki/ markdown grep/rg fallback 구현

**Issue #12: model-router.py KIMI_API_KEY SyntaxError**
- `KIMI_API_KEY=os.env...EY", "")` — 잘린 코드
- 수정: `os.environ.get("KIMI_API_KEY", "")`

**Issue #13: `except Exception: pass` 남용 10+**
- 영향: `src/council/council-runner.py`, `src/runtime/model-router.py`, `src/report/composer.py`, `src/intent/office_hours.py`
- 수정: 최소 `logging.warning` 추가, import는 `except ImportError`로 좁히기

**작업 흐름:**
```bash
but mark c29-misc-fixes
# 4 issue 순차 수정
python3 -m pytest tests/ -q
but commit -m "fix(c29-#9): resolve 4 skill contradictions" --status-after
but commit -m "fix(c29-#11): MemPalace search local wiki fallback" --status-after
but commit -m "fix(c29-#12): model-router KIMI_API_KEY syntax" --status-after
but commit -m "fix(c29-#13): logging.warning + except ImportError narrowing" --status-after
touch _research/.c29-locks/worker-4.done
```

---

## 공통 검증 (모든 worker)

```bash
python3 -m pytest tests/ -q          # 256 + 신규 → 모두 PASS 필수
but status -fv                        # 자기 branch에만 commit 있어야
git log gitbutler/workspace --oneline -5
```

회귀 PASS 안 되면 done 파일 만들지 말 것.

---

## 종료 후 (메인 thread)

각 worker `worker-{1..4}.done` 4개 모두 생성되면:
1. 각 virtual branch를 GitHub remote로 push: `but push c29-config-rubric` 등 4번
2. 각 PR 생성: `gh pr create --base main --head c29-{name}` 4번
3. critic verify (codex) 후 머지

---

## GitButler CLI 핵심 명령 (워커 참고)

| 명령 | 용도 |
|---|---|
| `but status -fv` | 현재 lane 상태 확인 (작업 시작 시) |
| `but mark <branch>` | 이후 변경을 이 branch에 자동 stage |
| `but commit -m "..." --status-after` | 현재 mark된 branch에 commit |
| `but stage <file>` | 파일을 특정 branch에 명시 stage |
| `but show <branch>` | 해당 branch의 변경 검토 |
| `but push <branch>` | 원격 push (PR 만들 때) |

**중요:** `git add/commit/push` 절대 사용 금지 — `but` 사용. (skill 강제)
