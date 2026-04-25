# C22: Phase 0b Adaptive Interview v2

**작성:** 2026-04-25
**선행:** C21-E (PRD 6 questions, 정적 순서)
**목표:** Track A(사용자 환경 deep-interview/show-me-the-prd/deep-research-query) + Track B(arXiv 2510.27410 / 2601.14798 / 2507.02564 / Anthropic Interviewer / LangChain ODR) 학술-디테일 융합 → **동적 재배치 + 선택지형 + Coverage Gate** 인터뷰 v2.

---

## 핵심 원칙 (사용자 승인)

1. **AskUserQuestion 도구**로 6 questions 호출 — 빈칸 강요 X, **선택지 A/B/C/D + Other 직접 입력**
2. **Entropy-Greedy 동적 재배치** (arXiv 2510.27410) — Q1→Q6 고정 순서 아님. 매 라운드 가장 불확실한 차원 먼저
3. **Type 분류** (deep-research-query Phase 1) — Exploratory / Comparative / Analytical / Predictive
4. **Pre-screen 1회 clarification** (LangChain ODR) — 약어/모호 용어만, "ABSOLUTELY NECESSARY" 원칙
5. **Source quality A-D** (deep-research-query) — Q6 옵션화
6. **Rubric Coverage Gate ≥0.75** (Anthropic Interviewer + 2601.14798) — ConsensusPlan 직전 검증, 미충족 시 보완 probe
7. **Stop signal 동적** (2601.14798) — 6개 강제 X, coverage 충족 시 조기 종료
8. **Progress [N/6]** UX, **Go Ahead 패스** 옵션

---

## 영향 파일

```
신설:
  src/intent/interview_rubric.py        ~120 LOC
  tests/test_interview_rubric.py         ~6 tests

수정:
  src/intent/interview_prompts.py        +select_next_question, classify_research_type, build_question_options
  src/intent/office_hours.py             +pre_screen_hook, reframe_with_context
  src/intent/plan_review.py              +rubric_coverage_gate
  skills/muchanipo.md                    Phase 0b 섹션 — AskUserQuestion 호출 흐름 + 동적 재배치 명시
  tests/test_interview_prompts.py        +entropy ordering, type classification tests
```

---

## 4-Commit 분할

### Commit 1 — `feat(c22-A): InterviewRubric + RubricItem dataclasses`

**파일:** `src/intent/interview_rubric.py` (신설)

```python
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

class CoverageStatus(Enum):
    NOT_ASKED = "not_asked"
    ASKED_INSUFFICIENT = "asked_insufficient"
    COVERED = "covered"

@dataclass
class RubricItem:
    dimension_id: str               # Q1~Q6
    research_question: str          # 이 차원이 답하려는 것
    probe_hints: list[str]          # 추가 probe 예시
    coverage_status: CoverageStatus = CoverageStatus.NOT_ASKED
    collected_answer: Optional[str] = None
    quality_score: float = 0.0      # 0.0~1.0, Teacher-Educator 5축 평균
    entropy_estimate: float = 1.0   # 1.0=완전 불확실, 0.0=확실

@dataclass
class InterviewRubric:
    topic: str
    items: list[RubricItem] = field(default_factory=list)

    def coverage_rate(self) -> float: ...
    def next_uncovered(self) -> Optional[RubricItem]: ...   # entropy 최대 차원
    def is_complete(self, threshold: float = 0.75) -> bool: ...
```

**기본 RubricItem 6개** (Q1-Q6 PRD-style 한국어 research_question 정의)

**테스트** (`tests/test_interview_rubric.py`):
- `test_rubric_default_six_items`
- `test_coverage_rate_zero_initial`
- `test_next_uncovered_picks_max_entropy`
- `test_is_complete_threshold_075`
- `test_mark_answered_updates_status`
- `test_partial_coverage_returns_false`

---

### Commit 2 — `feat(c22-B): entropy-greedy ordering + Type classification`

**파일:** `src/intent/interview_prompts.py` 수정

```python
@dataclass
class QuestionDimension:
    id: str                  # Q1~Q6
    label: str
    entropy_estimate: float
    answer: Optional[str] = None

def select_next_question(rubric: InterviewRubric) -> Optional[RubricItem]:
    """arXiv 2510.27410 greedy: 미답변 차원 중 entropy 최대 선택."""
    return rubric.next_uncovered()

def classify_research_type(text: str) -> str:
    """deep-research-query Phase 1.
    Returns: 'exploratory' | 'comparative' | 'analytical' | 'predictive'
    """
    # 키워드 기반 휴리스틱 (LLM 호출 없이 stdlib)
    # 비교/대조 키워드 → comparative
    # 미래/예측/구축 → predictive
    # ROI/정량/원인 → analytical
    # 그 외 → exploratory

def build_question_options(dim_id: str, topic: str, prev_answers: dict) -> list[dict]:
    """토픽-맞춤형 선택지 동적 생성.
    Returns: [{label: str, description: str}, ...]
    Q6는 항상 Source A-D quality 옵션 고정.
    """
```

**`assess()` 확장:** `InterviewPlan`에 `research_type: str` 필드 추가.

