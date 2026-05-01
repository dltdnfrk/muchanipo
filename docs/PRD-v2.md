# Muchanipo PRD v2 (Product Requirements Document)

> **범용 아이디어 리서치 엔진** — 어떤 주제든 아이디어만 던지면 자동으로 리서치→심의→보고서
> 작성일: 2026-04-14
> 레포: dltdnfrk/muchanipo
> 버전: 2.0

---

## 목차

1. [프로젝트 비전](#1-프로젝트-비전)
2. [전체 아키텍처](#2-전체-아키텍처)
3. [인터뷰 엔진](#3-인터뷰-엔진)
4. [리서치 백엔드](#4-리서치-백엔드)
5. [페르소나 생성 — HACHIMI](#5-페르소나-생성--hachimi)
6. [Council 심의 시스템](#6-council-심의-시스템)
7. [보고서 생성 — MBB Dual Structure](#7-보고서-생성--mbb-dual-structure)
8. [모델 게이트웨이 v2](#8-모델-게이트웨이-v2)
9. [Human-in-the-Loop — Plannotator](#9-human-in-the-loop--plannotator)
10. [평가 체계](#10-평가-체계)
11. [거버넌스 및 안전](#11-거버넌스-및-안전)
12. [Dream Cycle](#12-dream-cycle)
13. [기술 스택](#13-기술-스택)
14. [외부 프로젝트 참조 종합표](#14-외부-프로젝트-참조-종합표)
15. [현재 상태 및 로드맵](#15-현재-상태-및-로드맵)

---

## 1. 프로젝트 비전

### 1.1 핵심 정의

**Muchanipo**는 **Ultimate Research Tool**이다.

Karpathy autoresearch + LLM council + LLM wiki + MiroFish + gstack + gbrain + eval 등 최고의 오픈소스 프로젝트들을 융합한 범용 아이디어 리서치 엔진. 어떤 주제든 아이디어만 던지면 자동으로 **리서치 → 심의 → 보고서** 사이클을 완주한다.

CEO(Hyunjun)가 아이디어를 던지면:
1. 인터뷰 엔진이 아이디어를 연구 가능한 ResearchBrief로 정제
2. 학술 API + 웹 + 로컬 Vault를 병렬 탐색
3. 페르소나 기반 LLM Council이 MBB 컨설팅 수준으로 심의
4. Obsidian Vault에 지식 자산으로 축적

### 1.2 설계 철학

> "muchanipo는 모델을 잘 고르는 시스템이 아니라, 아이디어를 연구 가능한 brief로 정제하고 council에서 심의하는 시스템이다."

**세 가지 원칙:**

| 원칙 | 설명 |
|------|------|
| **Brief First** | 모든 리서치는 정제된 brief에서 시작. 모호한 아이디어는 Council에 도달하지 못한다 |
| **Evidence Anchored** | 모든 클레임은 출처가 있어야 한다. fabricated quote는 시스템 레벨에서 차단 |
| **Council as Truth** | 단일 모델의 판단보다 다양한 페르소나 Council의 합의를 신뢰 |

### 1.3 비교 포지셔닝

| 도구 | 한계 | Muchanipo 차별점 |
|------|------|-----------------|
| Perplexity | 단답형, Council 없음 | 다층 심의 + MBB 보고서 |
| ChatGPT Research | 단일 모델, HITL 없음 | 멀티 페르소나 Council |
| Elicit | 학술 전용 | 학술 + 비즈니스 융합 |
| NotebookLM | 수동 업로드 | 자동 크롤링 + Vault 축적 |
| GPT-4 Deep Research | OpenAI 종속 | 오픈소스 모델 병렬 활용 |

---

## 2. 전체 아키텍처

### 2.1 파이프라인 개요

```
┌─────────────────────────────────────────────────────────────────┐
│                        MUCHANIPO v2                              │
│                                                                  │
│  아이디어 투입                                                    │
│       │                                                          │
│       ▼                                                          │
│  ┌─────────────┐    ┌──────────────────────────────────────┐    │
│  │  Intake     │───▶│         Interview Engine              │    │
│  │  (캡처)     │    │  Phase 0a → 0b → 0c → 0d → 0e        │    │
│  └─────────────┘    └─────────────────┬────────────────────┘    │
│                                       │ ResearchBrief           │
│                                       ▼                          │
│                     ┌─────────────────────────────────────────┐ │
│                     │      Research Targeting                  │ │
│                     │  Domain Decomp → Institutions →          │ │
│                     │  Journals → Seed Papers → Queries        │ │
│                     └──────────────────┬────────────────────── ┘ │
│                                        │ TargetingMap            │
│                                        ▼                         │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │               Research Backend                            │   │
│  │  OpenAlex │ Semantic Scholar │ arXiv │ CrossRef │ CORE   │   │
│  │  + Vault Search + Web (Exa) + insane-search              │   │
│  └──────────────────────────┬───────────────────────────────┘   │
│                              │ EvidenceRef + Finding             │
│                              ▼                                   │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │               Evidence Store                              │   │
│  │  source_grade(A/B/C/D) + provenance 검증                 │   │
│  └──────────────────────────┬───────────────────────────────┘   │
│                              │                                   │
│            ┌─────────────────┼─────────────────┐                │
│            ▼                 ▼                  ▼                │
│  ┌──────────────┐  ┌──────────────────┐  ┌──────────────┐      │
│  │  HACHIMI     │  │  Council         │  │  Report      │      │
│  │  페르소나 생성 │  │  (10 rounds)    │  │  Composer    │      │
│  └──────┬───────┘  └────────┬─────────┘  └──────┬───────┘      │
│         │                   │                    │               │
│         └───────────────────┼────────────────────┘               │
│                             ▼                                    │
│                   ┌──────────────────┐                          │
│                   │  MBB 6-Chapter   │                          │
│                   │  Final Report    │                          │
│                   └────────┬─────────┘                          │
│                            │                                    │
│            ┌───────────────┼───────────────┐                   │
│            ▼               ▼               ▼                   │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐         │
│  │  Plannotator │  │  Eval/Rubric │  │  Vault       │         │
│  │  (HITL)      │  │  (13축)      │  │  (Obsidian)  │         │
│  └──────────────┘  └──────────────┘  └──────────────┘         │
│                                                                  │
│  ┌───────────────────────────────────────────────────────┐     │
│  │  Runtime Orchestrator — NEVER STOP (Karpathy loop)    │     │
│  └───────────────────────────────────────────────────────┘     │
└─────────────────────────────────────────────────────────────────┘
```

### 2.2 스테이지 정의

```
Stage: IDEA_DUMP → INTERVIEW → TARGETING → RESEARCH → EVIDENCE → COUNCIL → REPORT → EVAL → VAULT
```

| Stage | 담당 모듈 | 주요 출력물 |
|-------|-----------|------------|
| IDEA_DUMP | `src/intake/` | `IdeaDump` dataclass |
| INTERVIEW | `src/interview/` + `src/intent/` | `ResearchBrief` |
| TARGETING | `src/targeting/` | `TargetingMap` |
| RESEARCH | `src/research/` | `Finding[]` |
| EVIDENCE | `src/evidence/` | `EvidenceRef[]` (graded) |
| COUNCIL | `src/council/` | `RoundResult[]` (10 rounds) |
| REPORT | `src/report/` | `REPORT.md` (MBB 6-chapter) |
| EVAL | `src/eval/` | rubric 점수 + 등급 |
| VAULT | vault/ | compiled truth 승격 |

---

## 3. 인터뷰 엔진

### 3.1 5단계 파이프라인 (Phase 0a~0e)

인터뷰는 단순 Q&A가 아니라 **아이디어를 리서치 가능한 Brief로 정제**하는 프로세스다.

```
Phase 0a: Triage
     │   ─ 아이디어 분류 (exploratory / comparative / analytical / predictive)
     │   ─ 리서치 타입 자동 감지
     ▼
Phase 0b: Forcing Questions (gstack /office-hours)
     │   ─ 6개 핵심 질문으로 표면 요구 → pain root 변환
     │   ─ entropy-greedy 원칙으로 정보량 최대화 (arXiv 2510.27410)
     ▼
Phase 0c: DesignDoc Review
     │   ─ 기존 DesignDoc이 있으면 검토 후 반영
     │   ─ LangChain ODR "ABSOLUTELY NECESSARY" 패턴: 명확화 1회 제한
     ▼
Phase 0d: ConsensusPlan Review
     │   ─ 기존 ConsensusPlan이 있으면 연속성 보장
     │   ─ LLMREI Interview Cookbook 동적 질문 재구성
     ▼
Phase 0e: Mode Routing
         ─ deep / moderate / quick 모드 분기
         ─ ResearchBrief 생성 → research/planner.py 전달
```

### 3.2 6 Forcing Questions (gstack /office-hours)

Garry Tan의 /office-hours 패턴을 차용. 표면 요구를 pain root로 reframing하는 핵심 질문들이다. LLM 호출 없이 keyword-driven 휴리스틱으로 구동.

| # | 질문 이름 | 핵심 내용 | 목적 |
|---|-----------|-----------|------|
| **Q1** | **Demand Reality** | "이미 돈을 내거나 행동으로 증명한 사람이 있는가?" | 수요 실재 여부 확인. 행동/돈이 수요다 |
| **Q2** | **Status Quo** | "지금 이 문제를 어떻게 해결하고 있는가? 현재 솔루션은?" | 기존 대안 이해. 진짜 경쟁자는 현재의 행동이다 |
| **Q3** | **Desperate Specificity** | "이 문제로 절실하게 고통받는 한 사람의 이름을 댈 수 있는가?" | 타겟을 일반화에서 구체 인물로 좁히기 |
| **Q4** | **Narrowest Wedge** | "내일 출시할 수 있는 가장 작은 버전은 무엇인가?" | MVP 범위 강제 축소. 실행 가능성 검증 |
| **Q5** | **Observation & Surprise** | "사용자를 관찰하면서 예상치 못하게 배운 것은? 진짜 만들고 있는 건 뭔가?" | 빌더의 가정 vs 실제 사용자 행동 갭 노출 |
| **Q6** | **Future-Fit** | "의도적으로 하지 않을 것은? 범위 밖에 두는 것은?" | 제품 경계 명확화. anti-roadmap |

**구현 특징:**
- `intent/office_hours.py`의 `OfficeHours.reframe()` 메서드
- 키워드 매칭으로 해당 forcing question 자동 트리거
- 각 질문은 최대 1회 적용 (중복 방지)
- LLMREI Interview Cookbook의 동적 재구성과 결합

### 3.3 관련 참조 프로젝트

| 프로젝트 | 차용 내용 | 적용 위치 |
|----------|-----------|-----------|
| **gstack /office-hours** | 6 forcing questions 구조 | `intent/office_hours.py` |
| **arXiv 2510.27410 (Nous)** | entropy-greedy 질문 선택 원칙 | `interview/session.py` |
| **LangChain ODR** | "ABSOLUTELY NECESSARY" 1회 제한 | `interview/session.py` |
| **LLMREI Interview Cookbook** | 동적 질문 재구성 | `interview/session.py` |
| **deep-research-query** | 4가지 research type 분류 | `intake/triage.py` |
| **grill-me (mattpocock/skills)** | 끈질긴 의사결정 트리 인터뷰, AI 추천 답변 제시, 코드베이스 자동 탐색. ~45분 세션으로 "shared understanding" 도달 | `interview/session.py` |
| **prd-taskmaster (anombyte93)** | 12개+ 상세 질문 → 종합 PRD 생성 → 13개 자동 품질 검사 (모호 표현/누락 기준/테스트 불가능 요구사항 감지) | `interview/brief.py` |

### 3.4 ResearchBrief 스키마

```python
@dataclass
class ResearchBrief:
    # 원문 보존
    raw_idea: str
    normalized_text: str

    # 분류
    research_type: Literal["exploratory", "comparative", "analytical", "predictive"]
    mode: Literal["deep", "moderate", "quick"]

    # Forcing Questions 결과
    demand_signal: str          # Q1: 수요 증거
    status_quo: str             # Q2: 현재 솔루션
    target_persona: str         # Q3: 구체 인물
    mvp_scope: str              # Q4: 최소 버전
    observation_surprise: str   # Q5: 예상치 못한 발견
    out_of_scope: str           # Q6: 안 할 것들

    # 리서치 설정
    query_axes: list[str]
    per_query_cap: int
    source_grade_threshold: str  # "A", "B", "C", "D"
```

### 3.5 리서치 타겟팅 (Research Targeting)

인터뷰에서 `ResearchBrief` 생성 시 **Targeting Map을 자동 포함**하여 리서치 백엔드가 올바른 학술 생태계를 즉시 탐색하도록 한다.

#### Targeting Map 구성

| # | 구성 요소 | 설명 |
|---|-----------|------|
| **1** | **분야 분해 (Domain Decomposition)** | 주제를 하위 학문 분야로 MECE 분해 |
| **2** | **타겟 기관 (Target Institutions)** | OpenAlex로 해당 분야 top 기관/연구실/저자 자동 추출 |
| **3** | **타겟 저널 (Target Journals)** | Scimago/IF 기반 핵심 저널 식별 |
| **4** | **시드 논문 전략 (Seed Paper Strategy)** | 최다인용 리뷰 + 최신 3년 키 논문 선정 |
| **5** | **검색 쿼리 생성** | 분야별 최적 검색어 자동 생성 |

#### 할루시네이션 방지 규칙 (CRITICAL)

> **Targeting Map의 모든 항목(기관, 저자, 저널)은 반드시 학술 API 쿼리 결과로부터 도출해야 한다. LLM 생성 금지.**

| 항목 | 검증 방법 | 금지 사항 |
|------|-----------|-----------|
| **기관/연구실** | OpenAlex API `GET /institutions?search=` → 실제 논문 발표 기관만 | LLM이 "이 대학에 ~학과가 있을 것 같다" 추측 |
| **저자** | Semantic Scholar API → 해당 키워드 top 저자 (citation count 기반) | 존재하지 않는 저자명 생성 |
| **저널** | CrossRef/Scimago → ISSN 기반 실존 저널만 | "~학회지가 있을 것 같다" 추측 |
| **논문** | DOI 또는 Semantic Scholar ID로 실존 확인 | 제목/저자 조합 날조 (ghost reference) |

이 규칙은 `safety/lockdown.py`의 `validate_targeting_map()` 게이트에서 강제한다. API 쿼리 응답에 없는 항목은 자동 제거.

#### Targeting Map 예시

아래는 **API 기반으로 실제 도출된** 예시 (LLM 생성 아님):

```
주제: "딸기 역병 분자진단 형광 프로브"
├─ 분야: 분자생물학 + 유기합성 + 광학센서
├─ 기관: [OpenAlex API 쿼리 결과로 채워짐]
├─ 저널: [CrossRef/Scimago 쿼리 결과로 채워짐]
└─ 시드: [Semantic Scholar 최다인용순 쿼리 결과로 채워짐]
```
> **참고**: 예시의 기관/저널은 실행 시 API가 반환하는 실제 데이터로 대체됨. PRD에서는 구조만 정의.

#### ResearchBrief 스키마 확장

```python
@dataclass
class TargetingMap:
    domains: list[str]              # MECE 분해 학문 분야
    target_institutions: list[str]  # OpenAlex 상위 기관/연구실
    target_journals: list[str]      # Scimago/IF 핵심 저널
    seed_papers: list[str]          # 최다인용 리뷰 + 최신 3년 키 논문
    search_queries: dict[str, list[str]]  # 분야별 최적 검색어
```

`ResearchBrief.targeting_map: TargetingMap` 필드로 자동 포함. `research/planner.py`가 이를 소비하여 AcademicRunner 초기 쿼리를 구성한다.

---

## 4. 리서치 백엔드

### 4.1 학술 API 통합표

| API | 키 | Rate Limit | 한국어 | 용도 | 비고 |
|-----|-----|------------|--------|------|------|
| **OpenAlex** | 무료 필수 | 10 RPS | 양호 | 종합 학술 데이터베이스 | 메일 헤더 추가 시 polite pool |
| **Semantic Scholar** | 권장 | 1 RPS | 제한적 | 인용 그래프 분석 | 무료 키로 100 RPS 가능 |
| **arXiv** | 불필요 | 3초/1건 | 미지원 | 프리프린트 최신 논문 | 반드시 딜레이 준수 |
| **CrossRef** | 불필요 | 50 RPS | DOI 가능 | 메타데이터 표준 | Polite pool 무제한 |
| **Unpaywall** | 불필요(이메일) | 일 100K | DOI 가능 | OA(Open Access) 버전 탐색 | 이메일 파라미터 필수 |
| **CORE** | 무료 필수 | 5-10/10초 | 일부 | 풀텍스트 논문 접근 | aggregator, 국내 논문 일부 포함 |

**구현 우선순위:**
1. OpenAlex (커버리지 최대, 무료)
2. Semantic Scholar (인용 관계 맵핑)
3. CORE (풀텍스트 접근)
4. CrossRef (메타데이터 보완)
5. arXiv (CS/ML 최신 연구)
6. Unpaywall (페이월 논문 OA 버전 탐색)

### 4.1a 학술 도구 전체 레지스트리

**Tier 1 — 즉시 통합 (무료 + MCP 서버):**

| 도구 | 규모 | 비용 | 특징 |
|------|------|------|------|
| **Semantic Scholar** | 2.25억 논문 | 무료 MCP | 인용 그래프, 공식 MCP 서버 |
| **OpenAlex** | 2.5억 논문 | CC0, 무료 | 최대 커버리지, Targeting Map 기관 추출 |
| **PubMed** | 3600만 논문 | 무료 MCP 7개+ | 생의학 전문, NIH 직결 |
| **Crossref** | 1.8억 DOI | 무료 | 메타데이터 표준, polite pool |
| **DBLP** | CS 전문 | 무료 | 컴퓨터과학 완전체 |
| **Zotero** | 문헌 관리 허브 | MCP 3개+ | 로컬 라이브러리 통합 |
| **KCI** | 한국 논문 | 무료 MCP | 국내 학술지 전용 |
| **arXiv** | 프리프린트 | 무료 | CS/ML/Physics 최신 연구 |
| **Google Scholar** | — | MCP 3개+, 스크래핑 | 최광범위, 비공식 접근 |

**Tier 2 — 유료:**

| 도구 | 기능 | 비용 | 비고 |
|------|------|------|------|
| **Consensus** | 과학적 합의 추출 | $0.10/쿼리 | 공식 MCP 서버 |
| **Scite.ai** | 인용 맥락 (지지/반박) | 구독 | 공식 MCP 서버 |
| **Elicit** | AI 리포트 | Pro 플랜 | 공식 MCP 서버 |
| **Connected Papers** | 인용 그래프 시각화 | Early Access API | 관련 논문 발견 |

**통합형 MCP 서버:**

| MCP 서버 | 커버리지 |
|----------|----------|
| **paper-search-mcp** | arXiv, PubMed, bioRxiv, Google Scholar |
| **PaperMCP** | ArXiv, HuggingFace, DBLP, PapersWithCode |
| **Scientific-Papers-MCP** | arXiv, OpenAlex, PMC, CORE |

**권장 조합:** `paper-search-mcp` + `Zotero MCP` + `Consensus MCP` + `KCI MCP`

**페이월 우회 도구:**
- `insane-search` 등 페이월 우회 도구 설정 가이드 필요
- 법적 주의사항 및 fair use 가이드라인 문서화
- Unpaywall을 통한 합법적 OA 버전 우선 탐색

### 4.2 3-Backend 집계 구조

```
ResearchBrief
    │
    ├── AcademicRunner (OpenAlex/SemanticScholar/arXiv/CrossRef/CORE)
    │       └── 학술 논문, 인용 그래프, 풀텍스트
    │
    ├── VaultRunner (로컬 Obsidian Vault)
    │       └── InsightForge: 5W1H + RRF(Reciprocal Rank Fusion)
    │
    └── WebRunner (Exa + Gemini Search grounding)
            └── 실시간 웹, 뉴스, 블로그
                │
                └── RRF 통합 → score 기반 정렬 → per_query_cap 적용
```

### 4.3 소스 등급 체계

| 등급 | 기준 | 예시 |
|------|------|------|
| **A** | 동료 심사 학술 논문 (DOI + 인용 검증) | Nature, Science, NEJM |
| **B** | 신뢰 출처 (web_score ≥ 0.8) 또는 로컬 Vault | 공식 문서, 정부 통계, Vault |
| **C** | 일반 웹 출처 | 뉴스, 블로그 |
| **D** | 출처 불명, 검증 불가 | 자동 경고 처리 |

### 4.4 MiroFish InsightForge 통합

MiroFish의 `InsightForge` 패턴을 차용하여 로컬 Vault 검색 강화:

- **5W1H 분해**: 쿼리를 Who/What/When/Where/Why/How로 분해하여 다각도 검색
- **RRF(Reciprocal Rank Fusion)**: 여러 검색 결과를 순위 기반으로 통합
- **sub-query decomposition**: `zep_tools.py` 패턴으로 복합 쿼리 분해

---

## 5. 페르소나 생성 — HACHIMI

### 5.1 개요

HACHIMI (arXiv 2603.04855) 논문의 3단계 페르소나 생성 프로토콜을 Council 페르소나 생성의 핵심으로 채택.

이론 기반 스키마로 페르소나 속성을 분해하여 일관성 있는 고품질 페르소나를 생성한다.

### 5.2 3단계 프로토콜

```
┌─────────────────────────────────────────────────────────────┐
│                    HACHIMI 3-Stage                           │
│                                                             │
│  Stage 1: PROPOSE                                          │
│  ─────────────────                                         │
│  theory-anchored schema로 페르소나 속성 분해               │
│                                                             │
│  입력: 연구 토픽 + Nemotron-Korea 인구통계 seed            │
│  처리:                                                      │
│    ─ 이론 기반 속성 분류                                   │
│      (직업/역할/나이/지역/가치관/리스크 성향)               │
│    ─ Value Axes 4축 할당                                   │
│      (time_horizon/risk_tolerance/                          │
│       stakeholder_priority/innovation_orientation)          │
│    ─ 초안 페르소나 생성                                    │
│                                                             │
│             │                                               │
│             ▼                                               │
│                                                             │
│  Stage 2: VALIDATE                                         │
│  ──────────────────                                        │
│  Neuro-Symbolic Validator (2단계)                          │
│                                                             │
│  Fast Validator (규칙 기반, 즉시 실행):                    │
│    ✓ AUP risk score ≤ 0.3                                  │
│    ✓ 위험 동사 없음 (폭력/개인정보침해 등)                  │
│    ✓ 고위험 타겟 조합 없음                                  │
│    ✓ 한국어 실명 타겟팅 없음                                │
│    ✓ tool 권한 적절성                                      │
│                                                             │
│  Deep Validator (LLM 기반, Fast 통과 후만 실행):           │
│    ✓ 페르소나 내적 일관성 검증                              │
│    ✓ 연구 토픽 관련성 점수 ≥ 0.7                           │
│    ✓ 다양성 커버리지 (EvoAgentX MAP-Elites 패턴)           │
│    ✓ 중복 관점 탐지 및 거부                                │
│                                                             │
│             │                                               │
│             ▼                                               │
│                                                             │
│  Stage 3: REVISE                                           │
│  ────────────────                                          │
│  검증 실패 시 자동 수정 (최대 3회 루프)                    │
│                                                             │
│  수정 전략:                                                 │
│    ─ Fast 실패 → 속성 재생성 (AUP 위험 요소 제거)          │
│    ─ Deep 실패 → 관점 조정 (다양성/일관성 개선)            │
│    ─ 3회 실패 → 폴백 페르소나 (안전 프리셋)                │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### 5.3 Value Axes 4축

| Axis | 설명 | 범위 |
|------|------|------|
| `time_horizon` | 단기 수익 vs 장기 성장 | short / medium / long |
| `risk_tolerance` | 위험 회피 vs 위험 추구 | low / medium / high |
| `stakeholder_priority` | 투자자 vs 사용자 vs 사회 | investor / user / society |
| `innovation_orientation` | 점진적 개선 vs 파괴적 혁신 | incremental / disruptive |

### 5.4 Nemotron-Personas-Korea 시드

한국 grounded 인구통계 데이터로 페르소나의 현실성 확보:

- **지역**: province(도/시) + city(시/군/구) 레벨
- **직업**: 한국 직업 분류 체계 기반
- **세대**: MZ/X/베이비붐 특성 반영
- **가치관**: 한국 사회문화적 맥락 (대기업 선호, 안정 추구 등)

### 5.5 EvoAgentX MAP-Elites 다양성 유지

병렬 Council에서 관점 중복을 방지하기 위해 MAP-Elites 알고리즘 패턴 적용:

- 2D 다양성 맵 유지 (risk_tolerance × innovation_orientation)
- 맵의 각 셀에 최대 1개 페르소나
- 이미 점유된 셀 → 다른 셀로 페르소나 리다이렉트

---

## 6. Council 심의 시스템

### 6.1 이중 출처: Karpathy + MiroFish

**Karpathy LLM Council (3단계 구조):**
```
1. Individual Stage
   ─ 각 페르소나가 독립적으로 해당 챕터 분석
   ─ 다른 페르소나 의견 볼 수 없음 (블라인드)

2. Anonymous Peer Review Stage
   ─ 다른 페르소나의 주장을 익명으로 검토
   ─ 비판/동의/보완 의견 제출

3. Chairman Synthesis Stage
   ─ 모든 의견을 종합하여 최종 판정
   ─ 합의 vs 불일치 명시
```

**MiroFish OASIS 기반 Swarm Intelligence:**
```
─ OASIS (Open Agent Social Interaction Simulations) 프레임워크
─ 40 rounds 병렬 심의 가능
─ ReportAgent가 최종 synthesis 수행
─ Think-Act-Observe-Write ReACT 루프
─ 소수 의견도 보고서에 포함
```

**현재 구현: 두 접근법 결합**
- Karpathy의 3단계 검증 구조 + MiroFish의 swarm 규모
- 10 rounds × 다중 페르소나
- plateau detection으로 수렴 시 자동 종료

### 6.2 10 Chapter Council 구조 (round_layers.py)

| Round | Chapter | Framework | 담당 모델 |
|-------|---------|-----------|-----------|
| L1 | 시장 규모 (TAM/SAM/SOM) | MECE Tree | Council Fast |
| L2 | 경쟁 지형 (2x2 포지셔닝) | Porter 5 Forces | Council Fast |
| L3 | 고객 JTBD | Christensen JTBD | Council Fast |
| L4 | 재무 모델 (Unit Economics) | — | Council Deep |
| L5 | 리스크 시나리오 | SWOT/TOWS | Council Deep |
| L6 | 실행 로드맵 | — | Council Fast |
| L7 | 거버넌스/운영 | — | Council Fast |
| L8 | KPI 트리 (North Star) | Sean Ellis North Star | Council Fast |
| L9 | 반론/민감도 | SWOT/TOWS | Council Deep |
| L10 | Executive Synthesis | — | Consensus (Opus) |

### 6.3 Plateau Detection

```python
# 3-window tolerance 0.05로 confidence 정체 시 자동 종료
class PlateauDetector:
    window_size: int = 3
    tolerance: float = 0.05

    def is_plateau(self, confidence_history: list[float]) -> bool:
        if len(confidence_history) < self.window_size:
            return False
        recent = confidence_history[-self.window_size:]
        return max(recent) - min(recent) < self.tolerance
```

### 6.4 분석 프레임워크 레지스트리

`frameworks/registry.py`가 Layer ID → Framework 매핑. Council prompt에 framework guidance 자동 삽입.

| Framework | 출처 | 적용 Layer |
|-----------|------|------------|
| **MECE Tree** | McKinsey | L1 (TAM/SAM/SOM 분해) |
| **Porter 5 Forces** | Michael Porter | L2 (5 forces severity) |
| **Christensen JTBD** | Clayton Christensen | L3 (functional/emotional/social 3축) |
| **North Star** | Sean Ellis / Reforge | L8 (KPI + driver tree) |
| **SWOT/TOWS** | — | L5, L9 (Threats 위주 + WT 방어) |

---

## 7. 보고서 생성 — MBB Dual Structure

### 7.1 구조 이중성 문제

**기존 10-chapter 구조의 한계:**
- Council deliberation 기록 (Bottom-up, 의회 심의록)
- 각 라운드별 쟁점이 순차 나열
- 보고서 독자에게 비효율적 (심의 과정이 노출)

**진짜 MBB 보고서의 구조:**
- Top-down, Pyramid Principle
- SCR 프레임워크 (Situation → Complication → Resolution)
- 4-6개 챕터로 압축
- 결론 먼저 제시

### 7.2 해결책: Dual Structure

```
[내부]                          [외부]
Council 10-round 심의           MBB 6-chapter 최종 보고서
(Bottom-up 의사록)      ──→    (Top-down 피라미드)
round-*.json                    REPORT.md
```

Council은 내부적으로 10라운드 심의를 완주한 후, `ReportComposer`가 결과를 MBB 6-chapter 구조로 재포장한다.

### 7.3 MBB 6-Chapter 최종 보고서

```
┌─────────────────────────────────────────────────────────────┐
│                 MBB 6-CHAPTER REPORT                        │
│                                                             │
│  Chapter 1: Executive Summary                              │
│  ────────────────────────────────────────────────────────  │
│  SCR 프레임워크:                                            │
│    Situation  ─ 현재 상황 (2-3문장)                         │
│    Complication ─ 핵심 문제/기회 (2-3문장)                  │
│    Resolution ─ 권고 방향 (1-2문장)                         │
│  핵심 수치 3개 + 최우선 권고안 1개                         │
│                                                             │
│  Chapter 2: 시장 기회 (Market Opportunity)                 │
│  ────────────────────────────────────────────────────────  │
│  TAM/SAM/SOM 계산 (MECE Tree)                              │
│  JTBD 통합 분석 (functional/emotional/social)              │
│  시장 성장률 + 타이밍 논거                                  │
│                                                             │
│  Chapter 3: 경쟁 환경 (Competitive Landscape)              │
│  ────────────────────────────────────────────────────────  │
│  Porter 5 Forces 심각도 매핑                                │
│  2x2 포지셔닝 매트릭스                                      │
│  차별화 벡터 + 방어 가능성                                  │
│                                                             │
│  Chapter 4: 사업 타당성 (Business Case)                    │
│  ────────────────────────────────────────────────────────  │
│  Unit Economics (LTV/CAC/Payback Period)                   │
│  손익분기 시뮬레이션                                        │
│  주요 가정 + 민감도 분석                                    │
│                                                             │
│  Chapter 5: 리스크 및 대응 (Risks & Mitigations)          │
│  ────────────────────────────────────────────────────────  │
│  SWOT/TOWS 기반 리스크 매트릭스                             │
│  Council 반론 통합 (소수 의견 포함)                         │
│  시나리오별 대응 전략                                       │
│                                                             │
│  Chapter 6: 권고안 및 로드맵 (Recommendations)             │
│  ────────────────────────────────────────────────────────  │
│  실행 로드맵 (90일/6개월/1년)                               │
│  KPI 트리 (North Star Metric + drivers)                    │
│  거버넌스 구조 + 의사결정 체계                              │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### 7.4 ReportComposer 로직

```
round-*.json (10개)
    │
    ▼
ChapterMapper
    ─ L1+L3 → Chapter 2 (시장 기회)
    ─ L2    → Chapter 3 (경쟁)
    ─ L4    → Chapter 4 (재무)
    ─ L5+L9 → Chapter 5 (리스크)
    ─ L6+L7+L8 → Chapter 6 (로드맵)
    ─ L10   → Chapter 1 (Executive Summary SCR 추출)
    │
    ▼
PyramidPrinciple Formatter
    ─ 결론 먼저 → 근거 → 세부사항 순서 재정렬
    ─ 각 챕터 첫 문장 = 핵심 주장
    │
    ▼
VisualWire
    ─ framework_output → ASCII/Mermaid 차트
    ─ TAM funnel, 2x2 matrix, KPI tree 자동 생성
    │
    ▼
REPORT.md (MBB 6-chapter)
```

---

## 8. 모델 게이트웨이 v2

### 8.1 Stage별 모델 라우팅 (완전 개정)

| Stage | Model | Context | Cost | 선택 이유 |
|-------|-------|---------|------|-----------|
| **Intake** | Gemini CLI (Flash) | 1M | 무료 | Google Search grounding 내장, 최신 정보 실시간 접근 |
| **Interview** | Claude Sonnet 4.6 | 1M | OAuth | 추론 깊이 + 한국어 처리 최상위, forcing questions 반영 |
| **Research** | Gemini Pro + Kimi 병렬 | 1M / 256K | 무료 + $0.55/M | DeepSearchQA 92.5%, 대용량 문서 병렬 처리 |
| **Evidence** | Kimi K2.6 | 256K | $0.55/M | BrowseComp 83.2%, 웹 탐색 + 인용 검증 |
| **Council** | Claude Opus 4.6 | 1M | OAuth | GPQA 91.3%, 복잡한 추론 + 다층 심의 |
| **Report** | Qwen 3.6 로컬 (35B-A3B) | 262K | 무료 | 100tok/s 로컬 실행, 한국어 CoT 최적화 |
| **Consensus** | Claude Opus 4.6 | 1M | OAuth | 최종 판정, 합의 알고리즘 구동 |
| **Eval** | Codex CLI (GPT-5.5) | 400K | $20/mo | 샌드박스 격리, 코드 실행 기반 검증 |

### 8.2 모델 상세 스펙

**Claude Sonnet 4.6 (Interview)**
- Context: 1M tokens
- 특징: 한국어 추론 + 긴 대화 컨텍스트 유지
- 비용: Anthropic OAuth (Max 플랜 포함)

**Gemini Pro (Research)**
- Context: 1M tokens
- 특징: Google Search grounding으로 실시간 정보 통합
- DeepSearchQA 점수: 92.5%
- 비용: Google AI Studio 무료 티어

**Kimi K2.6 (Evidence)**
- Context: 256K tokens
- 특징: BrowseComp 83.2% — 복잡한 웹 탐색 + 근거 추출 최강
- 비용: $0.55/M tokens (입력)
- 적합 용도: 논문 풀텍스트 읽기 + 인용 검증

**Claude Opus 4.6 (Council + Consensus)**
- Context: 1M tokens
- GPQA 점수: 91.3% (대학원 수준 질문)
- 비용: Anthropic OAuth
- 역할: 복잡한 멀티턴 심의 + 최종 판정

**Qwen 3.6 로컬 (Report)**
- 아키텍처: Mixture of Experts, 3B active / 35B total parameters
- Context: 262K tokens
- 속도: 100tok/s (M-series Mac 로컬)
- GPQA: 86.0%
- SWE-bench: 73.4%
- 한국어 CoT (Chain-of-Thought) 최적화
- 비용: 완전 무료 (로컬 실행)
- 적합 용도: 보고서 최종 한국어 작성

**Codex CLI / GPT-5.5 (Eval)**
- Context: 400K tokens
- 비용: $20/mo 정액
- 특징: 샌드박스 격리 실행 — 코드 기반 검증 안전
- 역할: rubric 채점 + citation grounding 검증

### 8.3 비용 최적화 전략

```
총 비용 목표: 리서치 1회 < $0.5

Free Tier 최대 활용:
  ─ Gemini CLI (Flash/Pro): 무료 할당량 우선 소진
  ─ Qwen 3.6 로컬: 보고서 생성 전체 무료
  ─ Codex CLI: $20/mo 정액으로 eval 전체 커버

OAuth 모델 (Claude):
  ─ Sonnet: Interview + 가벼운 작업
  ─ Opus: Council 심층 분석만 제한 사용
  ─ Max 플랜 rate limit 관리

비용 경보:
  ─ RunBudget.reserve() → reconcile() → audit
  ─ vault/cost-log.jsonl append-only
  ─ 예산 초과 시 자동 다운그레이드 (Opus → Sonnet)
```

### 8.4 ModelGateway 라우팅 흐름

```
stage 입력
    │
    ▼
budget preflight (예산 확인)
    │
    ├── 초과 → 폴백 모델 선택 (fallback_reason 기록)
    │
    ▼
dispatch (모델 호출)
    │
    ▼
reconcile (실제 토큰 수 정산)
    │
    ▼
audit (stage/provider/model/cost/fallback_reason → audit.jsonl)
```

---

## 9. Human-in-the-Loop — Plannotator

### 9.1 Plannotator 개요

**Plannotator** (backnotprop/plannotator)를 HITL 평가 UI로 채택.

리서치 계획과 보고서를 시각적으로 annotation하여 에이전트가 소비할 수 있는 구조화된 피드백으로 변환하는 도구.

### 9.2 핵심 기능

| 기능 | 설명 |
|------|------|
| **Visual Annotation** | 리서치 계획/보고서의 시각적 마킹 및 코멘트 |
| **Approve/Request Changes** | 체크포인트 기반 승인/변경 요청 메커니즘 |
| **Structured Feedback** | 자유 텍스트 피드백 → 에이전트 소비 가능 JSON 자동 변환 |
| **Multi-Agent Support** | Claude Code, Codex CLI, Gemini CLI, OpenCode, Pi 호환 |
| **어노테이션 타입** | 삭제, 코멘트, 대체 텍스트, 삽입 — 4가지 어노테이션 액션 |
| **보안** | AES-256-GCM 암호화, 7일 자동 삭제 |
| **팀 협업** | 공유 링크로 배포 → 팀원 피드백 수집 → 에이전트에 전달 |

**설치:**
```bash
# 방법 1: curl 설치
curl -fsSL https://plannotator.ai/install.sh | bash

# 방법 2: OMC 플러그인
/plugin marketplace add backnotprop/plannotator
```

**지원 에이전트:** Claude Code, Codex CLI, Gemini CLI, OpenCode, Pi

### 9.3 HITL 체크포인트

```
파이프라인 내 3개 HITL 게이트:

Gate 1: Brief Approval (Phase 0e 이후)
    ─ ResearchBrief 검토
    ─ Plannotator로 scope/direction 수정
    ─ APPROVED → Research 시작
    ─ CHANGES REQUESTED → Interview 재실행

Gate 2: Evidence Review (Research 완료 후)
    ─ EvidenceRef 목록 검토
    ─ 신뢰도 낮은 소스 제거/교체
    ─ 추가 탐색 방향 지정
    ─ APPROVED → Council 시작

Gate 3: Report Review (Council 완료 후)
    ─ MBB 6-chapter 보고서 검토
    ─ 챕터별 Approve / Request Changes
    ─ APPROVED → Vault 저장
    ─ CHANGES REQUESTED → 해당 챕터 재생성
```

### 9.4 Rubric 기반 자동 채점과 HITL 연동

```
자동 채점 (13축 Rubric v2.2)
    │
    ├── PASS (≥70점) → Plannotator Gate 3 → Vault
    ├── UNCERTAIN (50-69점) → Plannotator 필수 검토
    └── FAIL (<50점) → discard (HITL 불필요)
```

### 9.5 피드백 자동 변환

Plannotator의 annotation이 에이전트용 JSON으로 자동 변환:

```json
{
  "gate": "report_review",
  "chapter": 2,
  "status": "changes_requested",
  "feedback": {
    "type": "evidence_insufficient",
    "target": "TAM calculation",
    "instruction": "한국 시장 데이터 추가 필요. KIET/KDI 보고서 참조",
    "priority": "high"
  }
}
```

---

## 10. 평가 체계

### 10.1 Rubric v2.2 — 13축

| # | 축 | Weight | 유형 | 설명 |
|---|---|---|---|---|
| 1 | relevance | 1.0 | Active | 연구 질문과의 관련성 |
| 2 | depth | 1.0 | Active | 분석 심도 |
| 3 | novelty | 1.0 | Active | 새로운 인사이트 비율 |
| 4 | evidence_quality | 1.0 | Active | 소스 등급 + 인용 충실도 |
| 5 | actionability | 1.0 | Active | 즉시 실행 가능한 권고안 |
| 6 | clarity | 1.0 | Active | 명확성 + 가독성 |
| 7 | coherence | 1.0 | Active | 논리 일관성 |
| 8 | reliability | 1.0 | Active (불변) | 재현 가능성 |
| 9 | bias_awareness | 1.0 | Active | 편향 인식 및 명시 |
| 10 | confidence | 1.0 | Active | 확신 수준 적절성 |
| 11 | citation_fidelity | 0.0 | Measurement-only (불변) | 인용 원문 일치 여부 |
| 12 | density | 0.0 | Measurement-only | 정보 밀도 |
| 13 | coverage_breadth | 0.0 | Measurement-only | 관점 커버리지 |

**등급 기준:**
- **PASS**: ≥ 70점 → vault 저장
- **UNCERTAIN**: 50-69점 → Plannotator 검토 큐
- **FAIL**: < 50점 → discard

**Grounding Gate:**
- min_verified_ratio: 0.8
- claim 1:1 quote-in-source_text 검증
- 실패 시 PASS → UNCERTAIN 자동 강등

### 10.2 Citation Grounder

`eval/citation_grounder.py`가 모든 클레임에 대해 1:1 검증:

```
클레임 추출
    │
    ▼
소스 텍스트 조회 (EvidenceRef.source_text)
    │
    ▼
quote ⊂ source_text 검증
    │
    ├── 통과 → verified_claim
    └── 실패 → UNVERIFIED 마킹 → grounding_ratio 차감
         └── ratio < 0.8 → PASS → UNCERTAIN 강등
```

### 10.3 Rubric Learner

20+ 피드백 축적 후 rubric 자동 진화:

- Plannotator 피드백 → weight 조정
- immutable 축 (reliability, citation_fidelity) 제외
- 변경 이력 `rubric-history.jsonl`에 기록

---

## 11. 거버넌스 및 안전

### 11.1 Safety Lockdown

| 기능 | 설명 |
|------|------|
| `guard_write()` | `~/.ssh`, `~/.aws`, `~/.config` 등 민감 경로 쓰기 차단 |
| `validate_persona_manifest()` | 위험 동사 + 고위험 타겟 + 도구 조합 탐지. 한국어 실명 타겟팅 방지 |
| `validate_evidence_provenance()` | fabricated quote 방지 (quote ⊂ source_text 검증) |
| `redact()` | AWS/GitHub/OpenAI/Anthropic 키 + PII 마스킹 |
| `aup_risk()` | 0.0-1.0 risk score 산출 |

### 11.2 불변 정책 (safety-immutable.yaml)

Council 심의로도 변경 불가한 불변 정책:
- `citation_fidelity` 축 진화 차단
- `reliability` 축 진화 차단
- 민감 경로 whitelist 변경 불가

### 11.3 RunBudget 거버넌스

```python
class RunBudget:
    # threading.Lock으로 스레드 안전 보장
    _lock: threading.Lock

    def reserve(self, stage: str, estimated_cost: float) -> bool:
        """사전 예약. 초과 시 False 반환 → 폴백 모델 사용"""

    def reconcile(self, stage: str, actual_cost: float):
        """실제 비용 정산. 차액 반환 또는 추가 차감"""

    def audit_log(self, entry: AuditEntry):
        """vault/cost-log.jsonl에 append-only 기록"""
```

### 11.4 AuditLog 필드

| 필드 | 내용 |
|------|------|
| stage | 실행 스테이지 |
| provider | anthropic/openai/ollama/mock |
| model | 실제 사용 모델 |
| cost | 실제 비용 ($) |
| fallback_reason | 폴백 발생 시 이유 |
| timestamp | ISO 8601 |

---

## 12. Dream Cycle

### 12.1 개요

인지과학의 episodic → semantic memory 승격 개념을 차용한 야간 지식 정리 시스템.

**실행**: cron KST 03:00 daily  
**특징**: stdlib only, 외부 LLM 호출 없음

### 12.2 DreamRunner 로직

```
vault/personas/ + vault/insights/ 스캔
    │
    ▼
Episode 정규화
    ─ 중복 제거
    ─ 날짜 인덱싱
    ─ 태그 표준화
    │
    ▼
클러스터 요약
    ─ 유사 episodic 항목 그룹화
    ─ 핵심 패턴 추출
    │
    ▼
Compiled Truth 승격
    ─ 3회 이상 반복 패턴 → wiki/compiled/
    ─ slug dedup (GBrain 패턴)
    ─ 9가지 페이지 타입 분류
    │
    ▼
index.md + log.md 업데이트
```

### 12.3 GBrain 2-Layer 구조

| 레이어 | 내용 | 관리 |
|--------|------|------|
| **Raw Layer** | 원본 에피소드 + 리서치 결과 | append-only |
| **Compiled Layer** | 검증된 진실 + 타임라인 | 큐레이션 필요 |

GBrain (garrytan)의 Compiled Truth + Timeline 패턴을 차용:
- stale detection: 6개월 이상 미검증 사실 경고
- cross-link 자동 생성: 관련 항목 간 링크
- typed links: 9가지 관계 타입

---

## 13. 기술 스택

### 13.1 코어 스택

| 레이어 | 기술 | 버전 |
|--------|------|------|
| Backend | Python | 3.12+ |
| Package Manager | uv | latest |
| Desktop (macOS) | Swift / SwiftUI | Swift 6 |
| Desktop (Cross-platform) | Tauri (Rust + React + TypeScript) | 2.x |
| UI | React + TailwindCSS + shadcn/ui | latest |
| CI/CD | GitHub Actions | — |

### 13.2 LLM 프로바이더

| 프로바이더 | 모델 | 접근 방법 |
|-----------|------|-----------|
| Anthropic | Claude Sonnet/Opus 4.6 | OAuth (Max 플랜) |
| Google | Gemini Flash/Pro | Gemini CLI 무료 |
| Moonshot | Kimi K2.6 | API Key |
| Alibaba | Qwen 3.6 (35B-A3B) | 로컬 Ollama |
| OpenAI | GPT-5.5 (Codex CLI) | $20/mo |

### 13.3 데이터 레이어

| 컴포넌트 | 기술 |
|----------|------|
| Knowledge Store | Obsidian Vault (markdown) |
| Cost Log | vault/cost-log.jsonl (append-only) |
| Evidence Store | vault/evidence/ |
| Personas | vault/personas/ |
| Compiled Truth | vault/wiki/ |

### 13.4 통신 프로토콜

| 인터페이스 | 방식 |
|-----------|------|
| 네이티브 앱 ↔ Python | JSON-line event stream (stdin/stdout) |
| 내부 모듈 | Python dataclass + dict |
| HITL | Plannotator JSON API |

---

## 14. 외부 프로젝트 참조 종합표

| 외부 프로젝트 | What | Why | Where | Logic Detail |
|---|---|---|---|---|
| **Karpathy autoresearch** | program.md 설정, 무한 루프, NEVER STOP 패턴 | 자율 리서치의 핵심 루프 구조 | `runtime/orchestrator.py` | interest axis별 토픽 풀 생성 (deep=3x, moderate=1x) → round-robin → subprocess 실행. PID lock으로 단일 인스턴스 보장 |
| **Karpathy LLM Wiki** | raw/ vs wiki/ 소유권 분리, compiled truth 축적, 2-layer 아키텍처 | 지식의 episodic→semantic 승격 메커니즘 | `wiki/`, `dream/dream_runner.py` | index.md/log.md 관리. stale detection + typed cross-link 자동 생성 |
| **Karpathy LLM Council** | 3단계: Individual → Anonymous Peer Review → Chairman synthesis | 단일 모델보다 합의가 신뢰도 높음 | `council/session.py` | 블라인드 독립 분석 → 익명 상호 검토 → 최종 판정. 합의/불일치 명시 |
| **MiroFish (666ghj) InsightForge** | 5W1H + RRF, 로컬 vault 검색, sub-query decomposition | 복합 쿼리의 다각도 검색 | `search/insight-forge.py` | zep_tools.py 패턴으로 쿼리 분해. Reciprocal Rank Fusion으로 다중 결과 통합 |
| **MiroFish ReACT 보고서** | Think-Act-Observe-Write 루프, ReportAgent | 보고서 생성의 반복적 품질 개선 | `report/composer.py` | 각 챕터를 Think(계획)→Act(생성)→Observe(검토)→Write(확정) 사이클로 처리 |
| **MiroFish OASIS Swarm** | OASIS 기반 swarm intelligence, 40 rounds 병렬 심의 | 대규모 다양성 확보 | `council/session.py` | 병렬 페르소나 심의. ReportAgent가 최종 synthesis. 소수 의견 보존 |
| **GBrain (garrytan)** | Compiled Truth + Timeline 2-layer, slug dedup, typed links, 9 page types | 지식 자산의 장기 축적 구조 | `agents/arc-wiki.md`, `dream/` | stale detection으로 구식 정보 경고. 9가지 관계 타입으로 cross-link 자동 생성 |
| **gstack (garrytan) /office-hours** | 6 forcing questions 패턴 | 표면 요구 → pain root 변환 | `intent/office_hours.py` | keyword-driven 휴리스틱. LLM 호출 없이 stdlib만 사용. 각 질문 최대 1회 적용 |
| **HACHIMI (arXiv 2603.04855)** | Propose→Validate→Revise 3단계 페르소나 생성, theory-anchored schema | 이론 기반 고품질 페르소나 생성 | `council/persona_generator.py` | Neuro-Symbolic Validator (Fast+Deep 2단계). 실패 시 최대 3회 수정 루프 |
| **McKinsey SCR 프레임워크** | Situation→Complication→Resolution 피라미드 | Top-down 보고서 구조화 | `report/composer.py` | Executive Summary의 핵심 서사 구조. 결론 먼저 제시 |
| **BCG/MBB Consulting Deck** | 10 chapter 심의 구조 → 6 chapter 최종 보고서 | 컨설팅 수준 보고서 품질 | `council/round_layers.py`, `report/` | 내부 10 rounds 심의 → 외부 MBB 6-chapter 재포장 (Dual Structure) |
| **Christensen JTBD** | functional/emotional/social 3축 Job-to-be-Done | 고객 동기의 다층 분석 | `frameworks/jtbd.py` | 기능적 필요 외 감정적/사회적 동기 분리 분석. L3 Council에 자동 삽입 |
| **Porter 5 Forces** | 5 forces severity 점수화 | 산업 경쟁 구조 정량화 | `frameworks/porter.py` | 공급자/구매자/신규진입/대체재/경쟁강도 5개 축으로 severity 측정 |
| **Sean Ellis / Reforge North Star** | 북극성 KPI + driver tree | 핵심 지표와 드라이버 연결 | `frameworks/north_star_tree.py` | North Star → 드라이버 지표 → 리프 지표 자동 트리 생성 |
| **arXiv 2510.27410 (Nous)** | entropy-greedy 질문 선택 원칙 | 정보량 최대화 | `interview/session.py` | 다음 질문 선택 시 불확실성 감소량 최대 질문 우선 |
| **Nemotron-Personas-Korea** | 한국 grounded 인구통계 seed | 페르소나의 한국적 현실성 | `council/persona_generator.py` | province/city/occupation 매핑. 한국 사회문화 맥락 주입 |
| **EvoAgentX MAP-Elites** | 2D 다양성 맵 기반 관점 분포 유지 | 병렬 Council의 관점 중복 방지 | `council/diversity_mapper.py` | risk_tolerance × innovation_orientation 2D 셀. 셀당 최대 1 페르소나 |
| **Composio** | plugin slot abstraction 패턴 | 모델/런타임 유연한 교체 | `runtime/plugin_loader.py` | YAML 기반 3 slot (model_router, runtime, notifier) 정의 |
| **LangChain ODR** | "ABSOLUTELY NECESSARY" 1회 제한 패턴 | 인터뷰 중복 방지 | `interview/session.py` | 명확화 질문 최대 1회 제한. 사용자 피로도 최소화 |
| **LLMREI Interview Cookbook** | 동적 질문 재구성 | 맥락 적응형 인터뷰 | `interview/session.py` | 이전 답변 분석 → 다음 질문 실시간 재구성 |
| **deep-research-query** | 4가지 research type 분류 | 리서치 전략 자동 선택 | `intake/triage.py` | exploratory/comparative/analytical/predictive 자동 분류 |
| **grill-me (mattpocock/skills)** | 지속적 인터뷰 세션 패턴 | 심층 인터뷰 지속성 | `interview/session.py` | 세션 간 컨텍스트 보존. 이전 답변 참조 재질문 |
| **prd-taskmaster** | 구조화된 PRD 출력 형식 | ResearchBrief 표준화 | `interview/brief.py` | PRD 필드 자동 채우기. 누락 필드 재질문 트리거 |
| **Anthropic 81k Interviewer** | multi-axis coverage planning | 인터뷰 커버리지 보장 | `interview/coverage_planner.py` | 미커버 축 자동 감지 → 보충 질문 생성 |
| **Plannotator (backnotprop)** | 비주얼 annotation + Approve/Request Changes UI | 구조화된 HITL 피드백 | `hitl/plannotator_adapter.py` | annotation → JSON 변환. Claude Code/Codex/Gemini CLI/OpenCode 호환 |
| **OpenAlex API** | 종합 학술 DB, 무료 10 RPS | 최대 커버리지 학술 검색 | `research/academic/openalex.py` | polite pool 활용. 이메일 헤더로 우선순위 확보 |
| **Semantic Scholar API** | 인용 그래프, 권장 API 키 | 논문 인용 관계 맵핑 | `research/academic/semantic_scholar.py` | 인용 클러스터 분석. 핵심 논문 자동 발견 |
| **CORE API** | 풀텍스트 논문 aggregator | 페이월 없는 풀텍스트 접근 | `research/academic/core.py` | 국내 논문 일부 포함. 5-10req/10초 제한 준수 |
| **Unpaywall API** | OA 버전 탐색, 이메일 필수 | 합법적 페이월 우회 | `research/academic/unpaywall.py` | DOI → OA URL 변환. 일 100K 한도 관리 |
| **pi-autoresearch (davebcn87/Shopify)** | 자율 실험 루프 — 코드 수정→벤치마크→유지/롤백 반복, MAD 기반 confidence score | Karpathy autoresearch를 범용 소프트웨어 최적화로 일반화. Shopify Liquid 엔진에서 53% 성능 향상 실증 | `src/eval/evolve_runner.py`, rubric 자동 진화 | MAD(Median Absolute Deviation) 기반 통계적 신뢰도 측정. 개선이 없으면 롤백, 개선이 확인되면 코드 유지 반복 |

---

## 15. 현재 상태 및 로드맵

### 15.1 완료 (v1 기준)

- [x] E2E 파이프라인 (idea → council) mock-first 구현
- [x] Mock → Real 와이어링 (C32: 4 lanes)
- [x] Tauri 앱 스캐폴드 + CI/CD (GitHub Actions + DMG 자동 빌드)
- [x] Swift 네이티브 앱 스캐폴드 (SwiftUI)
- [x] 13축 평가 체계 + grounding gate
- [x] Safety lockdown (PII redaction, fabricated quote 방지)
- [x] Dream cycle (야간 정리, cron KST 03:00)
- [x] 5개 분석 프레임워크 (JTBD, Porter, MECE, NorthStar, SWOT)
- [x] Budget governance (reserve→reconcile→audit)
- [x] PID lock 기반 단일 인스턴스 NEVER STOP 루프

### 15.2 Open PR

- [ ] #30: Apple-style app composition mockup (디자인 문서)

### 15.3 v2 신규 구현 필요 항목

**높은 우선순위:**
- [ ] 학술 API 통합 (OpenAlex, Semantic Scholar, CORE)
  - `research/academic/` 모듈 신규 작성
  - rate limit 관리 + retry 로직
- [ ] Plannotator HITL 통합
  - `hitl/plannotator_adapter.py` 구현
  - 3개 Gate 체크포인트 구현
- [ ] MBB Dual Structure ReportComposer
  - `ChapterMapper` 구현 (10 rounds → 6 chapters)
  - Pyramid Principle Formatter
- [ ] Model Gateway v2 라우팅 업데이트
  - Gemini CLI 연동 (Intake stage)
  - Kimi K2.6 연동 (Evidence stage)
  - Qwen 3.6 로컬 연동 (Report stage)
  - Codex CLI 연동 (Eval stage)

**중간 우선순위:**
- [ ] HACHIMI Neuro-Symbolic Validator (Fast + Deep 2단계)
- [ ] Plannotator annotation → JSON 자동 변환
- [ ] 6 Forcing Questions 개별 구현 및 테스트
- [ ] EvoAgentX MAP-Elites 다양성 맵 구현
- [ ] `consensus.py` 합의 알고리즘 완성 (현재 placeholder)

**낮은 우선순위:**
- [ ] insane-search 등 페이월 우회 도구 설정 가이드
- [ ] Unpaywall DOI → OA URL 파이프라인
- [ ] Rubric Learner 자동 진화 (20+ 피드백 필요)
- [ ] VisualWire Mermaid 차트 자동 생성
- [ ] 네이티브 앱 UI 완성 (현재 스캐폴드)

### 15.4 아키텍처 검증 포인트

| 항목 | 현재 상태 | 목표 |
|------|-----------|------|
| Council 모델 다양성 | Sonnet/Opus 위주 | Gemini/Qwen 병렬 심의 추가 |
| Research latency | 순차 실행 | Gemini + Kimi 병렬화 |
| Report 품질 | MBB 10-chapter | MBB 6-chapter (Dual Structure) |
| HITL friction | 수동 파일 편집 | Plannotator UI |
| 학술 데이터 커버리지 | Vault + Exa만 | 6개 학술 API 추가 |
| 비용/리서치 | 미측정 | 목표 < $0.5 |

### 15.5 비전 달성 체크리스트

```
Ultimate Research Tool 기준:

✓ 범용성: 어떤 주제든 처리
□ 학술 깊이: 6개 학술 API 통합 완료
✓ 심의 품질: Karpathy + MiroFish Council 구현
□ 보고서 품질: MBB 6-chapter Dual Structure
□ HITL: Plannotator 통합
✓ 지식 축적: Dream cycle + LLM Wiki
✓ 안전성: Safety lockdown + immutable 정책
□ 비용 효율: < $0.5/리서치 달성
✓ 자율성: NEVER STOP 루프
```

---

## 부록 A: 모듈 간 연결 다이어그램

```
intake/idea_dump
  → intent/office_hours (6 forcing questions reframe)
  → interview/session (entropy-greedy + grill-me 지속 세션)
    → interview/coverage_planner (multi-axis 커버리지 확인)
    → interview/brief (ResearchBrief 생성 — prd-taskmaster 패턴)
      → research/planner
        → research/academic/ (OpenAlex/SemanticScholar/arXiv/CrossRef/CORE/Unpaywall)
        → research/vault (InsightForge: 5W1H + RRF)
        → research/web (Exa + Gemini Search grounding)
          → evidence/store (provenance + source_grade 검증)
            → eval/citation_grounder (claim 1:1 검증)
            → safety/lockdown (fabricated quote 방지)

      → report/composer (MBB Dual Structure: 10-round → 6-chapter)
        → report/chapter_mapper (L1-L10 → Ch1-6)
        → report/pyramid_formatter (결론 먼저 재정렬)
        → report/visual_wire (차트 시각화)

      → council/persona_generator (HACHIMI 3단계)
        → council/diversity_mapper (EvoAgentX MAP-Elites)
      → council/session (Karpathy 3단계 + MiroFish swarm)
        → execution/model_gateway (stage → provider 라우팅)
          → providers (anthropic/gemini/kimi/qwen/codex/mock)
          → governance/budget (reserve→reconcile)
          → governance/audit (cost logging)
        → council/round_layers (10 chapters)
        → frameworks/registry (JTBD/Porter/MECE/NorthStar/SWOT)
        → council/value_axes (4축 관점 bias)

pipeline/idea_to_council  ← 전체 E2E 오케스트레이션
  → hitl/plannotator_adapter (Gate 1/2/3 체크포인트)
  → eval/rubric_scorer (13축 채점)
    → hitl/vault_router (PASS/UNCERTAIN/FAIL 라우팅)

runtime/orchestrator      ← NEVER STOP 자율 루프 (Karpathy)
dream/dream_runner        ← 야간 cron (episodic→semantic 승격)
muchanipo/server          ← 네이티브 앱 JSON-line 서버
```

---

## 부록 B: 파일 구조

```
muchanipo/
├── src/
│   ├── intake/
│   │   ├── idea_dump.py          # IdeaDump dataclass
│   │   ├── normalizer.py         # whitespace 정리
│   │   └── triage.py             # research type 분류
│   ├── interview/
│   │   ├── session.py            # 5단계 파이프라인
│   │   ├── brief.py              # ResearchBrief 생성
│   │   └── coverage_planner.py   # multi-axis 커버리지
│   ├── intent/
│   │   └── office_hours.py       # 6 forcing questions
│   ├── research/
│   │   ├── planner.py
│   │   ├── runner.py
│   │   ├── academic/
│   │   │   ├── openalex.py
│   │   │   ├── semantic_scholar.py
│   │   │   ├── arxiv.py
│   │   │   ├── crossref.py
│   │   │   ├── core.py
│   │   │   └── unpaywall.py
│   │   ├── vault_runner.py       # InsightForge 통합
│   │   └── web_runner.py         # Exa + Gemini
│   ├── evidence/
│   │   ├── artifact.py           # EvidenceRef, Finding
│   │   └── store.py              # provenance 검증
│   ├── council/
│   │   ├── persona_generator.py  # HACHIMI 3단계
│   │   ├── diversity_mapper.py   # MAP-Elites
│   │   ├── session.py            # Karpathy+MiroFish
│   │   ├── round_layers.py       # 10 chapters
│   │   └── value_axes.py         # 4축
│   ├── report/
│   │   ├── composer.py           # Dual Structure
│   │   ├── chapter_mapper.py     # 10→6 재포장
│   │   ├── pyramid_formatter.py  # Top-down 재정렬
│   │   └── visual_wire.py        # 차트 생성
│   ├── execution/
│   │   ├── model_gateway.py      # stage → model 라우팅
│   │   └── providers/
│   │       ├── anthropic.py
│   │       ├── gemini.py
│   │       ├── kimi.py
│   │       ├── qwen.py           # 로컬 Ollama
│   │       ├── codex.py
│   │       └── mock.py
│   ├── governance/
│   │   ├── budget.py             # RunBudget
│   │   └── audit.py              # AuditLog
│   ├── frameworks/
│   │   ├── registry.py
│   │   ├── jtbd.py
│   │   ├── porter.py
│   │   ├── mece_tree.py
│   │   ├── north_star_tree.py
│   │   └── swot.py
│   ├── eval/
│   │   ├── rubric_scorer.py      # 13축 채점
│   │   ├── citation_grounder.py  # claim 1:1 검증
│   │   └── rubric_learner.py     # 자동 진화
│   ├── hitl/
│   │   ├── plannotator_adapter.py # Plannotator 연동
│   │   └── vault_router.py       # PASS/UNCERTAIN/FAIL
│   ├── safety/
│   │   └── lockdown.py
│   ├── dream/
│   │   └── dream_runner.py
│   ├── pipeline/
│   │   └── idea_to_council.py    # E2E 오케스트레이션
│   └── runtime/
│       └── orchestrator.py       # NEVER STOP 루프
├── app/
│   ├── macos/                    # Swift/SwiftUI
│   └── tauri/                    # Rust + React + TypeScript
├── vault/                        # Obsidian Vault
│   ├── personas/
│   ├── insights/
│   ├── evidence/
│   ├── wiki/
│   │   ├── raw/
│   │   └── compiled/
│   └── cost-log.jsonl
├── config/
│   ├── model-router.json
│   └── safety-immutable.yaml
└── pyproject.toml                # uv 관리
```

---

*Muchanipo PRD v2 — 작성: 2026-04-14*
*다음 리뷰: v2 구현 완료 후 (예상: 2026-Q2)*
