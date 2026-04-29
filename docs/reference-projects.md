# Muchanipo 참고 프로젝트 정리

이 문서는 Muchanipo가 제품 방향과 구조를 잡을 때 참고하는 외부 프로젝트와 시스템을 정리한 문서다. 구현 계획서는 아니며, 각 참고 대상이 무엇이고 Muchanipo에서 왜 필요한지만 설명한다.

## 6단계별 참고 프로젝트 배치

Muchanipo의 실제 구현은 아래 6단계 흐름을 기준으로 참고 프로젝트를 녹여 넣는다.

| 단계 | 단계 이름 | 들어가야 하는 참고 프로젝트 |
| --- | --- | --- |
| 1 | 인터뷰 / 요구사항 정리 | 1. GPTaku `show-me-the-prd`<br>2. GStack `office-hours`<br><br>중요: `show-me-the-prd`와 `office-hours`의 역할이 겹치지 않게 분리해야 한다. |
| 2 | 목표 설정 / 연구 지도 작성 | 1. GStack `plan-review`<br>2. 학술 자료 검색 API<br>3. GBrain 지식 구조<br>4. Plannotator |
| 3 | 자료 수집 / 자동 연구 | 1. Karpathy Autoresearch<br>2. InsightForge<br>3. MemPalace<br>4. 학술 자료 검색 API<br><br>주의: 자료 수집이 너무 두루뭉실해지기 쉬운 단계다. 여기서는 검색 질문, 근거 수집 기준, 재검색 조건을 포함한 프롬프트 엔지니어링을 가장 정밀하게 다듬어야 한다. |
| 4 | 근거 검증 / 지식 정리 | 1. GBrain, 현재 결론 + 사건 기록<br>2. 출처 기반 연구 원칙<br>3. Plannotator |
| 5 | Council / 다중 관점 토론 | 1. MiroFish<br>2. OASIS / CAMEL-AI<br>3. Nemotron-Personas-Korea<br>4. HACHIMI<br>5. MAP-Elites |
| 6 | 보고서 작성 / 학습 축적 | 1. ReACT 보고서 작성 패턴<br>2. Karpathy LLM Wiki Pattern<br>3. GBrain<br>4. GStack `retro`와 `learnings_log` |

이 표는 구현 우선순위를 정하는 용도가 아니라, 각 단계에서 어떤 참고 프로젝트를 빠뜨리면 안 되는지 확인하는 색인이다. 세부 설명은 아래 항목별 정리를 기준으로 한다.

## Karpathy Autoresearch

- 출처: https://github.com/karpathy/autoresearch
- 검토한 버전: `228791f`
- 라이선스: MIT

Karpathy Autoresearch는 아주 작은 구조의 자율 실험 반복 시스템이다. 에이전트가 `program.md`를 읽고, 정해진 범위 안에서 파일을 고치고, 일정 시간 실험을 돌리고, 지표를 기록한다. 결과가 좋아지면 변경을 유지하고, 나빠지면 버린 뒤 다시 반복한다.

Muchanipo에서는 무인 개선 루프의 기준으로 삼는다. 중요한 것은 학습 코드가 아니라 운영 방식이다. 사용자는 markdown으로 연구 조직의 목표와 규칙을 적고, 에이전트는 측정 가능한 지표를 기준으로 계속 실험한다. 이 방식은 Muchanipo의 장시간 자동 개선, 지표 기록, 성공/실패 판정, 중단 전까지 계속 진행하는 원칙에 직접 연결된다.

## Karpathy LLM Wiki Pattern

- 출처: https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f

Karpathy의 LLM Wiki 패턴은 사람이 관리하는 원자료와 에이전트가 정리하는 지식 문서를 분리한다. 원자료는 `raw/` 같은 위치에 그대로 보존하고, 에이전트가 정리한 요약 문서는 `wiki/`에 둔다. 이렇게 하면 문서가 깔끔해져도 근거 원문은 계속 추적할 수 있다.