**테스트:**
- `test_select_next_question_picks_max_entropy`
- `test_classify_type_comparative` ("A vs B 비교")
- `test_classify_type_predictive` ("구축하고 싶어")
- `test_classify_type_analytical` ("ROI 정량")
- `test_classify_type_exploratory` (default)
- `test_q6_options_always_source_quality_a_to_d`

---

### Commit 3 — `feat(c22-C): pre_screen_hook + reframe + AskUserQuestion 통합`

**파일:** `src/intent/office_hours.py` 수정

```python
@dataclass
class PreScreenResult:
    need_clarification: bool
    question: str = ""
    reason: str = ""

def pre_screen_hook(topic: str, history: list[dict]) -> PreScreenResult:
    """LangChain ODR "ABSOLUTELY NECESSARY":
    1. 이미 명확화 했으면 → 재질문 금지
    2. 약어/줄임말/미지 용어 감지 → need_clarification=True
    3. 범위 과도하게 넓음 → need_clarification=True
    """

def reframe_with_context(
    dim_id: str,
    rubric: InterviewRubric,
    prev_answers: dict,
) -> tuple[str, list[dict]]:
    """LLMREI Interview Cookbook + show-me-the-prd:
    이전 답변 참조해 다음 질문 + 선택지를 동적 재구성.
    Returns: (question_text, options_list)
    """
```

**파일:** `skills/muchanipo.md` 수정 (Phase 0b 섹션)

```markdown
### Phase 0b — Interactive Interview (AskUserQuestion 도구 사용)

매 라운드:
1. select_next_question(rubric) → 가장 불확실한 차원 선택 (Q1~Q6 동적 순서)
2. reframe_with_context(dim, rubric, prev_answers) → 토픽-맞춤 질문 + 선택지
3. AskUserQuestion 호출 — 선택지 A/B/C/D + Other(직접 입력)
4. 답변으로 rubric.update(dim, answer, quality_score) → entropy 감소
5. rubric.is_complete(threshold=0.75) AND coverage_rate ≥ 0.75 → Phase 0c 진입
   else → 다음 라운드 (최대 6 round)

진행 표시: 매 질문 헤더에 [N/6] (예: "[3/6] 도메인 맥락은 어디까지?")

Pre-screen: Phase 0b 시작 직전 pre_screen_hook(topic) 1회.
need_clarification=True면 첫 AskUserQuestion으로 명확화 → 답변 후 본 인터뷰.
```

**테스트:**
- `test_pre_screen_detects_acronym` ("MIRIVA")
- `test_pre_screen_skips_if_already_clarified`
- `test_reframe_uses_prev_answers`
- `test_q3_options_narrow_after_q1_known`

---

### Commit 4 — `feat(c22-D): rubric_coverage_gate before ConsensusPlan`

**파일:** `src/intent/plan_review.py` 수정

```python
def rubric_coverage_gate(
    rubric: InterviewRubric,
    threshold: float = 0.75,
) -> tuple[bool, str]:
    """ConsensusPlan 생성 직전 coverage 검증.
    Returns: (passed, reason)
    """
    rate = rubric.coverage_rate()
    if rate < threshold:
        uncovered = [i.dimension_id for i in rubric.items
                     if i.coverage_status != CoverageStatus.COVERED]
        return False, f"Coverage {rate:.2f} < {threshold}. Uncovered: {uncovered}"
    return True, f"Coverage {rate:.2f} ≥ {threshold}"
```

**파일:** `skills/muchanipo.md` Phase 0d 섹션 갱신 — gate 단계 명시:

```markdown
### Phase 0d — ConsensusPlan Review

진입 전 rubric_coverage_gate(threshold=0.75) 검증:
- ❌ 미충족 → 부족한 차원 1개 보완 probe (AskUserQuestion 1회 추가)
- ✅ 충족 → autoplan(doc) 호출 → ConsensusPlan 출력 → 사용자 review
```

**테스트:**
- `test_coverage_gate_passes_at_threshold`
- `test_coverage_gate_fails_below_threshold`
- `test_coverage_gate_reports_uncovered_dims`

---

## 검증

1. **단위:** `python3 -m pytest tests/ -v` — 기존 119+ + 신규 ~15 → **134+ PASS**
2. **회귀:** Phase 0a~0e 통합 흐름 (이전 시나리오 "MIRIVA 가격 책정", "프로브 파운드리") 양쪽 다 동작 확인
3. **Skill paths:** `python3 -m pytest tests/test_skill_paths.py -v` — interview_rubric.py 추가 import 무결성

---

## 비-목표 (이번 sprint 외)

- Shannon entropy 정확 계산 (LLM 호출 필요) — quality_score를 entropy 프록시로 대체
- DPO/GRPO 학습 — 휴리스틱만 (Nous는 RL 훈련 통한 정책, 우리는 동등한 greedy 선택)
- council-runner.py에 rubric wire (Task #17 deferred sprint)
- Anthropic Interviewer JSON 스키마 정확 복제 (자연어 rubric만)

---

## 예상 작업량

- Commit 1 (rubric): 30분
- Commit 2 (entropy + type): 40분
- Commit 3 (pre_screen + reframe + skill): 60분
- Commit 4 (gate): 20분
- 회귀: 10분
- **총: ~2.5h, 4 commits**
