import { useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { markPendingRun } from "../lib/pendingRun";
import { pushRun } from "../lib/runsIndex";

function newRunId(): string {
  return `run-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
}

export type StudioTurn = {
  id: string;
  target: string;
  question: string;
  rationale: string;
  expected: string;
  answer?: string;
};

type ModelOption = {
  id: string;
  label: string;
  hint: string;
};

type PersonaPlanLayer = {
  layer: string;
  label: string;
  description: string;
  interviewFocus: string;
  sourceTurnId: string;
  status: "answered" | "pending";
  basis: string;
};

type PersonaPlanTemplate = {
  layer: string;
  label: string;
  description: string;
  fallbackFocus: string;
  sourceTurnId: string;
};

const FALLBACK_GOAL = "검증할 Goal";

const MODEL_OPTIONS: ModelOption[] = [
  { id: "opus-4.6", label: "Opus 4.6", hint: "깊은 인터뷰" },
  { id: "sonnet-4.5", label: "Sonnet 4.5", hint: "균형" },
  { id: "haiku-4.5", label: "Haiku 4.5", hint: "빠른 정리" },
];

const DEFAULT_TURNS: StudioTurn[] = [
  {
    id: "turn-scope",
    target: "정리 항목 · 범위가 불명확한 용어",
    question: "이 Goal에서 가장 흔들리면 안 되는 용어 하나를 골라, 포함할 의미와 제외할 의미를 나눠 적어주세요.",
    rationale: "범위가 먼저 정리되어야 Browser가 넓은 카테고리로 흐르지 않습니다.",
    expected: "포함/제외 경계",
  },
  {
    id: "turn-actor",
    target: "정리 항목 · 주체가 빠진 항목",
    question: "이 문제에서 실제로 행동하는 사람, 지불하거나 승인하는 사람, 운영하는 사람이 각각 누구인지 구분해 주세요.",
    rationale: "행위자가 분리되면 evidence route와 persona 제약이 흔들리지 않습니다.",
    expected: "사용자/구매자/운영자 구분",
  },
  {
    id: "turn-evidence",
    target: "정리 항목 · 근거가 부족한 항목",
    question: "어떤 종류의 근거가 있으면 Browser 실행 결과를 신뢰할 수 있고, 어떤 근거는 부족하다고 볼지 적어주세요.",
    rationale: "증거 경계가 있어야 실행 중 source acceptance와 report 품질을 판정할 수 있습니다.",
    expected: "증거 기준과 반례 기준",
  },
];

const PERSONA_PLAN_TEMPLATES: PersonaPlanTemplate[] = [
  {
    layer: "Layer 1",
    label: "Layer 1 · 직접 사용자",
    description: "Goal을 실제로 겪거나 사용하는 사람",
    fallbackFocus: "상황, 행동, 불편, 성공 조건",
    sourceTurnId: "turn-actor",
  },
  {
    layer: "Layer 2",
    label: "Layer 2 · 생태계 이해관계자",
    description: "도입, 운영, 비용, 규칙에 영향을 주는 사람",
    fallbackFocus: "구매/승인 주체, 운영 제약, Evidence",
    sourceTurnId: "turn-evidence",
  },
  {
    layer: "Layer 3",
    label: "Layer 3 · 교차 분야/반대 전문가",
    description: "다른 분야의 기준이나 반대 관점으로 검토하는 사람",
    fallbackFocus: "반례, 제외 의미, 위험한 가정",
    sourceTurnId: "turn-scope",
  },
];

export function buildPersonaPlanLayers(goal: string, turns: StudioTurn[]): PersonaPlanLayer[] {
  const layers: PersonaPlanLayer[] = [];
  for (const template of PERSONA_PLAN_TEMPLATES) {
    const turn = turns.find((candidate) => candidate.id === template.sourceTurnId);
    const answeredBasis = turn ? turn.answer?.trim() : "";
    const status = answeredBasis ? "answered" : "pending";
    const basis = answeredBasis || goal.trim() || FALLBACK_GOAL;
    const expected = turn?.expected ? ` · ${turn.expected}` : "";
    const target = turn?.target.replace("정리 항목 · ", "") || "Goal";
    layers.push({
      layer: template.layer,
      label: template.label,
      description: `${template.description} · ${target}`,
      interviewFocus:
        status === "answered"
          ? `${template.fallbackFocus} · 답변 기반${expected}`
          : `${template.fallbackFocus} · 질문 대기${expected}`,
      sourceTurnId: template.sourceTurnId,
      status,
      basis,
    });
  }
  return layers;
}

function loadGoal(studioId?: string): string {
  if (!studioId) return FALLBACK_GOAL;
  try {
    return localStorage.getItem(`studio:${studioId}:goal`) || FALLBACK_GOAL;
  } catch {
    return FALLBACK_GOAL;
  }
}

function coverageFromTurns(turns: StudioTurn[]): number {
  const answered = turns.filter((turn) => Boolean(turn.answer?.trim())).length;
  return Math.round((answered / turns.length) * 100);
}

function CircleIcon({ active }: { active?: boolean }) {
  return (
    <span
      className={`inline-flex h-2.5 w-2.5 rounded-full border ${
        active ? "border-[#d7d1c6] bg-[#5b5b57]" : "border-[#5b5b57] bg-transparent"
      }`}
    />
  );
}

function ProgressCard({ coverage, readyForBrowser }: { coverage: number; readyForBrowser: boolean }) {
  return (
    <section className="claude-side-card">
      <div className="flex items-center justify-between gap-3">
        <h2 className="claude-side-title">진행 상황</h2>
        <span className="text-[#8c8981]">⌄</span>
      </div>
      <div className="mt-10 flex items-center gap-2">
        <CircleIcon active={coverage >= 34} />
        <span className="h-px w-5 bg-[#4a4945]" />
        <CircleIcon active={coverage >= 67} />
        <span className="h-px w-5 bg-[#4a4945]" />
        <CircleIcon active={readyForBrowser} />
      </div>
      <p className="mt-10 text-[13px] leading-5 text-[#8f8c84]">
        Browser 준비 상태를 확인하세요. 답변이 쌓이면 Browser 실행이 열립니다.
      </p>
    </section>
  );
}

export default function StudioSession() {
  const { studioId } = useParams();
  const navigate = useNavigate();
  const goal = useMemo(() => loadGoal(studioId), [studioId]);
  const [turns, setTurns] = useState<StudioTurn[]>(DEFAULT_TURNS);
  const [draft, setDraft] = useState("");
  const [model, setModel] = useState("opus-4.6");
  const activeTurn = turns.find((turn) => !turn.answer) || turns[turns.length - 1];
  const answeredTurns = turns.filter((turn) => Boolean(turn.answer?.trim()));
  const coverage = coverageFromTurns(turns);
  const readyForBrowser = coverage >= 100;
  const studioComplete = readyForBrowser;
  const activeModel = MODEL_OPTIONS.find((option) => option.id === model) || MODEL_OPTIONS[0];
  const personaPlanLayers = useMemo(() => buildPersonaPlanLayers(goal, turns), [goal, turns]);

  function submitAnswer(e: React.FormEvent) {
    e.preventDefault();
    const answer = draft.trim();
    if (!answer) return;
    setTurns((current) =>
      current.map((turn) =>
        turn.id === activeTurn.id && !turn.answer
          ? { ...turn, answer }
          : turn,
      ),
    );
    setDraft("");
  }

  function startBrowserRun() {
    if (!readyForBrowser) return;
    const runId = newRunId();
    const brief = turns
      .map((turn) => `${turn.target}\nQ: ${turn.question}\nA: ${turn.answer || "미응답"}`)
      .join("\n\n");
    try {
      localStorage.setItem(`run:${runId}:topic`, goal);
      localStorage.setItem(`run:${runId}:studioBrief`, brief);
      localStorage.setItem(`run:${runId}:studioModel`, model);
      if (studioId) localStorage.setItem(`run:${runId}:studioId`, studioId);
      markPendingRun(runId);
      pushRun(runId, goal, { studioId: studioId || undefined, studioModel: model });
    } catch {
      /* ignore */
    }
    navigate(`/browser/${runId}`);
  }

  return (
    <div className="claude-workspace min-h-full">
      <div className="claude-session-title" data-tauri-drag-region>
        <span className="truncate">Studio</span>
        <span className="text-[#9b978e]">⌄</span>
      </div>

      <div className="claude-chat-layout">
        <main className="claude-chat-main">
          <div className="claude-message-stack">
            <article className="claude-user-bubble">
              <p>{goal}</p>
            </article>

            <article className="claude-assistant-message">
              <p className="leading-8">
                좋아요. 바로 실행하지 않고 먼저 범위, 행위자, 근거 경계를 정리할게요.
                기존 질문 문장은 유지하고, 답변은 새 기록으로 추가됩니다.
              </p>
              <div className="mt-8 flex flex-wrap gap-2 text-[13px] text-[#bdb7ac]">
                <span className="claude-chip">Deep Interview</span>
                <span className="claude-chip">Unknown</span>
                <span className="claude-chip">Ontology</span>
                <span className="claude-chip">Browser</span>
              </div>
            </article>

            {answeredTurns.map((turn) => (
              <div key={turn.id} className="space-y-8">
                <article className="claude-user-bubble">
                  <p className="whitespace-pre-wrap">{turn.answer}</p>
                </article>
                <article className="claude-assistant-message">
                  <p className="text-[15px] leading-7 text-[#d8d2c6]">{turn.rationale}</p>
                  <p className="mt-3 text-[13px] text-[#8f8c84]">{turn.target} · {turn.expected}</p>
                </article>
              </div>
            ))}

            {studioComplete ? (
              <article className="claude-assistant-message">
                <p className="mb-3 text-[13px] text-[#8f8c84]">Browser 준비</p>
                <h1 className="text-[25px] font-medium leading-9 text-[#f1eee7]">정리된 답변을 실행 그래프로 넘길 수 있어요.</h1>
                <p className="mt-4 text-[15px] leading-7 text-[#bdb7ac]">
                  이제 Browser에서 source-backed 실행, council, persona, report 흐름을 확인합니다.
                </p>
              </article>
            ) : (
              <article className="claude-assistant-message">
                <p className="mb-3 text-[13px] text-[#8f8c84]">{activeTurn.target}</p>
                <h1 className="text-[25px] font-medium leading-9 text-[#f1eee7]">{activeTurn.question}</h1>
                <p className="mt-4 text-[15px] leading-7 text-[#bdb7ac]">{activeTurn.rationale}</p>
              </article>
            )}
          </div>

          <form onSubmit={submitAnswer} className="claude-composer-wrap">
            <div className="claude-composer">
              <textarea
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                onKeyDown={(e) => {
                  if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
                    submitAnswer(e);
                  }
                }}
                rows={3}
                placeholder="메시지를 입력하세요..."
                className="claude-composer-input"
              />
              <div className="claude-composer-footer">
                <div className="flex items-center gap-3">
                  <button type="button" className="claude-icon-button" aria-label="추가">＋</button>
                  <span className="claude-mode-pill">질문⌄</span>
                </div>
                <div className="flex items-center gap-3">
                  <label className="sr-only" htmlFor="studio-model-select">모델 선택</label>
                  <select
                    id="studio-model-select"
                    value={model}
                    onChange={(e) => setModel(e.target.value)}
                    className="claude-model-select"
                    aria-label="모델 선택"
                  >
                    {MODEL_OPTIONS.map((option) => (
                      <option key={option.id} value={option.id}>
                        {option.label}
                      </option>
                    ))}
                  </select>
                  <span className="hidden text-[12px] text-[#8f8c84] md:inline">{activeModel.hint}</span>
                  <button
                    type="submit"
                    disabled={!draft.trim()}
                    className="claude-send-button"
                    aria-label="답변 기록"
                  >
                    ↑
                  </button>
                </div>
              </div>
            </div>
            <p className="mt-3 text-center text-[12px] text-[#6f6b64]">
              Muchanipo는 근거 기반으로 실행하지만, 결과를 다시 한번 확인해 주세요.
            </p>
          </form>
        </main>

        <aside className="claude-right-rail">
          <ProgressCard coverage={coverage} readyForBrowser={readyForBrowser} />

          <section className="claude-side-card">
            <div className="flex items-center justify-between gap-3">
              <h2 className="claude-side-title">Unknowns</h2>
              <span className="text-[#8c8981]">⌄</span>
            </div>
            <div className="mt-7 space-y-4">
              <div>
                <p className="mb-3 text-[13px] text-[#8f8c84]">Goal</p>
                <div className="space-y-2">
                  {turns.map((turn) => (
                    <div key={turn.id} className="claude-folder-row">
                      <span className="claude-doc-icon">▣</span>
                      <div className="min-w-0">
                        <p className="truncate text-[14px] text-[#cfc8bd]">{turn.target.replace("정리 항목 · ", "")}</p>
                        <p className="truncate text-[12px] text-[#7d7971]">{turn.expected}</p>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
              <div className="border-t border-[#34332f] pt-4">
                <button
                  type="button"
                  onClick={startBrowserRun}
                  disabled={!readyForBrowser}
                  className="claude-browser-button"
                >
                  Browser에서 실행
                </button>
              </div>
            </div>
          </section>

          <section className="claude-side-card">
            <div className="flex items-center justify-between gap-3">
              <h2 className="claude-side-title">Persona Plan</h2>
              <span className="text-[#8c8981]">⌄</span>
            </div>
            <p className="mt-5 line-clamp-2 text-[13px] leading-5 text-[#8f8c84]">
              현재 Goal 기준 · {goal}
            </p>
            <div className="mt-5 space-y-3">
              {personaPlanLayers.map((item) => (
                <div key={item.layer} className="rounded-xl border border-[#34332f] bg-[#171716] px-3 py-3">
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <p className="text-[13px] font-medium text-[#e4ded2]">{item.label}</p>
                      <p className="mt-1 text-[12px] leading-5 text-[#8f8c84]">{item.description}</p>
                    </div>
                    <span className="shrink-0 rounded-full border border-[#3f3d38] px-2 py-0.5 font-mono text-[10px] text-[#8f8c84]">
                      {item.layer}
                    </span>
                  </div>
                  <p className="mt-2 text-[11px] leading-5 text-[#7d7971]">
                    Focus · {item.interviewFocus}
                  </p>
                  <p className="mt-1 text-[11px] leading-5 text-[#7d7971]">
                    Status · {item.status} · {item.sourceTurnId}
                  </p>
                  <p className="mt-1 line-clamp-2 text-[11px] leading-5 text-[#8f8c84]">
                    Basis · {item.basis}
                  </p>
                </div>
              ))}
            </div>
          </section>

          <section className="claude-side-card">
            <div className="flex items-center justify-between gap-3">
              <h2 className="claude-side-title">Evidence</h2>
              <span className="text-[#8c8981]">⌄</span>
            </div>
            <div className="mt-7 space-y-5">
              <div>
                <p className="mb-3 text-[13px] text-[#8f8c84]">Ontology</p>
                <div className="claude-folder-row">
                  <span className="claude-doc-icon">⌁</span>
                  <span className="text-[15px] text-[#d4cec4]">Ontology</span>
                </div>
              </div>
              <div>
                <p className="mb-3 text-[13px] text-[#8f8c84]">Evidence</p>
                <div className="claude-folder-row">
                  <span className="claude-doc-icon">▤</span>
                  <span className="text-[15px] text-[#d4cec4]">Evidence</span>
                </div>
              </div>
            </div>
          </section>
        </aside>
      </div>
    </div>
  );
}