Muchanipo에서는 수집 자료와 최종 보고서를 분리하는 기준이다. 생성된 문장을 곧바로 근거로 취급하지 않고, 원문 문서, 검색된 발췌문, 인용 정보를 보고서 뒤에서도 확인할 수 있게 해야 한다.

## MiroFish

- 출처: https://github.com/666ghj/MiroFish
- 검토한 버전: `fa0f651`
- 라이선스: AGPL-3.0

MiroFish는 여러 에이전트가 함께 예측과 시뮬레이션을 수행하는 시스템이다. 입력 자료에서 가상의 세계를 만들고, 서로 다른 역할과 기억을 가진 에이전트를 생성한 뒤, 에이전트 간 상호작용을 통해 예측 보고서를 만든다.

Muchanipo에서는 다중 에이전트 연구 흐름의 주요 참고 대상이다. 질문을 여러 방향으로 쪼개는 방식, 근거를 찾은 뒤 보고서를 쓰는 방식, 인물·조직·이해관계자 기반 페르소나를 만드는 방식, 관계 정보를 고려한 토론 구조를 참고한다. 목표는 MiroFish 전체를 복제하는 것이 아니라, 근거 검색, 에이전트 프로필 구성, 구조화된 보고서 생성 방식을 가져오는 것이다.

## OASIS / CAMEL-AI

- 출처: https://github.com/camel-ai/oasis
- 관련 프로젝트: https://github.com/camel-ai/camel

OASIS는 MiroFish가 참고하는 사회적 에이전트 시뮬레이션 기반이다. 많은 에이전트가 프로필, 기억, 상호작용 규칙을 가진 상태로 통제된 환경 안에서 움직이도록 설계한다.

Muchanipo에서는 Council 단계의 개념 참고 대상이다. Council 페르소나는 단순한 역할 이름이 아니라 배경, 목표, 제약, 기억, 상호작용 규칙을 가져야 한다. 좋은 토론은 여러 모델에게 막연히 “토론해”라고 시키는 데서 나오지 않고, 입력 세계 모델이 얼마나 잘 구성되어 있는지에 달려 있다.

## GBrain

- 출처: https://github.com/garrytan/gbrain
- 검토한 버전: `8468ba2`
- 라이선스: Apache-2.0

GBrain은 markdown 파일, 혼합 검색, 기술 라우팅, 현재 결론과 사건 기록을 분리하는 지식 구조를 가진 개인 지식 저장소다. 여기서 “현재 결론”은 지금 시점의 최선의 이해이고, “사건 기록”은 어떤 근거가 언제 들어왔는지 남기는 변경 이력이다.

Muchanipo에서는 지식이 오래 버티도록 만드는 기준이다. 현재 요약과 과거 근거를 분리하고, 출처가 있는 검색, 여러 검색 결과의 순위 결합, 중복 문서 정리, 오래된 정보 표시, 작업별 기술 선택, 지식 저장소 상태 점검을 설계하는 데 참고한다.

## GStack

- 출처: https://github.com/garrytan/gstack

GStack은 에이전트가 생각하고 일하는 방식에 대한 운영 패턴 모음이다. Muchanipo에서 관련 있는 것은 `office-hours`, `plan-review`, `retro`, `learnings_log`다.

Muchanipo에서는 모호한 사용자 요청을 바로 연구로 넘기지 않고, 더 좋은 작업 요청서로 바꾸는 단계에 참고한다. 또한 계획 검토, 실행 후 배운 점 기록, 같은 실수를 반복하지 않기 위한 회고 구조에도 쓴다.

## GPTaku show-me-the-prd

- 출처: https://github.com/fivetaku/gptaku_plugins
- 플러그인: `show-me-the-prd`
- 라이선스: marketplace 저장소 기준 MIT

`show-me-the-prd`는 GPTaku 플러그인 모음에 있는 인터뷰 기반 제품 요구사항 문서 생성기다. 한 문장 아이디어를 짧은 인터뷰를 통해 제품 요구사항 문서, 데이터 모델, 단계별 개발 계획, 프로젝트 규칙 문서로 바꾸는 흐름을 제공한다.

