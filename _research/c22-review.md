# C22-A~D Review

Date: 2026-04-25
Reviewer: worker-4
Scope:
- `91c13dc` C22-A InterviewRubric
- `8e17593` C22-B entropy + Type
- `a34d6fc` C22-C pre_screen + reframe
- `97867df` C22-D coverage gate

Verification:
- `python3 -m pytest tests/ -q` -> `163 passed in 1.02s`
- Re-run after concurrent sprint updates: `python3 -m pytest tests/ -q` -> `174 passed in 1.03s`
- Spot checks:
  - `pre_screen_hook("한국 농가 가격 분석", history=["bad"])` raises `AttributeError`
  - `_detect_unknown_acronyms("한국 AgTech TAM CAGR 분석")` returns `["TAM", "CAGR"]`
  - `_detect_unknown_acronyms("AI 에이전트 ROI 분석")` returns `[]`
  - `OfficeHours().reframe("내 이메일 foo@example.com 으로 한국 농가 가격 분석")` redacts email before `PlanReview.autoplan()`

## Findings

### MEDIUM - malformed history can crash the clarification pre-screen

File: `src/intent/office_hours.py:271`

`pre_screen_hook()` accepts `history: Optional[Sequence[Dict[str, Any]]]`, but runtime callers can pass partially malformed chat history. The current `any(...)` loop calls `msg.get(...)` unconditionally, so a single string/`None`/list item crashes before the interview can start.

Repro:

```python
pre_screen_hook("한국 농가 가격 분석", history=["bad"])
# AttributeError: 'str' object has no attribute 'get'
```

Risk:
- This is an edge-case availability bug in the Phase 0 entry path.
- It also bypasses the intended "do not re-ask if already clarified" behavior if upstream history serialization changes shape.

Suggested action item:
- Normalize history entries defensively (`msg if isinstance(msg, Mapping) else {}`), and add tests for `history=["bad"]`, `history=[None]`, and mixed valid/malformed history.

### LOW - common finance/research acronyms trigger unnecessary clarification

File: `src/intent/office_hours.py:242`

`_detect_unknown_acronyms()` intentionally flags uppercase 3-7 char tokens not in `_KNOWN_ACRONYMS`. The whitelist covers `AI`/`ROI`, but misses common research and market-sizing acronyms already recognized elsewhere by `citation_grounder.is_critical_claim`, such as `TAM`, `SAM`, `SOM`, `CAGR`, `AUM`, `MAU`, `DAU`, `ARR`, and `MRR`.

Repro:

```python
_detect_unknown_acronyms("한국 AgTech TAM CAGR 분석")
# ["TAM", "CAGR"]
```

Risk:
- Korean + English mixed market-analysis prompts may get a false-positive "what does this acronym mean?" question even when the acronym is standard.
- This does not break execution, but it adds avoidable friction to Quick/Deep interview routing.

Suggested action item:
- Align `_KNOWN_ACRONYMS` with `_CRITICAL_PATTERNS` in `src/eval/citation_grounder.py`, or centralize the common acronym list.

## Checks Passed

- C22-A `InterviewRubric.update()` correctly raises `KeyError` on unknown `dimension_id` and the behavior is covered by `tests/test_interview_rubric.py`.
- C22-A stores collected answers as-is, but the C22-C `OfficeHours.reframe()` path redacts PII before DesignDoc/PlanReview generation. No direct regression found in the reviewed tests.
- C22-B `classify_research_type()` handles empty input and the tested comparative/predictive/analytical/exploratory paths.
- C22-B dynamic options fall back to `Other` for unknown dimensions, so unknown `dim_id` does not crash option generation.
- C22-C lockdown integration calls `redact()` and `aup_risk()` with graceful fallback. Email redaction was verified.
- C22-D `rubric_coverage_gate()` blocks below-threshold coverage and reports uncovered dimensions.
- `citation_grounder.is_critical_claim` compatibility: no direct API conflict found. C22 code references citation grounding as downstream policy text and does not alter claim extraction or grounding APIs.

## Recommendation

COMMENT / follow-up task. No high-severity blockers found, and the regression suite is passing. Create a small C24 hardening task for defensive history parsing and acronym whitelist alignment.
