# C23: Parallel Post-C22 Sprints

**작성:** 2026-04-25
**선행:** C22 완료 (Phase 0b v2 — entropy-greedy + AskUserQuestion + rubric coverage)
**목표:** 4 독립 sprints 병렬 진행 — interview 모듈을 council-runner에 wire + Type-aware routing 정밀화 + dream_cycle cron + C22 review

---

## 워커 분배 (4명, 각자 1개 sprint 전담)

각 워커는 자신의 sprint 1개만 진행. 끝나면 done 파일 떨어뜨리고 종료.

```
Worker 1 (claude) → Sprint A: council-runner.py에 Phase 0 interview wire
Worker 2 (claude) → Sprint B: Type-aware Phase 0e routing 정밀화
Worker 3 (claude) → Sprint C: dream_cycle cron + evolve_runner trigger
Worker 4 (claude) → Sprint D: C22-A~D 코드 review (read-only, lockdown 검증)
```

각 워커는 시작 시 `_assignments/ASSIGNMENT_C23_parallel.md` 정독 후 자기 Sprint 진행.

**완료 시 필수:**
- 변경 commit (Sprint별 메시지 prefix `feat(c23-A)` ... `feat(c23-D)`)
- `_research/.c23-locks/sprint-X.done` 파일 생성 (X는 A/B/C/D)
- 회귀 `python3 -m pytest tests/ -q` 163 + 신규 → PASS 보장

**금지:**
- 다른 워커 sprint 영역 손대지 말 것
- 회귀 PASS 안 되면 done 파일 만들지 말 것

---

## Sprint A — council-runner.py에 Phase 0 interview wire (Worker 1)

**문제:** C21-E + C22에서 Interactive Intent Interview를 만들었지만 `src/council/council-runner.py`에 wire 안 됨. skill 문서엔 "Phase 0 종료 시 ConsensusPlan.to_ontology() → Step 4 council ontology 직접 입력" 명시했지만 코드 미통합.

**작업:**
1. `src/council/council-runner.py` 읽고 현재 ontology 입력 진입점 식별
2. CLI 인자에 `--design-doc <path>` 또는 `--consensus-plan-json <path>` 추가
3. 진입점에서 `ConsensusPlan.to_ontology()` dict를 받아 council ontology에 반영
4. Korean domain 자동 감지 시 `KoreaPersonaSampler.agtech_farmer_seed(n)` 자동 호출 (이미 있는 모듈 사용)
5. 신규 테스트 `tests/test_council_intent_wire.py` 3-5개 (ontology 진입, role 자동 추가)
6. 회귀 PASS 확인 후 commit

**영향 파일:**
- 수정: `src/council/council-runner.py`
- 신설: `tests/test_council_intent_wire.py`

**Commit prefix:** `feat(c23-A): wire Phase 0 ConsensusPlan into council-runner ontology`

**완료 표시:** `touch _research/.c23-locks/sprint-A.done`

---

## Sprint B — Type-aware Phase 0e routing 정밀화 (Worker 2)

**문제:** C22-B에서 `InterviewPlan.research_type`이 추가됐지만 Phase 0e `route_mode()`에서 활용 안 됨. type별로 routing 신호를 가중해야 정확도↑.

**작업:**
1. `src/intent/interview_prompts.py`의 `route_mode()` 함수에 `research_type` 시그널 추가
2. 휴리스틱:
   - `analytical` / `comparative` → `targeted_iterative` 보너스 +1 (단발 결과 적합)
   - `predictive` → `autonomous_loop` 보너스 +1 (구축은 지속 학습)
   - `exploratory` → 가중치 중립 (default 흐름)
3. `ModeDecision.signals` dict에 `research_type_bonus_*` 키 추가
4. `format_mode_routing_decision()`에 type 한 줄 표시
5. tests/test_interview_prompts.py에 4 type별 routing 영향 테스트 4개 추가
6. 회귀 PASS 확인 후 commit

**영향 파일:**
- 수정: `src/intent/interview_prompts.py`, `tests/test_interview_prompts.py`

**Commit prefix:** `feat(c23-B): Type-aware Phase 0e mode routing`

**완료 표시:** `touch _research/.c23-locks/sprint-B.done`

---

## Sprint C — dream_cycle cron + evolve_runner trigger (Worker 3)

**문제:** gbrain v0.20 dream-cycle 패턴이 vault에 누적된 통찰을 정리하는 야간 작업인데 muchanipo에 자동 실행 인프라 미구축. 현재 수동 호출만 가능.

**작업:**
1. `src/dream/` 디렉토리 확인 (없으면 생성)
2. `src/dream/dream_runner.py` 신설 — vault `vault/personas/`, `vault/insights/` 스캔 후 중복 합치기 + cluster summary
3. `tools/dream_cycle.sh` 신설 — `python3 src/dream/dream_runner.py` 호출 + 로그 출력
4. `crontab` 자동 install은 하지 말 것 (사용자 환경 침해). 대신 README 갱신:
   - `tools/dream_cycle.sh` 사용법
   - 권장 cron 스케줄: 매일 03:00 KST
5. tests/test_dream_runner.py 3-5개 (빈 vault, 중복 합치기, cluster output)
6. 회귀 PASS 확인 후 commit

**금지:**
- 실제 cron 등록 금지 (사용자가 직접)
- 외부 LLM API 호출 금지 (stdlib only — heuristic dedup)

**영향 파일:**
- 신설: `src/dream/dream_runner.py`, `tools/dream_cycle.sh`, `tests/test_dream_runner.py`

**Commit prefix:** `feat(c23-C): dream_cycle runner skeleton + manual trigger script`

**완료 표시:** `touch _research/.c23-locks/sprint-C.done`

---

## Sprint D — C22-A~D 코드 review (Worker 4, read-only)

**문제:** C22 4 commits를 빠르게 떨궜는데 다른 시각의 검증 부재. lockdown 통합, citation_grounder와 충돌, edge case 점검.

**작업 (read-only — 코드 수정 금지):**
1. C22 4 commit 모두 검토:
   - `91c13dc` C22-A InterviewRubric
   - `8e17593` C22-B entropy + Type
   - `a34d6fc` C22-C pre_screen + reframe
   - `97867df` C22-D coverage gate
2. 각 commit별로 다음 점검:
   - lockdown.aup_risk / redact 통합 누락 여부
   - citation_grounder.is_critical_claim 호환성
   - edge case (empty input, malformed history, unknown dim_id)
   - 한국어 + 영문 mixed 입력에서 약어 감지 false positive
3. 발견사항을 `_research/c22-review.md` 파일에 정리 (severity high/med/low)
4. action item이 있으면 별도 task로 제안 (직접 수정은 금지)
5. PASS 의견이면 그대로 보고

**금지:**
- 코드/테스트 수정 금지 (read-only review)
- _research 외 디렉토리 write 금지

**영향 파일:**
- 신설: `_research/c22-review.md` (review 문서만)

**Commit prefix:** `docs(c23-D): C22 sprint review report`

**완료 표시:** `touch _research/.c23-locks/sprint-D.done`

---

## 공통 검증 (전 워커)

```bash
python3 -m pytest tests/ -q   # 163 + sprint별 신규 테스트 모두 PASS 확인
git status -sb                # 자기 sprint 영역만 변경
git log --oneline -5          # commit 메시지 확인
```

회귀 PASS 안 되면 done 파일 만들지 말 것. 디버깅 끝까지.

---

## 종료 조건 (orchestrator 보는 신호)

`_research/.c23-locks/sprint-{A,B,C,D}.done` 4개 모두 생성되면 omc-auto-team.sh가 자동 shutdown.