Muchanipo에서는 첫 입력과 인터뷰 단계의 참고 대상이다. 중요한 것은 “문서 하나 생성”이 아니라, 주제에 맞춰 질문을 조정하는 방식이다. 어려운 기술어 대신 쉬운 말로 묻고, 이전 답변에 따라 다음 질문을 바꾸고, 구현 가능한 산출물을 만들며, 모호한 한 줄 아이디어가 곧바로 웹 검색으로 넘어가지 않게 막는다. 현재 repo에서도 `src/intent/office_hours.py`, `src/intent/interview_prompts.py`, `_assignments/ASSIGNMENT_C22_phase0b_v2.md`에서 이 패턴을 참조한다.

## MemPalace

- 출처: https://github.com/mempalace

MemPalace는 로컬 기억 저장소와 지식 저장소의 참고 대상이다. 현재 Muchanipo 코드에서는 문서를 가져올 때 조각 저장, 의미 기반 검색, 지식 그래프와 비슷한 검색 대상으로 나타난다.

Muchanipo에서는 “내 자료 먼저, 웹은 그 다음” 원칙에 필요하다. 외부 웹을 뒤지기 전에 사용자가 넣은 문서와 누적된 저장소 지식을 먼저 검색해야 한다.

## Plannotator

Plannotator는 사람이 중간에 검토하는 절차의 참고 대상이다. 현재 Muchanipo 코드에는 markdown 대체 경로와 HTTP 연결 형태가 이미 있다.

Muchanipo에서는 자동화하면 위험한 연구 상태를 멈추고 검토하는 기준이다. 요청이 모호하거나, 근거가 약하거나, 출처가 서로 충돌하거나, 판단의 영향이 큰 경우에는 확신 있는 문장으로 자동 작성하지 않고 사람 검토로 넘겨야 한다.

## 학술 자료 검색 API

학술 자료 검색 API는 출처가 있는 발견을 위한 근거 제공 계층이다. 하나의 제품이 아니라 다음 시스템들을 함께 본다.

- OpenAlex: https://openalex.org
- Crossref: https://www.crossref.org
- Semantic Scholar: https://www.semanticscholar.org/product/api
- Unpaywall: https://unpaywall.org/products/api
- arXiv: https://arxiv.org/help/api
- CORE: https://core.ac.uk/services/api

Muchanipo에서는 LLM이 상상한 정보가 아니라 실제 논문·기관·저널·DOI·초록·인용 정보·공개 원문 위치를 찾는 계층이다. 목표 기관, 목표 저널, 시작 논문은 모델의 추측이 아니라 이런 출처 기반 자료에서 나와야 한다.

## Nemotron-Personas-Korea

- 출처: https://huggingface.co/datasets/nvidia/Nemotron-Personas-Korea
- 현재 로컬 seed: `vault/personas/seeds/korea/agtech-farmers-sample500.jsonl`
- 로컬 sampler: `src/council/persona_sampler.py`
- 라이선스: CC-BY-4.0

Nemotron-Personas-Korea는 NVIDIA의 한국어 합성 페르소나 데이터셋이다. 한국의 실제 인구통계와 지역 분포를 반영하도록 설계되었고, 데이터셋 설명 기준으로 100만 개 기록과 700만 개 페르소나 설명을 포함한다. 지역, 나이, 성별, 학력, 직업, 주거, 가족 맥락, 경력 목표, 기술, 문화적 배경, 취미 같은 필드가 들어 있다.

Muchanipo에서는 한국 맥락 Council을 실제에 가깝게 만드는 핵심 자료다. 한국 시장, 농업 기술, 지역 정책, 의료, 소비자, 지역 도입 가능성 분석에서 막연한 “한국 사용자” 상상에 의존하면 안 된다. 가능한 경우 구조화된 한국 페르소나를 뽑고, 출처 정보를 보존하고, 주제가 요구할 때만 Council에 넣어야 한다.

