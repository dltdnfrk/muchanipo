# Muchanipo 데이터 전송 고지

## 개요

Muchanipo는 **명시적 오프라인 경로를 우선 제공하는(offline-first capable)** 설계입니다.  
`muchanipo demo`, `--offline`, 또는 `MUCHANIPO_OFFLINE=1`을 사용한 실행은 외부 서버와의 통신을 전혀 하지 않으며, 로컬 fixture 기반의 모의 연구 데이터를 사용합니다. 반대로 일반 `run`/`serve`/Tauri CLI 경로는 로컬 제공자 CLI나 API 키가 감지되면 온라인 실행이 가능하므로, 민감한 주제는 오프라인 플래그를 명시해야 합니다.

## 오프라인 모드 (기본)

| 항목 | 동작 |
|------|------|
| 외부 API 호출 | **0건** |
| 사용자 검색어 전송 | **없음** |
| 사용자 IP 전송 | **없음** |
| 네트워크 트래픽 | **없음** |
| 사용되는 데이터 출처 | 로컬 fixture (`MockProvider`) |

오프라인 모드에서 생성되는 보고서의 근거는 실제 논문이나 웹 검색 결과가 아닌, 구조화된 시뮬레이션 데이터입니다. 이 점을 연구 보고서에 활용할 때 유의해야 합니다.

## 온라인 모드 (라이브 실행)

`--online` 플래그를 사용하거나, 로컬에 LLM 제공자 CLI/API 키가 설정되어 있을 때 Muchanipo는 다음 외부 서비스와 통신할 수 있습니다:

| 서비스 | 전송 데이터 | 목적 |
|--------|------------|------|
| **OpenAlex** (openalex.org) | 검색어, `contact_email` | 학술 논문 메타데이터 검색 |
| **Crossref** (crossref.org) | 검색어, `contact_email` | DOI 기반 논문 정보 검색 |
| **Semantic Scholar** | 검색어 | 논문 초록 및 인용 정보 검색 |
| **Unpaywall** (unpaywall.org) | DOI, `contact_email` | 공개 접근 가능한 원문 위치 확인 |
| **arXiv** (arxiv.org) | 검색어 | 프리프린트 논문 검색 |
| **CORE** (core.ac.uk) | 검색어 | 오픈 액세스 논문 검색 |
| **LLM 제공자** (Anthropic, Google, OpenAI, Moonshot 등) | 프롬프트 텍스트, 컨텍스트 | 언어 모델 기반 분석 및 보고서 작성 |
| **Plannotator HTTP 게이트** | 게이트 이름, 계획/brief, evidence refs, report markdown, annotation/status | 사람이 계획/근거/보고서를 검토하는 HITL 승인 |

### 주의사항

- **검색어**: 사용자가 입력한 연구 주제와 파생 검색어는 위 학술 데이터베이스의 서버(주로 미국, 유럽)에 전송됩니다.
- **IP 주소**: 위 서비스로의 HTTP 요청 시 사용자의 공개 IP 주소가 해당 서버의 접근 로그에 기록될 수 있습니다.
- **이메일 주소**: 학술 API의 정책상 `contact_email`을 요구하는 경우, 기본값은 `research@muchanipo.local`입니다. 실제 연구 목적으로 사용 시 `MUCHANIPO_CONTACT_EMAIL` 환경변수를 설정하세요.
- **LLM 프롬프트**: 온라인 모드에서 사용자 입력과 검색 결과는 선택된 LLM 제공자의 API 서버로 전송됩니다. 제공자별 데이터 처리 정책을 참고하세요.
- **Plannotator payload**: `PLANNOTATOR_API_KEY`와 HTTP endpoint를 설정하면 계획, brief, evidence refs, report markdown이 외부 검토 서비스로 전송될 수 있습니다.

## 사용자 동의 및 설정

Muchanipo는 실행 시 `--offline` 또는 `--online`을 명시적으로 선택할 수 있습니다. 아무것도 지정하지 않으면:

1. 로컬에 설치된 제공자 CLI 또는 API 키가 없으면 → **오프라인 모드로 자동 전환**
2. 제공자 CLI/API 키가 감지되면 → 온라인 모드 가능 (`MUCHANIPO_PREFER_CLI=0` 또는 `MUCHANIPO_OFFLINE=1`로 차단 가능)

민감한 주제나 개인정보가 포함된 연구 주제를 입력할 경우 반드시 `--offline` 플래그를 사용하거나, 개인정보를 익명화한 후 입력하세요.

## 관련 환경변수

| 변수 | 설명 |
|------|------|
| `MUCHANIPO_OFFLINE=1` | 강제 오프라인 모드 |
| `MUCHANIPO_ONLINE=1` | 강제 온라인 모드 |
| `MUCHANIPO_CONTACT_EMAIL` | 학술 API 호출 시 사용할 이메일 주소 |
| `MUCHANIPO_PREFER_CLI=0` | 로컬 제공자 CLI 자동 사용 비활성화 |
| `PLANNOTATOR_API_KEY` | Plannotator HTTP HITL 게이트 사용 |

## 문의

Muchanipo의 데이터 처리 방식에 대한 문의는 저장소의 Issue 트래커를 통해 남겨주세요.