현재 구현에는 농업 기술용 부분 집합이 있다. `KoreaPersonaSampler.agtech_farmer_seed(n)`은 직업, 산업, 페르소나 설명, 어려움, 목표에서 농가·농업 신호를 찾아 샘플을 뽑는다. `PersonaGenerator.propose(..., seed_personas=...)`는 뽑힌 seed를 `manifest.grounded_seed`에 저장하고 지역, 도시, 나이, 성별, 직업, 페르소나 설명, 출처를 보존한다. 실제 데이터가 없거나 읽을 수 없으면 sampler가 `synthetic-fallback` 출처를 명시하므로, 나중에 보고서에서 실제 데이터 기반인지 대체 생성값인지 구분할 수 있다.

## HACHIMI 페르소나 생성

- 로컬 구현: `src/council/persona_generator.py`
- 질문문 보조: `src/council/persona_prompts.py`
- 테스트: `tests/test_persona_generator.py`, `tests/test_persona_generator_llm.py`

HACHIMI는 현재 repo에서 Council 페르소나를 만들 때 쓰는 참고 패턴이다. 후보를 제안하고, 검증하고, 안전하지 않거나 품질이 낮은 후보를 고치거나 버리는 3단계 구조다. 이 repo에서는 규칙 기반 경로를 기본으로 두고, 선택적으로 LLM 호출 경로도 사용할 수 있다.

Muchanipo에서는 Council 품질을 결정하는 페르소나 묶음을 만드는 기준이다. 페르소나 생성은 역할 적합성, 허용 도구, 필수 산출물, 금지어, 가치 축, 안전 위험, 한국어 실명 타겟팅 위험을 확인해야 한다. 한국 현장 관점이 필요하면 Nemotron-Personas-Korea 같은 실제 분포 기반 seed도 함께 써야 한다.

## EvoAgentX / MAP-Elites 다양성

- 로컬 구현: `src/council/diversity_mapper.py`
- 테스트: `tests/test_diversity_mapper.py`

MAP-Elites는 단순히 많은 페르소나를 만드는 대신 서로 다른 관점의 다양성을 유지하는 참고 패턴이다. 현재 구현은 Council 페르소나를 위험 감수 성향과 혁신 지향성이라는 두 축 위에 배치하고, 각 칸에는 그 영역에서 가장 적합한 페르소나 하나만 남긴다.

Muchanipo에서는 Council이 비슷한 “무난한 분석가” 목소리로만 채워지는 것을 막는다. Council은 위험을 낮게 보는 사람, 높게 보는 사람, 보수적인 사람, 혁신적인 사람을 의도적으로 포함해야 하며, 어떤 관점이 비어 있는지도 드러내야 한다.

## 플러그인 슬롯 로더 / 런타임 확장 지점

- 로컬 구현: `src/runtime/plugin_loader.py`
- 설정: `config/plugin-slots.yaml`
- 테스트: `tests/test_plugin_loader.py`

Muchanipo에는 현재 완전한 OpenClaw 통합이 아니라 최소한의 플러그인 슬롯 로더가 있다. 이 로더는 `config/plugin-slots.yaml`을 읽고, `module:callable` 형식의 대상을 실제 함수로 해석하며, 실행 중에 `register_slot(...)`으로 설정된 슬롯을 덮어쓸 수 있게 한다.

현재 설정된 슬롯은 `model_router`, `runtime`, `notifier`다. Muchanipo에서는 모델 선택, 실행 환경, 알림 구현이 코드 곳곳에 하드코딩되는 것을 막는 확장 지점이다. Codex 기술, Claude 플러그인, Kimi CLI 동작, 로컬 도구, 미래의 다른 플러그인 시스템을 파이프라인 단계 전체를 다시 쓰지 않고 연결할 수 있게 한다.

## Codex Skills / Awesome Codex Skills

- 출처: https://github.com/ComposioHQ/awesome-codex-skills

Codex Skills 생태계는 반복 가능한 에이전트 작업을 재사용 가능한 기술 파일로 포장하는 참고 대상이다. 연구 품질 자체보다, 에이전트가 반복 수행할 행동을 문서화하고 선택 가능한 단위로 만드는 데 초점이 있다.

Muchanipo에서는 인터뷰, 목표 설정, 근거 검색, 근거 검토, Council, 보고서, 유지보수 같은 반복 작업을 어떤 기술로 실행할지 정리하는 데 참고한다. GBrain의 작업 선택 방식과도 연결된다.

## Claude, Gemini, Codex, Kimi CLI 제공자

다음 CLI들은 연구 방법론 프로젝트는 아니지만, 로컬 실행 제공자라는 점에서 중요하다.

- Claude Code CLI
- Gemini CLI
- OpenAI Codex CLI
- Kimi CLI

Muchanipo에서는 각 단계를 실행할 수 있는 로컬 제공자다. 중요한 것은 제공자별 역할 분담이다. 첫 입력, 인터뷰, 목표 설정, 연구, 근거 검토, Council, 보고서, 평가 단계는 각 제공자의 강점과 실패 양상에 맞춰 다른 모델이나 도구를 사용할 수 있어야 한다.

## OpenRouter, Ollama, 로컬 모델 실행 환경

OpenRouter와 Ollama는 현재 실행 환경과 모델 선택 코드에서 참고 대상으로 나타난다.

Muchanipo에서는 대체 실행 경로나 로컬 실행 경로로 유용하다. 근거 중심 연구 원칙을 대체하지는 않지만, 선호 제공자가 사용할 수 없거나, 속도 제한에 걸리거나, 비용이 너무 높을 때 앱을 계속 사용할 수 있게 한다.

## ReACT 보고서 작성 패턴

ReACT 패턴은 MiroFish의 보고서 작성 에이전트 참고를 통해 Muchanipo에 연결된다. 기본 흐름은 생각하기, 행동하기, 관찰하기, 쓰기다.

Muchanipo에서는 질문을 넣자마자 바로 보고서 문장을 쓰지 않는 기준이다. 보고서 작성자는 먼저 절을 계획하고, 도구를 호출하거나 근거를 찾고, 결과를 관찰한 다음에만 문장을 써야 한다. 이것이 평범하고 근거 없는 보고서를 막는 핵심 구조다.

## InsightForge

InsightForge는 MiroFish에서 영감을 받은 검색 패턴이며, 현재 `src/search/insight-forge.py`에 일부 반영되어 있다.

Muchanipo에서는 여러 각도에서 근거를 찾는 방식의 참고 대상이다. 질문을 나누고, 여러 출처를 검색하고, 검색 결과 순위를 합치고, 단순 웹 검색 목록이 아니라 구조화된 근거 묶음을 반환한다.

## 현재 결론 + 사건 기록

현재 결론과 사건 기록은 GBrain의 지식 모델에서 가져온 개념이다.

Muchanipo에서 현재 결론은 지금 시점의 최선의 답이고, 사건 기록은 근거가 들어오고 판단이 바뀐 이력이다. 보고서는 근거 이력을 덮어쓰면 안 된다. 새로운 근거가 기존 이해와 충돌하면 현재 결론은 바뀔 수 있지만, 사건 기록에는 무엇이 언제 왜 바뀌었는지가 남아야 한다.

## 출처 기반 연구 원칙

이 원칙은 위 참고 프로젝트 전반에 공통으로 적용된다.

Muchanipo는 LLM 출력물을 근거로 취급하면 안 된다. LLM은 질문을 만들고, 출처가 있는 사실을 요약하고, 가설을 만들고, 주장을 비판하고, 보고서 초안을 쓸 수 있다. 하지만 최종 보고서에 영향을 주는 주장은 출처 기록, 근거 식별자, 또는 명시적인 사람 검토로 추적 가능해야 한다.
