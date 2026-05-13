import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import {
  getBufferedEvents,
  getPipelineRuntimeStatus,
  onBackendEvent,
  sendAction,
  submitIdea,
  type BackendEvent,
  type PipelineMode,
  type ResearchDepth,
} from "../lib/tauriClient";
import { deleteRun, listRuns, markRunDone, markRunFailed, markRunRunning } from "../lib/runsIndex";
import {
  PlannotatorPlanEditor,
  normalizePlanReviewEditState,
  planReviewAnnotations,
  type PlanReviewEditState,
} from "../components/PlannotatorPlanEditor";
import EvidenceIndexPanel from "../components/EvidenceIndexPanel";
import SourceDiscoveryPanel, {
  buildDiscoveredSourceMap,
  buildKnowledgeGaps,
  type DiscoveredSource,
  type KnowledgeGap,
} from "../components/SourceDiscoveryPanel";
import {
  PersonaPoolCard,
  normalizePersonaPoolSummary,
  type PersonaPoolSummary,
} from "../components/PersonaPoolCard";
import { clearPendingRun, getPendingRunAutostartDecision } from "../lib/pendingRun";

type BackendMode = "offline" | "cli" | "api";

function readBackendMode(): BackendMode {
  const value = localStorage.getItem("backend_mode");
  return value === "cli" || value === "api" || value === "offline" ? value : "offline";
}

function readCredential(k: string): string {
  return localStorage.getItem(`credential:${k}`) || sessionStorage.getItem(k) || "";
}

function readEnvsFromSettings(): Record<string, string> {
  const backendMode = readBackendMode();
  const envs: Record<string, string> = {};
  if (backendMode === "offline") {
    envs.MUCHANIPO_OFFLINE = "1";
  } else if (backendMode === "cli") {
    envs.MUCHANIPO_USE_CLI = "1";
    envs.MUCHANIPO_ONLINE = "1";
    envs.MUCHANIPO_REQUIRE_LIVE = "1";
    envs.MUCHANIPO_SOURCE_RESEARCH = "1";
  } else {
    const mimoKey = readCredential("mimo_api_key").trim();
    const opencodeGoKey = readCredential("opencode_api_key").trim();
    if (!mimoKey && !opencodeGoKey) {
      throw new Error(
        "API 실행 모드인데 MiMo 또는 OpenCode Go API Key가 앱 설정/localStorage에 없습니다. 설정에서 둘 중 하나 이상을 저장한 뒤 다시 시작하세요.",
      );
    }
    envs.MUCHANIPO_ONLINE = "1";
    envs.MUCHANIPO_REQUIRE_LIVE = "1";
    envs.MUCHANIPO_SOURCE_RESEARCH = "1";
    envs.MUCHANIPO_VERIFICATION_ROUTING = "mimo_opencode_go_only";
    envs.MUCHANIPO_API_ROUTING = "mimo_opencode_go_only";
    envs.MUCHANIPO_MODEL_ROUTING = "mimo_opencode_go_only";
    envs.MUCHANIPO_INTERVIEW_COUNSELLING = "1";
    // Do not let a single slow chairman synthesis kill an otherwise successful
    // live council run. The backend records a blocking timeout-fallback event so
    // product PASS remains honest, but Markdown report generation can complete.
    envs.MUCHANIPO_CHAIRMAN_TIMEOUT_FALLBACK = "1";
    envs.MUCHANIPO_PREFER_CLI = "0";
    envs.OPENCODE_USE_CLI = "0";
    envs.MUCHANIPO_USE_CLI = "0";
    if (mimoKey) {
      envs.XIAOMI_MIMO_API_KEY = mimoKey;
      envs.MIMO_API_KEY = mimoKey;
      envs.MIMO_MODEL = readCredential("mimo_model").trim() || "mimo-v2.5-pro";
      envs.MUCHANIPO_MIMO_MODEL = envs.MIMO_MODEL;
      const mimoBaseUrl = readCredential("mimo_base_url").trim() || "https://token-plan-sgp.xiaomimimo.com/v1";
      envs.MIMO_BASE_URL = mimoBaseUrl;
      envs.XIAOMI_MIMO_BASE_URL = mimoBaseUrl;
      envs.MUCHANIPO_PROVIDER_CHAIN = opencodeGoKey ? "mimo,opencode" : "mimo";
    }
    if (opencodeGoKey) {
      envs.OPENCODE_API_KEY = opencodeGoKey;
      envs.OPENCODE_GO_API_KEY = opencodeGoKey;
    }
    const plannotatorKey = readCredential("plannotator_key").trim();
    if (plannotatorKey) envs.PLANNOTATOR_API_KEY = plannotatorKey;
  }
  if (backendMode !== "offline") {
    const openAlexEmail = readCredential("openalex_email").trim();
    if (openAlexEmail) {
      envs.MUCHANIPO_CONTACT_EMAIL = openAlexEmail;
      envs.UNPAYWALL_EMAIL = openAlexEmail;
    }
  }
  const visualizer = localStorage.getItem("council_visualizer");
  if (visualizer === "ollama") {
    envs.MUCHANIPO_COUNCIL_VISUALIZER = "ollama";
    envs.MUCHANIPO_COUNCIL_VISUALIZER_MODEL =
      localStorage.getItem("council_visualizer_model") || "qwen3.6-a3b:latest";
  }
  return envs;
}

function readResearchDepth(): ResearchDepth {
  const value = localStorage.getItem("research_depth");
  return value === "shallow" || value === "deep" || value === "max" || value === "superdeep" ? value : "deep";
}

type Stage =
  | "intake"
  | "interview"
  | "targeting"
  | "research"
  | "evidence"
  | "council"
  | "report"
  | "vault"
  | "agents"
  | "finalize";

interface StageState {
  status: "pending" | "active" | "completed" | "error";
  message: string;
  startedAt?: number;
  completedAt?: number;
  durationMs?: number;
  lastEventAt?: number;
  lastSignal?: string;
  referenceProjects?: string[];
  artifactKeys?: string[];
}

interface TokenCard {
  persona: string;
  text: string;
  layer?: string;
  round?: number;
}

interface ResearchActivity {
  id: string;
  status:
    | "research_plan_ready"
    | "searching"
    | "source_found"
    | "source_evaluated"
    | "knowledge_gap"
    | "facet_summary"
    | "source_audit_gate"
    | "claim_evidence_gate"
    | "max_plus_benchmark_scored"
    | "research_quality_ready"
    | "done";
  query?: string;
  queryIndex?: number;
  queryCount?: number;
  backends?: string[];
  sourceTitle?: string;
  sourceUrl?: string;
  sourceGrade?: string;
  sourceKind?: string;
  accessStatus?: string;
  accepted?: boolean;
  facetIds?: string[];
  relevanceScore?: number;
  reason?: string;
  facetId?: string;
  message?: string;
  acceptedCount?: number;
  minAcceptedSources?: number;
  gapCount?: number;
  acceptedSourceCount?: number;
  rejectedSourceCount?: number;
  passed?: boolean;
  decision?: string;
  supportedClaimCount?: number;
  partialClaimCount?: number;
  unsupportedClaimCount?: number;
  supportedRatio?: number;
  benchmarkId?: string;
  metrics?: Record<string, number>;
  queries?: string[];
  queryRoutes?: ResearchQueryRoute[];
  topicAnchor?: string;
  purpose?: string;
  sourceClass?: string;
  intent?: string;
  backend?: string;
  continueReason?: string;
  authorityRequirement?: string;
  acceptanceRules?: string[];
}

interface ResearchQueryRoute {
  query?: string;
  facetId?: string;
  purpose?: string;
  sourceClass?: string;
  intent?: string;
  backend?: string;
  continueReason?: string;
  authorityRequirement?: string;
  acceptanceRules?: string[];
}

export interface ResearchPlanDisplayRow {
  query: string;
  routeDetails: string[];
  continueReason?: string;
  authorityRequirement?: string;
  acceptanceRules: string[];
}

const RESEARCH_ACTIVITY_STATUSES: ResearchActivity["status"][] = [
  "research_plan_ready",
  "searching",
  "source_found",
  "source_evaluated",
  "knowledge_gap",
  "facet_summary",
  "source_audit_gate",
  "claim_evidence_gate",
  "max_plus_benchmark_scored",
  "research_quality_ready",
  "done",
];

export interface ResearchContractState {
  researchSessionId?: string;
  appRunId?: string;
  memoryPolicy?: string;
  importedKnowledgeRefs: string[];
}

const EMPTY_RESEARCH_CONTRACT: ResearchContractState = {
  importedKnowledgeRefs: [],
};

interface CouncilActivity {
  id: string;
  kind:
    | "round_start"
    | "turn"
    | "token"
    | "round_done"
    | "provider_call_start"
    | "provider_call_done"
    | "provider_call_timeout"
    | "provider_call_error";
  round?: number;
  layer?: string;
  persona?: string;
  councilStage?: string;
  text?: string;
  provider?: string;
  providerRoute?: string;
  model?: string;
  score?: number;
  responseChars?: number;
  activePersonaCount?: number;
  activePersonaIds?: string[];
  visualizationSource?: string;
  visualizerModel?: string;
  timeoutSec?: number;
  elapsedSec?: number;
  errorClass?: string;
  blocksProductPass?: boolean;
}

interface StudioProvenance {
  studioId?: string;
  studioModel?: string;
  studioBrief?: string;
}

interface InterviewCounselling {
  mode?: string;
  rationale?: string;
  referenceInsights: string[];
  assumptionsToTest: string[];
  prdImpact?: string;
  provider?: string;
  model?: string;
}

interface InterviewPrompt {
  id: string;
  header: string;
  text: string;
  options: { key: string; label: string; value: string; description?: string }[];
  allowOther: boolean;
  multiSelect: boolean;
  preview?: string;
  index?: number;
  total?: number;
  clarity?: InterviewClarity;
  counselling?: InterviewCounselling;
}

interface HitlPrompt {
  gate: string;
  title: string;
  prompt: string;
  preview?: string;
  options: { key: string; label: string; value: string; description?: string }[];
  payload?: Record<string, unknown>;
}

interface InterviewClarity {
  phase?: string;
  mode?: string;
  researchType?: string;
  rationale?: string;
  coverageScore?: number;
  ambiguityScore?: number;
  missingDimensions: string[];
  focusDimension?: string;
  focusLabel?: string;
  focusQuestion?: string;
  round?: number;
  total?: number;
}

interface DeepInterviewDocumentArtifact {
  path: string;
  title: string;
  chars: number;
  preview: string;
}

interface DeepInterviewArtifacts {
  workflow: string;
  commit: string;
  documentCount: number;
  outputs: string[];
  evidenceMarkers: string[];
  manifest: DeepInterviewDocumentArtifact[];
}

interface RuntimeEvidence {
  runId?: string;
  startedAt?: string;
  pythonPid?: number;
  pythonExecutable?: string;
  cwd?: string;
  heartbeatStage?: string;
  heartbeatDetail?: string;
  heartbeatElapsedSec?: number;
  childPid?: number | null;
  appBinaryPath?: string | null;
  workspaceRoot?: string;
  runtimeAgeMs?: number | null;
  lastEventElapsedMs?: number | null;
  stalled?: boolean;
}

interface BrowserPersonaRow {
  id: string;
  name: string;
  role: string;
  provenance: string;
  note: string;
}

const STAGES: Stage[] = [
  "intake",
  "interview",
  "targeting",
  "research",
  "evidence",
  "council",
  "report",
  "vault",
  "agents",
  "finalize",
];

const STAGE_LABEL: Record<Stage, string> = {
  intake: "아이디어 접수",
  interview: "인터뷰",
  targeting: "타겟팅",
  research: "리서치",
  evidence: "증거 수집",
  council: "심의",
  report: "보고서",
  vault: "Vault 저장",
  agents: "에이전트 기록",
  finalize: "완료",
};

const PHASE_TO_STAGE: Record<string, Stage> = {
  STARTUP: "intake",
  INTERVIEW: "interview",
  COUNCIL: "council",
  REPORT: "report",
};

function isBackendGoneError(message: string): boolean {
  return /pipeline is not running|failed to write backend action|broken pipe/i.test(message);
}

function formatElapsed(ms?: number | null): string {
  if (ms === undefined || ms === null) return "";
  const seconds = Math.max(0, Math.round(ms / 1000));
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  return `${minutes}m ${seconds % 60}s`;
}

function isStage(value: unknown): value is Stage {
  return typeof value === "string" && STAGES.includes(value as Stage);
}

export function parseEventBoolean(value: unknown): boolean {
  if (typeof value === "boolean") return value;
  if (typeof value === "number") return value !== 0;
  if (typeof value === "string") {
    const normalized = value.trim().toLowerCase();
    return normalized === "1" || normalized === "true" || normalized === "yes";
  }
  return false;
}

function stringList(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value.map((item) => String(item)).filter(Boolean);
}

export function normalizeImportedKnowledgeRefs(value: unknown): string[] {
  if (Array.isArray(value)) return value.map((item) => String(item).trim()).filter(Boolean);
  if (typeof value === "string") {
    const trimmed = value.trim();
    if (!trimmed) return [];
    try {
      const parsed = JSON.parse(trimmed) as unknown;
      if (Array.isArray(parsed)) return parsed.map((item) => String(item).trim()).filter(Boolean);
    } catch {
      // Fall through to a single explicit ref. Do not infer or split prose.
    }
    return [trimmed];
  }
  return [];
}

export function updateResearchContractFromEvent(
  previous: ResearchContractState,
  event: BackendEvent,
): ResearchContractState {
  const importedRefs = normalizeImportedKnowledgeRefs(event.imported_knowledge_refs);
  return {
    researchSessionId: String(event.research_session_id ?? previous.researchSessionId ?? "") || undefined,
    appRunId: String(event.app_run_id ?? previous.appRunId ?? "") || undefined,
    memoryPolicy: String(event.memory_policy ?? previous.memoryPolicy ?? "") || undefined,
    importedKnowledgeRefs:
      event.imported_knowledge_refs !== undefined ? importedRefs : previous.importedKnowledgeRefs,
  };
}

export function eventFeedsCurrentSessionEvidenceLedger(event: BackendEvent): boolean {
  return (
    event.event === "research_progress" &&
    (event.status === "source_found" || event.status === "source_evaluated")
  );
}

function artifactKeyList(value: unknown): string[] {
  if (!value || typeof value !== "object" || Array.isArray(value)) return [];
  return Object.keys(value as Record<string, unknown>).sort();
}

function signalAge(now: number, lastEventAt?: number): string {
  if (!lastEventAt) return "";
  return formatElapsed(now - lastEventAt);
}

const COUNCIL_STAGE_LABEL: Record<string, string> = {
  individual: "독립 의견",
  peer_review: "상호 검토",
  chairman: "의장 종합",
  digest: "요약",
};

function initialState(): Record<Stage, StageState> {
  const init: Record<Stage, StageState> = {} as Record<Stage, StageState>;
  for (const s of STAGES) init[s] = { status: "pending", message: "" };
  return init;
}

function normalizeInterviewPrompt(event: BackendEvent): InterviewPrompt | null {
  const data =
    event.data && typeof event.data === "object"
      ? (event.data as Record<string, unknown>)
      : {};
  const id = String(event.q_id ?? event.question_id ?? data.q_id ?? data.question_id ?? "Q1");
  const text = String(event.text ?? event.prompt ?? data.text ?? data.prompt ?? "").trim();
  if (!text) return null;
  const header = String(event.header ?? data.header ?? "Interview input required");
  const preview = String(event.preview ?? data.preview ?? "").trim();
  const index = Number(event.index ?? data.index ?? 0) || undefined;
  const total = Number(event.total ?? data.total ?? 0) || undefined;
  const clarity =
    data.deep_interview && typeof data.deep_interview === "object"
      ? normalizeInterviewClarity(data.deep_interview as Record<string, unknown>)
      : undefined;
  const counsellingRaw =
    data.counselling && typeof data.counselling === "object"
      ? (data.counselling as Record<string, unknown>)
      : undefined;
  const counselling = counsellingRaw
    ? {
        mode: String(counsellingRaw.mode ?? event.counselling_mode ?? ""),
        rationale: String(counsellingRaw.rationale ?? event.counselling_rationale ?? ""),
        referenceInsights: stringList(counsellingRaw.reference_insights ?? event.reference_insights),
        assumptionsToTest: stringList(counsellingRaw.assumptions_to_test ?? event.assumptions_to_test),
        prdImpact: String(counsellingRaw.prd_impact ?? event.prd_impact ?? ""),
        provider: String(counsellingRaw.provider ?? ""),
        model: String(counsellingRaw.model ?? ""),
      }
    : undefined;

  const rawOptions = Array.isArray(event.options)
    ? event.options
    : Array.isArray(data.options)
    ? data.options
    : [];
  const options = rawOptions.map((raw, idx) => {
    if (raw && typeof raw === "object") {
      const item = raw as Record<string, unknown>;
      const key = String(item.key ?? String.fromCharCode(65 + idx));
      const label = String(item.label ?? item.text ?? item.value ?? key);
      const description = String(item.description ?? "").trim();
      return { key, label, value: String(item.value ?? label), description };
    }
    const value = String(raw);
    const match = value.match(/^([A-D])[\).\s-]+(.+)$/i);
    if (match) {
      return { key: match[1].toUpperCase(), label: match[2], value };
    }
    const key = String.fromCharCode(65 + idx);
    return { key, label: value, value };
  });

  const isDeepInterviewPrompt = isDeepInterviewSignal(id, total, clarity);

  return {
    id,
    header: isDeepInterviewPrompt ? "Deep Interview" : header,
    text,
    options,
    allowOther: isDeepInterviewPrompt || (event.allow_other !== false && data.allow_other !== false),
    multiSelect:
      !isDeepInterviewPrompt &&
      (event.multiSelect === true ||
        event.multi_select === true ||
        data.multiSelect === true ||
        data.multi_select === true),
    preview: preview || undefined,
    index,
    total,
    clarity,
    counselling,
  };
}

function isDeepInterviewSignal(
  id?: string,
  total?: number,
  clarity?: InterviewClarity,
): boolean {
  return Boolean((id && /^Q[1-6]_/.test(id)) || total === 6 || clarity);
}

function normalizeInterviewClarity(raw: Record<string, unknown>): InterviewClarity {
  const missing = Array.isArray(raw.missing_dimensions)
    ? raw.missing_dimensions.map((item) => String(item)).filter(Boolean)
    : [];
  return {
    phase: String(raw.phase ?? ""),
    mode: String(raw.mode ?? ""),
    researchType: String(raw.research_type ?? ""),
    rationale: String(raw.rationale ?? ""),
    coverageScore: Number(raw.coverage_score ?? 0) || 0,
    ambiguityScore: Number(raw.ambiguity_score ?? 0) || 0,
    missingDimensions: missing,
    focusDimension: String(raw.focus_dimension ?? ""),
    focusLabel: String(raw.focus_label ?? ""),
    focusQuestion: String(raw.focus_question ?? ""),
    round: Number(raw.round ?? 0) || undefined,
    total: Number(raw.total ?? 0) || undefined,
  };
}

function normalizeDeepInterviewProgress(event: BackendEvent): InterviewClarity {
  return normalizeInterviewClarity(event as Record<string, unknown>);
}

function normalizeDeepInterviewArtifacts(event: BackendEvent): DeepInterviewArtifacts | null {
  const data =
    event.data && typeof event.data === "object"
      ? (event.data as Record<string, unknown>)
      : {};
  const rawManifest = Array.isArray(data.document_manifest) ? data.document_manifest : [];
  const manifest = rawManifest
    .map((raw): DeepInterviewDocumentArtifact | null => {
      if (!raw || typeof raw !== "object") return null;
      const item = raw as Record<string, unknown>;
      const path = String(item.path ?? "").trim();
      if (!path) return null;
      return {
        path,
        title: String(item.title ?? path),
        chars: Number(item.chars ?? 0) || 0,
        preview: String(item.preview ?? "").trim(),
      };
    })
    .filter((item): item is DeepInterviewDocumentArtifact => item !== null);
  const outputs = Array.isArray(event.document_outputs)
    ? event.document_outputs.map((item) => String(item)).filter(Boolean)
    : manifest.map((item) => item.path);
  const evidenceMarkers = Array.isArray(event.evidence_markers)
    ? event.evidence_markers.map((item) => String(item)).filter(Boolean)
    : [];
  if (outputs.length === 0 && manifest.length === 0) return null;
  return {
    workflow: String(event.workflow ?? data.workflow ?? "show-me-the-prd"),
    commit: String(event.workflow_commit ?? data.commit ?? ""),
    documentCount: Number(event.document_count ?? outputs.length) || outputs.length,
    outputs,
    evidenceMarkers,
    manifest,
  };
}

function normalizeHitlPrompt(event: BackendEvent): HitlPrompt | null {
  const data =
    event.data && typeof event.data === "object"
      ? (event.data as Record<string, unknown>)
      : {};
  const gate = String(event.gate ?? data.gate ?? "").trim();
  if (!gate) return null;
  const title = String(event.title ?? data.title ?? `${gate} 승인`);
  const prompt = String(event.prompt ?? data.prompt ?? "계속 진행하려면 승인하세요.");
  const preview = String(event.preview ?? data.preview ?? "").trim();
  const rawOptions = Array.isArray(event.options)
    ? event.options
    : Array.isArray(data.options)
    ? data.options
    : [];
  const payload =
    data.payload && typeof data.payload === "object" && !Array.isArray(data.payload)
      ? (data.payload as Record<string, unknown>)
      : undefined;
  const options = rawOptions.map((raw, idx) => {
    if (raw && typeof raw === "object") {
      const item = raw as Record<string, unknown>;
      const key = String(item.key ?? String.fromCharCode(65 + idx));
      const label = String(item.label ?? item.text ?? item.value ?? key);
      const description = String(item.description ?? "").trim();
      return { key, label, value: String(item.value ?? label), description };
    }
    const value = String(raw);
    const key = String.fromCharCode(65 + idx);
    return { key, label: value, value };
  });
  return {
    gate,
    title,
    prompt,
    preview: preview || undefined,
    payload,
    options:
      options.length > 0
        ? options
        : [
            {
              key: "approve",
              label: "승인하고 계속",
              value: "approved",
              description: "현재 내용을 승인하고 다음 단계로 진행합니다.",
            },
          ],
  };
}

function hitlEvidenceRefs(prompt: HitlPrompt): unknown {
  if (prompt.gate !== "evidence") return undefined;
  return prompt.payload?.evidence_refs;
}

export function normalizeResearchActivity(event: BackendEvent): ResearchActivity | null {
  if (event.event !== "research_progress") return null;
  const status = String(event.status ?? "searching");
  if (!RESEARCH_ACTIVITY_STATUSES.includes(status as ResearchActivity["status"])) return null;
  const query = String(event.query ?? "").trim();
  const sourceTitle = String(event.source_title ?? "").trim();
  const sourceUrl = String(event.source_url ?? "").trim();
  const sourceGrade = String(event.source_grade ?? "").trim();
  const sourceKind = String(event.source_kind ?? "").trim();
  const accessStatus = String(event.access_status ?? "").trim();
  const reason = String(event.reason ?? "").trim();
  const facetId = String(event.facet_id ?? "").trim();
  const message = String(event.message ?? "").trim();
  const queryIndex = Number(event.query_index ?? 0) || undefined;
  const queryCount = Number(event.query_count ?? 0) || undefined;
  const relevanceScore = Number(event.relevance_score ?? Number.NaN);
  const acceptedCount = optionalNumber(event.accepted_count);
  const minAcceptedSources = optionalNumber(event.min_accepted_sources);
  const gapCount = optionalNumber(event.gap_count);
  const acceptedSourceCount = optionalNumber(event.accepted_source_count);
  const rejectedSourceCount = optionalNumber(event.rejected_source_count);
  const supportedClaimCount = optionalNumber(event.supported_claim_count ?? event.supported_count);
  const partialClaimCount = optionalNumber(event.partial_claim_count ?? event.partial_count);
  const unsupportedClaimCount = optionalNumber(event.unsupported_claim_count ?? event.unsupported_count);
  const supportedRatio = optionalNumber(event.supported_ratio);
  const decision = String(event.decision ?? "").trim();
  const benchmarkId = String(event.benchmark_id ?? "").trim();
  const topicAnchor = String(event.topic_anchor ?? event.topicAnchor ?? "").trim();
  const purpose = String(event.purpose ?? "").trim();
  const sourceClass = String(event.source_class ?? event.sourceClass ?? "").trim();
  const intent = String(event.intent ?? "").trim();
  const backend = String(event.backend ?? "").trim();
  const continueReason = String(event.continue_reason ?? event.continueReason ?? "").trim();
  const authorityRequirement = String(event.authority_requirement ?? event.authorityRequirement ?? "").trim();
  const rawAcceptanceRules = event.acceptance_rules ?? event.acceptanceRules;
  const acceptanceRules = parseStringArray(rawAcceptanceRules) ?? (String(rawAcceptanceRules ?? "").trim() ? [String(rawAcceptanceRules).trim()] : undefined);
  const metrics =
    event.metrics && typeof event.metrics === "object" && !Array.isArray(event.metrics)
      ? Object.fromEntries(
          Object.entries(event.metrics)
            .map(([key, value]) => [key, Number(value)])
            .filter(([, value]) => Number.isFinite(value)),
        )
      : undefined;
  const backends = Array.isArray(event.backends)
    ? event.backends.map((item) => String(item)).filter(Boolean)
    : undefined;
  const facetIds = Array.isArray(event.facet_ids)
    ? event.facet_ids.map((item) => String(item)).filter(Boolean)
    : undefined;
  const queries = parseStringArray(event.queries);
  const queryRoutes = normalizeResearchQueryRoutes(event.query_routes);
  const accepted = typeof event.accepted === "boolean" ? event.accepted : undefined;
  const id = [status, queryIndex ?? "", query, sourceTitle, sourceUrl, facetId, reason].join("|");
  return {
    id,
    status: status as ResearchActivity["status"],
    query: query || undefined,
    queryIndex,
    queryCount,
    backends,
    sourceTitle: sourceTitle || undefined,
    sourceUrl: sourceUrl || undefined,
    sourceGrade: sourceGrade || undefined,
    sourceKind: sourceKind || undefined,
    accessStatus: accessStatus || undefined,
    accepted,
    facetIds,
    relevanceScore: Number.isFinite(relevanceScore) ? relevanceScore : undefined,
    reason: reason || undefined,
    facetId: facetId || undefined,
    message: message || undefined,
    acceptedCount,
    minAcceptedSources,
    gapCount,
    acceptedSourceCount,
    rejectedSourceCount,
    passed: optionalBoolean(event.passed),
    decision: decision || undefined,
    supportedClaimCount,
    partialClaimCount,
    unsupportedClaimCount,
    supportedRatio,
    benchmarkId: benchmarkId || undefined,
    metrics,
    queries,
    queryRoutes,
    topicAnchor: topicAnchor || undefined,
    purpose: purpose || undefined,
    sourceClass: sourceClass || undefined,
    intent: intent || undefined,
    backend: backend || undefined,
    continueReason: continueReason || undefined,
    authorityRequirement: authorityRequirement || undefined,
    acceptanceRules,
  };
}

function optionalNumber(value: unknown): number | undefined {
  if (value === undefined || value === null || value === "") return undefined;
  const numeric = Number(value);
  return Number.isFinite(numeric) ? numeric : undefined;
}

function optionalBoolean(value: unknown): boolean | undefined {
  if (value === undefined || value === null || value === "") return undefined;
  return parseEventBoolean(value);
}

function parseJsonRecord(value: unknown): Record<string, unknown> {
  if (value && typeof value === "object" && !Array.isArray(value)) return value as Record<string, unknown>;
  if (typeof value !== "string" || !value.trim()) return {};
  try {
    const parsed = JSON.parse(value);
    return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? parsed as Record<string, unknown> : {};
  } catch {
    return {};
  }
}

function parseStringArray(value: unknown): string[] | undefined {
  const raw = typeof value === "string" ? safeJsonParse(value) : value;
  if (!Array.isArray(raw)) return undefined;
  const items = raw.map((item) => String(item).trim()).filter(Boolean);
  return items.length > 0 ? items : undefined;
}

function safeJsonParse(value: string): unknown {
  try {
    return JSON.parse(value);
  } catch {
    return value;
  }
}

function normalizeResearchQueryRoute(value: unknown): ResearchQueryRoute | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const record = value as Record<string, unknown>;
  const rawAcceptanceRules = record.acceptance_rules ?? record.acceptanceRules;
  const parsedAcceptanceRules = parseStringArray(rawAcceptanceRules);
  const fallbackAcceptanceRule = String(rawAcceptanceRules ?? "").trim();
  const route: ResearchQueryRoute = {
    query: String(record.query ?? "").trim() || undefined,
    facetId: String(record.facet_id ?? record.facetId ?? "").trim() || undefined,
    purpose: String(record.purpose ?? "").trim() || undefined,
    sourceClass: String(record.source_class ?? record.sourceClass ?? "").trim() || undefined,
    intent: String(record.intent ?? "").trim() || undefined,
    backend: String(record.backend ?? "").trim() || undefined,
    continueReason: String(record.continue_reason ?? record.continueReason ?? "").trim() || undefined,
    authorityRequirement: String(record.authority_requirement ?? record.authorityRequirement ?? "").trim() || undefined,
    acceptanceRules: parsedAcceptanceRules ?? (fallbackAcceptanceRule ? [fallbackAcceptanceRule] : undefined),
  };
  return Object.values(route).some(Boolean) ? route : null;
}

function normalizeResearchQueryRoutes(value: unknown): ResearchQueryRoute[] | undefined {
  const raw = typeof value === "string" ? safeJsonParse(value) : value;
  if (!Array.isArray(raw)) return undefined;
  const routes = raw.map(normalizeResearchQueryRoute).filter((item): item is ResearchQueryRoute => item !== null);
  return routes.length > 0 ? routes : undefined;
}

function qualitySummaryObject(event: BackendEvent, key: string): Record<string, unknown> {
  return parseJsonRecord(event[key]);
}

export function normalizeResearchQualityReadyActivity(event: BackendEvent): ResearchActivity | null {
  const isReadyEvent = event.event === "research_quality_ready";
  const isReadyDone =
    event.event === "done" &&
    (event.status === "research_quality_ready" || parseEventBoolean(event.research_quality_only));
  if (!isReadyEvent && !isReadyDone) return null;

  const artifacts = qualitySummaryObject(event, "artifacts");
  const sourceAudit =
    qualitySummaryObject(event, "source_audit_summary").accepted_source_count !== undefined
      ? qualitySummaryObject(event, "source_audit_summary")
      : qualitySummaryObject(artifacts as BackendEvent, "source_audit_summary");
  const claimEvidence =
    qualitySummaryObject(event, "claim_evidence_matrix_summary").supported_count !== undefined
      ? qualitySummaryObject(event, "claim_evidence_matrix_summary")
      : qualitySummaryObject(artifacts as BackendEvent, "claim_evidence_matrix_summary");
  const metricsValue = parseJsonRecord(event.max_plus_benchmark_metrics ?? artifacts.max_plus_benchmark_metrics);
  const metrics =
    Object.keys(metricsValue).length > 0
      ? Object.fromEntries(
          Object.entries(metricsValue)
            .map(([key, value]) => [key, Number(value)])
            .filter(([, value]) => Number.isFinite(value)),
        )
      : undefined;
  const stop = String(event.research_quality_stop ?? event.status ?? "ready_before_council").trim();
  const decision = String(event.max_plus_benchmark_decision ?? artifacts.max_plus_benchmark_decision ?? "").trim();
  return {
    id: `research_quality_ready|${stop}`,
    status: "research_quality_ready",
    message: "Research quality-first run complete before council",
    reason: stop,
    acceptedSourceCount: optionalNumber(sourceAudit.accepted_source_count),
    rejectedSourceCount: optionalNumber(sourceAudit.rejected_source_count),
    gapCount: optionalNumber(sourceAudit.gap_count),
    passed: optionalBoolean(sourceAudit.passed),
    decision: decision || undefined,
    supportedClaimCount: optionalNumber(claimEvidence.supported_claim_count ?? claimEvidence.supported_count),
    partialClaimCount: optionalNumber(claimEvidence.partial_claim_count ?? claimEvidence.partial_count),
    unsupportedClaimCount: optionalNumber(claimEvidence.unsupported_claim_count ?? claimEvidence.unsupported_count),
    supportedRatio: optionalNumber(claimEvidence.supported_ratio),
    metrics,
  };
}

function formatBenchmarkMetricLabel(key: string): string {
  if (key === "source_authority_score") return "authority";
  if (key === "weak_source_penalty") return "weak penalty";
  if (key === "expected_claim_recall") return "claim recall";
  if (key === "evidence_quote_coverage") return "quote coverage";
  if (key === "claim_traceability") return "traceability";
  return key.replaceAll("_", " ");
}

function formatBenchmarkMetricValue(value: number): string {
  if (!Number.isFinite(value)) return "";
  return `${Math.round(value * 100)}%`;
}

function uniqueStrings(values: (string | undefined)[]): string[] {
  return Array.from(new Set(values.map((item) => item?.trim()).filter((item): item is string => Boolean(item))));
}

function queryKey(value: string | undefined): string {
  return (value ?? "").trim().toLowerCase();
}

export function researchPlanDisplayRows(activity: ResearchActivity): ResearchPlanDisplayRow[] {
  const routesByQuery = new Map<string, ResearchQueryRoute>();
  for (const route of activity.queryRoutes ?? []) {
    const key = queryKey(route.query);
    if (key && !routesByQuery.has(key)) routesByQuery.set(key, route);
  }
  const orderedQueries = activity.queries && activity.queries.length > 0
    ? activity.queries
    : (activity.queryRoutes ?? []).map((route) => route.query).filter((query): query is string => Boolean(query));
  const rows = orderedQueries.map((query, index): ResearchPlanDisplayRow => {
    const route = routesByQuery.get(queryKey(query)) ?? activity.queryRoutes?.[index];
    return {
      query,
      routeDetails: [
        route?.facetId ? `facet ${route.facetId}` : undefined,
        route?.purpose ? `purpose ${route.purpose}` : undefined,
        route?.sourceClass ? `source class ${route.sourceClass}` : undefined,
        route?.intent ? `intent ${route.intent}` : undefined,
        route?.backend ? `backend ${route.backend}` : undefined,
      ].filter((item): item is string => Boolean(item)),
      continueReason: route?.continueReason,
      authorityRequirement: route?.authorityRequirement,
      acceptanceRules: route?.acceptanceRules ?? [],
    };
  });
  if (rows.length > 0) return rows;
  return (activity.query ? [activity.query] : []).map((query) => ({ query, routeDetails: [], acceptanceRules: [] }));
}

export function researchPlanSummaryChips(activity: ResearchActivity): string[] {
  const rows = researchPlanDisplayRows(activity);
  const sourceClasses = uniqueStrings((activity.queryRoutes ?? []).map((route) => route.sourceClass));
  const backends = uniqueStrings((activity.queryRoutes ?? []).map((route) => route.backend));
  return [
    `queries ${activity.queryCount ?? rows.length}`,
    sourceClasses.length > 0 ? `source classes ${sourceClasses.join(", ")}` : undefined,
    backends.length > 0 ? `backends ${backends.join(", ")}` : undefined,
    activity.topicAnchor ? `topic anchor ${activity.topicAnchor}` : undefined,
  ].filter((item): item is string => Boolean(item));
}

export function researchProgressStage(event: BackendEvent, activity?: ResearchActivity | null): Stage {
  if (event.stage === "quality_gate") return "evidence";
  if (
    event.event === "research_quality_ready" ||
    event.status === "research_quality_ready" ||
    event.status === "ready_before_council" ||
    event.status === "source_audit_gate" ||
    event.status === "claim_evidence_gate" ||
    event.status === "max_plus_benchmark_scored"
  ) return "evidence";
  if (
    activity?.status === "source_audit_gate" ||
    activity?.status === "claim_evidence_gate" ||
    activity?.status === "max_plus_benchmark_scored" ||
    activity?.status === "research_quality_ready"
  ) return "evidence";
  return "research";
}

export function researchQualityDetailChips(activity: ResearchActivity): string[] {
  const details: string[] = [];
  if (activity.passed !== undefined) details.push(`passed ${activity.passed ? "yes" : "no"}`);
  if (activity.acceptedSourceCount !== undefined) details.push(`accepted sources ${activity.acceptedSourceCount}`);
  if (activity.rejectedSourceCount !== undefined) details.push(`rejected sources ${activity.rejectedSourceCount}`);
  if (activity.gapCount !== undefined) details.push(`gaps ${activity.gapCount}`);
  if (activity.supportedClaimCount !== undefined) details.push(`supported claims ${activity.supportedClaimCount}`);
  if (activity.partialClaimCount !== undefined) details.push(`partial claims ${activity.partialClaimCount}`);
  if (activity.unsupportedClaimCount !== undefined) details.push(`unsupported claims ${activity.unsupportedClaimCount}`);
  if (activity.supportedRatio !== undefined) details.push(`supported ratio ${formatBenchmarkMetricValue(activity.supportedRatio)}`);
  if (activity.decision) details.push(`decision ${activity.decision}`);
  return details;
}

export function researchActivityCopy(activity: ResearchActivity): { label: string; message: string; signal: string } {
  if (activity.status === "research_plan_ready") {
    return {
      label: "Research plan ready",
      message: "Research plan prepared with query rationale",
      signal: `research_plan_ready · ${activity.queryCount ?? activity.queries?.length ?? 0} queries`,
    };
  }
  if (activity.status === "source_found") {
    return {
      label: "출처 확인",
      message: "출처 확인 중",
      signal: `source_found · ${activity.sourceTitle || "source"}`,
    };
  }
  if (activity.status === "source_evaluated") {
    return {
      label: activity.accepted === false ? "출처 거절" : "출처 채택",
      message: activity.accepted === false ? "출처 평가 · 거절/보류" : "출처 평가 · 채택",
      signal: `source_evaluated · ${activity.sourceTitle || "source"}`,
    };
  }
  if (activity.status === "knowledge_gap") {
    return {
      label: "근거 gap",
      message: "근거 부족 gap 발견",
      signal: `knowledge_gap · ${activity.facetId || "facet"}`,
    };
  }
  if (activity.status === "facet_summary") {
    return {
      label: "Facet 요약",
      message: "facet별 근거 커버리지 요약",
      signal: `facet_summary · gaps ${activity.gapCount ?? 0}`,
    };
  }
  if (activity.status === "source_audit_gate") {
    const details = researchQualityDetailChips(activity);
    return {
      label: "출처 감사 gate",
      message: activity.message || "출처 감사 gate 확인 중",
      signal: `source_audit_gate · ${details.join(" · ") || activity.reason || activity.message || "quality gate"}`,
    };
  }
  if (activity.status === "claim_evidence_gate") {
    const details = researchQualityDetailChips(activity);
    return {
      label: "Claim 근거 gate",
      message: activity.message || "claim 근거 matrix 확인 중",
      signal: `claim_evidence_gate · ${details.join(" · ") || activity.reason || activity.message || "quality gate"}`,
    };
  }
  if (activity.status === "max_plus_benchmark_scored") {
    const claimRecall = activity.metrics?.expected_claim_recall;
    const metricSignal = claimRecall !== undefined ? `claim recall ${formatBenchmarkMetricValue(claimRecall)}` : "quality gate";
    return {
      label: "Benchmark gate",
      message: activity.message || "명시 선택 benchmark fixture 평가",
      signal: `max_plus_benchmark_scored · ${activity.decision ? `decision ${activity.decision}` : activity.benchmarkId || metricSignal}`,
    };
  }
  if (activity.status === "research_quality_ready") {
    const details = researchQualityDetailChips(activity);
    return {
      label: "Research quality ready",
      message: activity.message || "Research quality-first run complete before council",
      signal: `research_quality_ready · ${activity.reason || "ready_before_council"}${details.length ? ` · ${details.join(" · ")}` : ""}`,
    };
  }
  return {
    label: activity.status === "done" ? "검색 완료" : "검색 중",
    message: activity.status === "done" ? "검색 완료" : "검색 쿼리 실행 중",
    signal: `${activity.status} · ${activity.query || "query"}`,
  };
}

function compactPersonaName(value: string | undefined): string {
  if (!value) return "persona";
  return value.replace(/^persona-/, "P-").replace(/^mirofish-entity-/, "M-");
}

const PERSONA_PROVENANCE_LABELS = {
  samplePool: "Persona sample pool",
  fallbackTemplate: "Fallback template",
  diversitySampling: "Diversity sampling",
  councilProtocol: "Council protocol",
  backendSelected: "Backend selected persona",
} as const;

const BROWSER_PERSONA_FALLBACK_ROWS: BrowserPersonaRow[] = [
  {
    id: "layer-1-direct-user",
    name: "Layer 1 · 직접 사용자",
    role: "Goal을 직접 겪는 사용자",
    provenance: PERSONA_PROVENANCE_LABELS.fallbackTemplate,
    note: "pending backend selection",
  },
  {
    id: "layer-2-ecosystem",
    name: "Layer 2 · 생태계 이해관계자",
    role: "도입, 운영, 비용, 규칙 이해관계자",
    provenance: PERSONA_PROVENANCE_LABELS.samplePool,
    note: "pending backend selection",
  },
  {
    id: "layer-3-contrarian",
    name: "Layer 3 · 교차 분야/반대 전문가",
    role: "반례와 다른 분야 기준 검토",
    provenance: PERSONA_PROVENANCE_LABELS.diversitySampling,
    note: "pending backend selection",
  },
  {
    id: "council-protocol",
    name: "Council protocol",
    role: "심의 순서와 발언 규칙",
    provenance: PERSONA_PROVENANCE_LABELS.councilProtocol,
    note: "protocol label; selected persona ids replace fallback rows when available",
  },
];

function browserPersonaRows(personas: string[]): BrowserPersonaRow[] {
  const selected = personas.map((persona, index) => ({
    id: `selected-${persona}-${index}`,
    name: compactPersonaName(persona),
    role: index === 0 ? "selected persona" : "selected council persona",
    provenance: PERSONA_PROVENANCE_LABELS.backendSelected,
    note: "received from council active_persona_ids",
  }));
  return selected.length > 0 ? selected : BROWSER_PERSONA_FALLBACK_ROWS;
}

function clearRunScopedSessionKeys(runId: string): void {
  const keysToRemove: string[] = [];
  for (let index = 0; index < sessionStorage.length; index += 1) {
    const key = sessionStorage.key(index);
    if (!key) continue;
    if (
      key.startsWith(`muchanipo:auto-answer:${runId}:`) ||
      key.startsWith(`muchanipo:auto-approve:${runId}:`)
    ) {
      keysToRemove.push(key);
    }
  }
  for (const key of keysToRemove) {
    sessionStorage.removeItem(key);
  }
}

function pushCouncilActivity(
  prev: CouncilActivity[],
  activity: CouncilActivity,
): CouncilActivity[] {
  const withoutDuplicate = prev.filter((item) => item.id !== activity.id);
  return [activity, ...withoutDuplicate].slice(0, 12);
}

export function deriveBackendSignalStatus({
  runId,
  runtimeRunId,
  runtimeHeartbeatStage,
  hasVisibleBackendHeartbeat,
}: {
  runId?: string;
  runtimeRunId?: string;
  runtimeHeartbeatStage?: string;
  hasVisibleBackendHeartbeat: boolean;
}): string {
  if ((runtimeRunId === runId && runtimeHeartbeatStage) || hasVisibleBackendHeartbeat) {
    return "Backend run signals observed";
  }
  return "Waiting for live backend signal";
}

export default function RunProgress() {
  const { runId } = useParams<{ runId: string }>();
  const navigate = useNavigate();
  const [stages, setStages] = useState<Record<Stage, StageState>>(() => initialState());
  const [councilRound, setCouncilRound] = useState<number>(0);
  const [topic, setTopic] = useState<string>("");
  const [studioProvenance, setStudioProvenance] = useState<StudioProvenance | null>(null);
  const [tokenCards, setTokenCards] = useState<TokenCard[]>([]);
  const [researchActivity, setResearchActivity] = useState<ResearchActivity[]>([]);
  const [researchContract, setResearchContract] = useState<ResearchContractState>(EMPTY_RESEARCH_CONTRACT);
  const [discoveredSources, setDiscoveredSources] = useState<Map<string, DiscoveredSource>>(() => {
    if (!runId) return new Map();
    try {
      const raw = localStorage.getItem(`run:${runId}:sources`);
      if (raw) {
        const parsed = JSON.parse(raw) as [string, DiscoveredSource][];
        return new Map(parsed);
      }
    } catch { /* ignore */ }
    return new Map();
  });
  const [knowledgeGaps, setKnowledgeGaps] = useState<KnowledgeGap[]>(() => {
    if (!runId) return [];
    try {
      const raw = localStorage.getItem(`run:${runId}:gaps`);
      if (raw) return JSON.parse(raw) as KnowledgeGap[];
    } catch { /* ignore */ }
    return [];
  });
  const [councilActivity, setCouncilActivity] = useState<CouncilActivity[]>([]);
  const [councilPersonas, setCouncilPersonas] = useState<string[]>([]);
  const [personaPool, setPersonaPool] = useState<PersonaPoolSummary | null>(null);
  const [runError, setRunError] = useState<string | null>(null);
  const runErrorRef = useRef<string | null>(null);
  const [runWarnings, setRunWarnings] = useState<string[]>([]);
  const [reportPreview, setReportPreview] = useState("");
  const [finalReport, setFinalReport] = useState("");
  const [interviewPrompt, setInterviewPrompt] = useState<InterviewPrompt | null>(null);
  const [interviewClarity, setInterviewClarity] = useState<InterviewClarity | null>(null);
  const [interviewArtifacts, setInterviewArtifacts] = useState<DeepInterviewArtifacts | null>(null);
  const [interviewAnswer, setInterviewAnswer] = useState("");
  const [interviewSelections, setInterviewSelections] = useState<string[]>([]);
  const [interviewSubmitting, setInterviewSubmitting] = useState(false);
  const [interviewError, setInterviewError] = useState<string | null>(null);
  const [hitlPrompt, setHitlPrompt] = useState<HitlPrompt | null>(null);
  const [planReviewEdits, setPlanReviewEdits] = useState<PlanReviewEditState | null>(null);
  const [hitlSubmitting, setHitlSubmitting] = useState(false);
  const [hitlError, setHitlError] = useState<string | null>(null);
  const [runtimeEvidence, setRuntimeEvidence] = useState<RuntimeEvidence | null>(null);
  const [hasReceivedHeartbeat, setHasReceivedHeartbeat] = useState(false);
  const [aborting, setAborting] = useState(false);
  const [now, setNow] = useState(() => Date.now());
  const unlistenRef = useRef<(() => void) | null>(null);
  const chunkKeysRef = useRef<Set<string>>(new Set());
  const finalReportReceivedRef = useRef(false);
  const planReviewEditCount = planReviewAnnotations(planReviewEdits).length;
  const activeDeepInterviewPrompt = interviewPrompt
    ? isDeepInterviewSignal(interviewPrompt.id, interviewPrompt.total, interviewPrompt.clarity)
    : false;
  const unknownDimensions = interviewClarity?.missingDimensions.filter(Boolean).slice(0, 6) ?? [];
  const ontologyNodes = Array.from(
    new Set(
      [
        interviewClarity?.focusLabel,
        interviewClarity?.focusDimension,
        ...unknownDimensions.slice(0, 3),
      ]
        .map((item) => item?.trim())
        .filter((item): item is string => Boolean(item)),
    ),
  );

  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, []);

  const failRun = useCallback(
    (message: string) => {
      runErrorRef.current = message;
      setRunError(message);
      setInterviewSubmitting(false);
      setHitlSubmitting(false);
      if (runId) {
        markRunFailed(runId);
      }
    },
    [runId],
  );

  const startRunFromTopic = useCallback(
    async (runTopic: string, options: { clearArtifacts?: boolean; warning?: string } = {}) => {
      if (!runId) return false;
      const trimmed = runTopic.trim();
      if (!trimmed) {
        failRun("주제 정보가 없습니다.");
        return false;
      }

      runErrorRef.current = null;
      setRunError(null);
      setRunWarnings(options.warning ? [options.warning] : []);
      setTopic(trimmed);

      if (options.clearArtifacts) {
        chunkKeysRef.current.clear();
        finalReportReceivedRef.current = false;
        setStages(initialState());
        setCouncilRound(0);
        setTokenCards([]);
        setResearchActivity([]);
        setDiscoveredSources(new Map());
        setKnowledgeGaps([]);
        if (runId) {
          localStorage.removeItem(`run:${runId}:sources`);
          localStorage.removeItem(`run:${runId}:gaps`);
        }
        setCouncilActivity([]);
        setCouncilPersonas([]);
        setPersonaPool(null);
        setReportPreview("");
        setFinalReport("");
        setInterviewPrompt(null);
        setInterviewClarity(null);
        setInterviewArtifacts(null);
        setInterviewAnswer("");
        setInterviewSelections([]);
        setInterviewError(null);
        setHitlPrompt(null);
        setPlanReviewEdits(null);
        setHitlError(null);
        setHitlSubmitting(false);
        setRuntimeEvidence(null);
        setHasReceivedHeartbeat(false);
        try {
          for (const suffix of ["report", "report_path", "vault_path", "chapter_count", "pending", "pending_at"]) {
            localStorage.removeItem(`run:${runId}:${suffix}`);
          }
          sessionStorage.removeItem(`run:${runId}:pending_session`);
          clearRunScopedSessionKeys(runId);
          markRunRunning(runId);
        } catch {
          /* ignore */
        }
      }

      try {
        const pipelineMode =
          (localStorage.getItem("pipeline_mode") as PipelineMode | null) || "full";
        await submitIdea(trimmed, pipelineMode, readResearchDepth(), readEnvsFromSettings(), runId);
        return true;
      } catch (err) {
        const msg = err instanceof Error ? err.message : String(err);
        failRun(msg);
        return false;
      }
    },
    [failRun, runId],
  );

  useEffect(() => {
    if (!runId) return;
    try {
      setTopic(localStorage.getItem(`run:${runId}:topic`) || "");
      const prov: StudioProvenance = {};
      const studioId = localStorage.getItem(`run:${runId}:studioId`);
      const studioModel = localStorage.getItem(`run:${runId}:studioModel`);
      const studioBrief = localStorage.getItem(`run:${runId}:studioBrief`);
      if (studioId) prov.studioId = studioId;
      if (studioModel) prov.studioModel = studioModel;
      if (studioBrief) prov.studioBrief = studioBrief;
      if (prov.studioId || prov.studioModel || prov.studioBrief) {
        setStudioProvenance(prov);
      }
    } catch {
      /* ignore */
    }
  }, [runId]);

  useEffect(() => {
    let mounted = true;
    chunkKeysRef.current.clear();
    finalReportReceivedRef.current = false;
    const handleEvent = (event: BackendEvent) => {
      if (!mounted) return;
      if (
        event.research_session_id !== undefined ||
        event.app_run_id !== undefined ||
        event.memory_policy !== undefined ||
        event.imported_knowledge_refs !== undefined
      ) {
        setResearchContract((prev) => updateResearchContractFromEvent(prev, event));
      }

      if (event.event === "error") {
        const message = (event.message as string) || "오류가 발생했어요.";
        const isGenericExit = message.startsWith("python pipeline exited with");
        if (isGenericExit && runErrorRef.current) {
          setRunWarnings((prev) =>
            [message, ...prev.filter((item) => item !== message)].slice(0, 3),
          );
        } else {
          failRun(message);
        }
        setInterviewSubmitting(false);
        setHitlSubmitting(false);
        setStages((prev) => {
          const next = { ...prev };
          const active = STAGES.find((stage) => next[stage].status === "active");
          if (active) {
            next[active] = {
              ...next[active],
              status: "error",
              completedAt: Date.now(),
              message,
            };
          }
          return next;
        });
        return;
      }

      if (event.event === "warning") {
        const message = (event.message as string) || "경고가 발생했어요.";
        setRunWarnings((prev) => [message, ...prev.filter((item) => item !== message)].slice(0, 3));
        return;
      }

      if (event.event === "run_started") {
        setStages((prev) => ({
          ...prev,
          intake: {
            ...prev.intake,
            status: prev.intake.status === "completed" ? "completed" : "active",
            startedAt: prev.intake.startedAt ?? Date.now(),
            lastEventAt: Date.now(),
            lastSignal: "run_started",
            message: "Python backend 시작 확인",
          },
        }));
        setRuntimeEvidence((prev) => ({
          ...(prev ?? {}),
          runId: String(event.run_id ?? ""),
          startedAt: String(event.started_at ?? ""),
          pythonPid: Number(event.python_pid ?? 0) || undefined,
          pythonExecutable: String(event.python_executable ?? ""),
          cwd: String(event.cwd ?? ""),
          heartbeatStage: "startup",
          heartbeatDetail: "run_started",
          stalled: false,
        }));
        return;
      }

      if (event.event === "pipeline_heartbeat") {
        setHasReceivedHeartbeat(true);
        const stage = isStage(event.stage) ? event.stage : null;
        if (stage) {
          setStages((prev) => {
            const current = prev[stage];
            if (current.status === "completed" || current.status === "error") return prev;
            return {
              ...prev,
              [stage]: {
                ...current,
                status: current.status === "pending" ? "active" : current.status,
                startedAt: current.startedAt ?? Date.now(),
                lastEventAt: Date.now(),
                lastSignal: event.detail
                  ? `heartbeat · ${String(event.detail)}`
                  : "heartbeat",
                message: "실행 중 · heartbeat 수신",
              },
            };
          });
        }
        setRuntimeEvidence((prev) => ({
          ...(prev ?? {}),
          runId: String(event.run_id ?? prev?.runId ?? ""),
          pythonPid: Number(event.python_pid ?? prev?.pythonPid ?? 0) || undefined,
          pythonExecutable: String(event.python_executable ?? prev?.pythonExecutable ?? ""),
          heartbeatStage: String(event.stage ?? ""),
          heartbeatDetail: String(event.detail ?? ""),
          heartbeatElapsedSec: Number(event.elapsed_sec ?? 0) || undefined,
          stalled: false,
        }));
        return;
      }

      if (event.event === "research_progress") {
        const activity = normalizeResearchActivity(event);
        if (!activity) return;
        const targetStage = researchProgressStage(event, activity);
        const copy = researchActivityCopy(activity);
        setStages((prev) => ({
          ...prev,
          [targetStage]: {
            ...prev[targetStage],
            status: prev[targetStage].status === "completed" ? "completed" : "active",
            startedAt: prev[targetStage].startedAt ?? Date.now(),
            lastEventAt: Date.now(),
            lastSignal: copy.signal,
            message: copy.message,
          },
        }));
        setResearchActivity((prev) => {
          const withoutDuplicate = prev.filter((item) => item.id !== activity.id);
          return [activity, ...withoutDuplicate].slice(0, 8);
        });
        setDiscoveredSources((prev) => {
          const next = buildDiscoveredSourceMap(prev, activity);
          if (runId) {
            try {
              localStorage.setItem(`run:${runId}:sources`, JSON.stringify(Array.from(next.entries())));
            } catch { /* ignore */ }
          }
          return next;
        });
        setKnowledgeGaps((prev) => {
          const next = buildKnowledgeGaps(prev, activity);
          if (runId) {
            try {
              localStorage.setItem(`run:${runId}:gaps`, JSON.stringify(next));
            } catch { /* ignore */ }
          }
          return next;
        });
        return;
      }

      if (event.event === "research_quality_ready") {
        const activity = normalizeResearchQualityReadyActivity(event);
        if (!activity) return;
        const copy = researchActivityCopy(activity);
        setStages((prev) => ({
          ...prev,
          evidence: {
            ...prev.evidence,
            status: "completed",
            completedAt: Date.now(),
            durationMs: prev.evidence.startedAt ? Date.now() - prev.evidence.startedAt : prev.evidence.durationMs,
            lastEventAt: Date.now(),
            lastSignal: copy.signal,
            message: copy.message,
          },
          finalize: {
            ...prev.finalize,
            status: "completed",
            startedAt: prev.finalize.startedAt ?? Date.now(),
            completedAt: Date.now(),
            lastEventAt: Date.now(),
            lastSignal: "research_quality_ready",
            message: "Research quality-first bounded run complete",
          },
        }));
        setResearchActivity((prev) => {
          const withoutDuplicate = prev.filter((item) => item.id !== activity.id);
          return [activity, ...withoutDuplicate].slice(0, 8);
        });
        return;
      }

      if (event.event === "deep_interview_progress") {
        const clarity = normalizeDeepInterviewProgress(event);
        setInterviewClarity(clarity);
        setStages((prev) => ({
          ...prev,
          interview: {
            ...prev.interview,
            status: prev.interview.status === "completed" ? "completed" : "active",
            startedAt: prev.interview.startedAt ?? Date.now(),
            lastEventAt: Date.now(),
            lastSignal: clarity?.focusLabel
              ? `deep_interview · ${clarity.focusLabel}`
              : "deep_interview",
            message:
              clarity?.coverageScore !== undefined
                ? `질문 명확화 중 · coverage ${Math.round(clarity.coverageScore * 100)}%`
                : "질문 명확화 중",
          },
        }));
        return;
      }

      if (event.event === "deep_interview_artifacts") {
        const artifacts = normalizeDeepInterviewArtifacts(event);
        if (artifacts) setInterviewArtifacts(artifacts);
        return;
      }

      if (event.event === "interview_question") {
        const prompt = normalizeInterviewPrompt(event);
        if (prompt) {
          setStages((prev) => ({
            ...prev,
            interview: {
              ...prev.interview,
              status: prev.interview.status === "completed" ? "completed" : "active",
              startedAt: prev.interview.startedAt ?? Date.now(),
              lastEventAt: Date.now(),
              lastSignal: `interview_question · ${prompt.id}`,
              message: "사용자 답변 대기",
            },
          }));
          setInterviewPrompt(prompt);
          if (prompt.clarity) setInterviewClarity(prompt.clarity);
          setInterviewAnswer("");
          setInterviewSelections([]);
          setInterviewError(null);
          setInterviewSubmitting(false);
        }
        return;
      }

      if (event.event === "hitl_gate") {
        const prompt = normalizeHitlPrompt(event);
        if (prompt) {
          const gateStage: Stage = prompt.gate === "plan" ? "targeting" : "evidence";
          setStages((prev) => ({
            ...prev,
            [gateStage]: {
              ...prev[gateStage],
              status: prev[gateStage].status === "completed" ? "completed" : "active",
              startedAt: prev[gateStage].startedAt ?? Date.now(),
              lastEventAt: Date.now(),
              lastSignal: `hitl_gate · ${prompt.gate}`,
              message: "사용자 검토 대기",
            },
          }));
          setHitlPrompt(prompt);
          setPlanReviewEdits(normalizePlanReviewEditState(prompt));
          setHitlError(null);
          setHitlSubmitting(false);
        }
        return;
      }

      if (event.event === "phase_change" && typeof event.phase === "string") {
        const stage = PHASE_TO_STAGE[event.phase.toUpperCase()];
        if (!stage) return;
        if (stage !== "interview") {
          setInterviewPrompt(null);
          setInterviewSubmitting(false);
        }
        setHitlPrompt(null);
        setPlanReviewEdits(null);
        setHitlSubmitting(false);
        // Stage transitions carry pipeline artifacts; mine persona telemetry
        // (seed source, validation/diversity framework, council protocol, pool
        // counts, fallbacks_used) so Browser shows the real Studio→Browser
        // persona handoff rather than only ids.
        const phaseData = (event as Record<string, unknown>).data;
        const artifactsCandidate =
          phaseData && typeof phaseData === "object" && !Array.isArray(phaseData)
            ? (phaseData as Record<string, unknown>).artifacts
            : (event as Record<string, unknown>).artifacts;
        const artifacts =
          artifactsCandidate && typeof artifactsCandidate === "object" && !Array.isArray(artifactsCandidate)
            ? (artifactsCandidate as Record<string, unknown>)
            : null;
        const summary = normalizePersonaPoolSummary(artifacts);
        if (summary) {
          setPersonaPool(summary);
        }
        setStages((prev) => {
          const next = { ...prev };
          const currentIndex = STAGES.indexOf(stage);
          STAGES.forEach((candidate, idx) => {
            if (idx < currentIndex && next[candidate].status !== "completed") {
              next[candidate] = {
                ...next[candidate],
                status: "completed",
                completedAt: Date.now(),
                message: "완료",
              };
            }
          });
          next[stage] = {
            ...next[stage],
            status: "active",
            startedAt: next[stage].startedAt ?? Date.now(),
            lastEventAt: Date.now(),
            lastSignal: `phase_change · ${event.phase}`,
            message: "진행 중 · phase event 수신",
          };
          return next;
        });
        return;
      }

      if (
        (event.event === "stage_started" || event.event === "stage_completed") &&
        typeof event.stage === "string"
      ) {
        const stage = event.stage as Stage;
        if (!STAGES.includes(stage)) return;
        if (event.event === "stage_started" && stage !== "interview") {
          setInterviewPrompt(null);
          setInterviewSubmitting(false);
        }
        if (event.event === "stage_started") {
          setHitlPrompt(null);
          setHitlSubmitting(false);
        }
        setStages((prev) => {
          const next = { ...prev };
          const current = { ...next[stage] };
          const referenceProjects = stringList(event.reference_projects);
          const artifactKeys = artifactKeyList(event.artifacts);
          if (event.event === "stage_started") {
            current.status = "active";
            current.startedAt = Date.now();
            current.lastEventAt = Date.now();
            current.lastSignal = "stage_started";
            current.message = "실행 시작 · backend event 수신";
          } else {
            current.status = "completed";
            current.completedAt = Date.now();
            if (current.startedAt) current.durationMs = current.completedAt - current.startedAt;
            current.lastEventAt = Date.now();
            current.lastSignal = "stage_completed";
            current.message = "완료 · backend event 수신";
          }
          if (referenceProjects.length > 0) current.referenceProjects = referenceProjects;
          if (artifactKeys.length > 0) current.artifactKeys = artifactKeys;
          next[stage] = current;
          return next;
        });
        return;
      }

      if (event.event === "council_round_start" && typeof event.round === "number") {
        setCouncilRound(event.round);
        setStages((prev) => ({
          ...prev,
          council: {
            ...prev.council,
            status: prev.council.status === "completed" ? "completed" : "active",
            startedAt: prev.council.startedAt ?? Date.now(),
            lastEventAt: Date.now(),
            lastSignal: `council_round_start · R${event.round}`,
            message: "페르소나 라운드 시작",
          },
        }));
        const activePersonaIds = Array.isArray(event.active_persona_ids)
          ? event.active_persona_ids.map((item) => String(item)).filter(Boolean)
          : [];
        if (activePersonaIds.length > 0) setCouncilPersonas(activePersonaIds);
        setCouncilActivity((prev) =>
          pushCouncilActivity(prev, {
            id: `round-start:${event.round}:${event.layer ?? ""}`,
            kind: "round_start",
            round: event.round,
            layer: String(event.layer ?? ""),
            activePersonaCount: Number(event.active_persona_count ?? activePersonaIds.length) || undefined,
            activePersonaIds,
          }),
        );
        return;
      }

      if (event.event === "council_turn" && typeof event.round === "number") {
        const persona = String(event.persona ?? "");
        const councilStage = String(event.council_stage ?? "");
        setStages((prev) => ({
          ...prev,
          council: {
            ...prev.council,
            status: prev.council.status === "completed" ? "completed" : "active",
            startedAt: prev.council.startedAt ?? Date.now(),
            lastEventAt: Date.now(),
            lastSignal: `council_turn · ${persona || "persona"}`,
            message: "페르소나 응답 수신",
          },
        }));
        setCouncilActivity((prev) =>
          pushCouncilActivity(prev, {
            id: `turn:${event.round}:${event.layer ?? ""}:${councilStage}:${persona}:${event.response_chars ?? ""}`,
            kind: "turn",
            round: event.round,
            layer: String(event.layer ?? ""),
            persona,
            councilStage,
            provider: String(event.provider ?? ""),
            responseChars: Number(event.response_chars ?? 0) || undefined,
          }),
        );
        return;
      }

      if (event.event === "council_persona_token") {
        const persona = String(event.persona ?? "agent");
        const layer = event.layer as string | undefined;
        const round = event.round as number | undefined;
        const delta = String(event.delta ?? "");
        setTokenCards((prev) => {
          const last = prev[prev.length - 1];
          if (last && last.persona === persona && last.layer === layer && last.round === round) {
            return [...prev.slice(0, -1), { ...last, text: last.text + delta }];
          }
          return [...prev, { persona, text: delta, layer, round }].slice(-12);
        });
        if (delta.trim()) {
          setStages((prev) => ({
            ...prev,
            council: {
              ...prev.council,
              status: prev.council.status === "completed" ? "completed" : "active",
              startedAt: prev.council.startedAt ?? Date.now(),
              lastEventAt: Date.now(),
              lastSignal: `council_token · ${persona}`,
              message: "토론 시각화 토큰 수신",
            },
          }));
          setCouncilActivity((prev) =>
            pushCouncilActivity(prev, {
              id: `token:${round ?? ""}:${layer ?? ""}:${event.council_stage ?? ""}:${persona}:${delta.slice(0, 80)}`,
              kind: "token",
              round,
              layer,
              persona,
              councilStage: String(event.council_stage ?? ""),
              text: delta,
              visualizationSource: String(event.visualization_source ?? ""),
              visualizerModel: String(event.visualizer_model ?? ""),
            }),
          );
        }
        return;
      }

      if (event.event === "council_round_done" && typeof event.round === "number") {
        setCouncilActivity((prev) =>
          pushCouncilActivity(prev, {
            id: `round-done:${event.round}:${event.layer ?? ""}`,
            kind: "round_done",
            round: event.round,
            layer: String(event.layer ?? ""),
            score: Number(event.score ?? 0) || undefined,
            text: event.stopped ? String(event.stop_reason ?? "") : undefined,
          }),
        );
        return;
      }

      if (
        (event.event === "council_provider_call_start" ||
          event.event === "council_provider_call_done" ||
          event.event === "council_provider_call_timeout" ||
          event.event === "council_provider_call_error") &&
        typeof event.round === "number"
      ) {
        const persona = String(event.persona ?? "persona");
        const councilStage = String(event.council_stage ?? "council");
        const providerRoute = String(event.provider_route ?? "");
        const provider = String(event.provider ?? "");
        const model = String(event.model ?? "");
        const elapsedSec = Number(event.elapsed_sec ?? 0) || undefined;
        const timeoutSec = Number(event.timeout_sec ?? 0) || undefined;
        const errorClass = String(event.error_class ?? "");
        const errorText = String(event.error ?? "").trim();
        const blocksProductPass = parseEventBoolean(event.blocks_product_pass);
        setStages((prev) => ({
          ...prev,
          council: {
            ...prev.council,
            status: prev.council.status === "completed" ? "completed" : "active",
            startedAt: prev.council.startedAt ?? Date.now(),
            lastEventAt: Date.now(),
            lastSignal: `${event.event} · ${councilStage}`,
            message:
              event.event === "council_provider_call_start"
                ? "Council provider 호출 시작"
                : event.event === "council_provider_call_done"
                  ? "Council provider 응답 수신"
                  : event.event === "council_provider_call_timeout"
                    ? "Council provider 타임아웃 감지"
                    : "Council provider 오류 감지",
          },
        }));
        setCouncilActivity((prev) =>
          pushCouncilActivity(prev, {
            id: `provider:${event.event}:${event.round}:${event.layer ?? ""}:${councilStage}:${persona}:${providerRoute}:${provider}:${elapsedSec ?? timeoutSec ?? ""}`,
            kind:
              event.event === "council_provider_call_start"
                ? "provider_call_start"
                : event.event === "council_provider_call_done"
                  ? "provider_call_done"
                  : event.event === "council_provider_call_timeout"
                    ? "provider_call_timeout"
                    : "provider_call_error",
            round: event.round,
            layer: String(event.layer ?? ""),
            persona,
            councilStage,
            providerRoute: providerRoute || undefined,
            provider: provider || undefined,
            model: model || undefined,
            responseChars: Number(event.response_chars ?? 0) || undefined,
            elapsedSec,
            timeoutSec,
            errorClass: errorClass || undefined,
            blocksProductPass,
            text: errorText || undefined,
          }),
        );
        return;
      }

      if (event.event === "report_chunk" && runId) {
        const chunk = String(event.markdown ?? event.delta ?? "");
        const key = chunk.trim();
        if (!key || finalReportReceivedRef.current || chunkKeysRef.current.has(key)) return;
        chunkKeysRef.current.add(key);
        setStages((prev) => ({
          ...prev,
          report: {
            ...prev.report,
            status: prev.report.status === "completed" ? "completed" : "active",
            startedAt: prev.report.startedAt ?? Date.now(),
            lastEventAt: Date.now(),
            lastSignal: `report_chunk · ${event.chapter_no ?? event.title ?? "chapter"}`,
            message: "보고서 chunk 수신",
          },
        }));
        setReportPreview((prev) => {
          const next = `${prev}${prev ? "\n\n" : ""}${chunk}`;
          try {
            localStorage.setItem(`run:${runId}:report`, next);
          } catch {
            /* ignore */
          }
          return next;
        });
        return;
      }

      if (event.event === "final_report" && runId) {
        const markdown = (event.markdown as string) || "";
        const reportPath = (event.report_path as string) || "";
        const vaultPath = (event.vault_path as string) || "";
        const chapterCount = (event.chapter_count as number) || 0;
        finalReportReceivedRef.current = true;
        chunkKeysRef.current.clear();
        setStages((prev) => ({
          ...prev,
          report: {
            ...prev.report,
            status: "completed",
            completedAt: Date.now(),
            durationMs: prev.report.startedAt ? Date.now() - prev.report.startedAt : prev.report.durationMs,
            lastEventAt: Date.now(),
            lastSignal: "final_report",
            message: "최종 보고서 수신",
          },
        }));
        try {
          if (markdown) localStorage.setItem(`run:${runId}:report`, markdown);
          localStorage.setItem(`run:${runId}:report_path`, reportPath);
          if (vaultPath) localStorage.setItem(`run:${runId}:vault_path`, vaultPath);
          localStorage.setItem(`run:${runId}:chapter_count`, String(chapterCount));
        } catch {
          /* ignore */
        }
        if (markdown) setFinalReport(markdown);
        return;
      }

      if (event.event === "done" && runId && !runErrorRef.current) {
        const qualityReadyActivity = normalizeResearchQualityReadyActivity(event);
        setInterviewSubmitting(false);
        setInterviewPrompt(null);
        setHitlSubmitting(false);
        setHitlPrompt(null);
        setStages((prev) => {
          const next = { ...prev };
          for (const stage of STAGES) {
            if (next[stage].status === "active" || stage === "finalize") {
              next[stage] = {
                ...next[stage],
                status: "completed",
                completedAt: Date.now(),
                durationMs: next[stage].startedAt
                  ? Date.now() - (next[stage].startedAt ?? Date.now())
                  : next[stage].durationMs,
                lastEventAt: Date.now(),
                lastSignal: qualityReadyActivity ? "research_quality_ready" : "done",
                message: qualityReadyActivity
                  ? "Research quality-first bounded run complete"
                  : "완료 · done event 수신",
              };
            }
          }
          return next;
        });
        if (qualityReadyActivity) {
          setResearchActivity((prev) => {
            const withoutDuplicate = prev.filter((item) => item.id !== qualityReadyActivity.id);
            return [qualityReadyActivity, ...withoutDuplicate].slice(0, 8);
          });
          markRunDone(runId);
          return;
        }
        if (event.aborted) {
          deleteRun(runId);
          setTimeout(() => {
            if (mounted) navigate("/");
          }, 300);
          return;
        }
        markRunDone(runId);
        setTimeout(() => {
          if (mounted) navigate(`/browser/${runId}/report`);
        }, 600);
        return;
      }
    };

    onBackendEvent(handleEvent, runId).then(async (unlisten) => {
      if (!mounted) {
        unlisten();
        return;
      }
      unlistenRef.current = unlisten;

      // Replay any events the active pipeline already emitted before this
      // listener was attached (e.g. user navigated to another page and came
      // back via the sidebar). Without replay the stage list stays at 0/8
      // even though Python is mid-run.
      let replayedEventCount = 0;
      try {
        const history = await getBufferedEvents(runId);
        replayedEventCount = history.length;
        for (const e of history) handleEvent(e);
      } catch {
        /* non-fatal */
      }

      // Listener + replay done — now safe to start the pipeline if this
      // mount owns the run kick-off (pending flag is set by IdeaSubmit).
      if (!runId) return;
      try {
        const pendingDecision = getPendingRunAutostartDecision(runId);
        const topic = localStorage.getItem(`run:${runId}:topic`) || "";
        if (pendingDecision.pending) {
          clearPendingRun(runId);
          if (!pendingDecision.canStart) {
            const message =
              pendingDecision.reason === "stale"
                ? "이전 세션의 미완료 실행은 오래되어 자동 시작하지 않았습니다. 다시 시작을 눌러주세요."
                : "이전 세션의 미완료 실행은 안전을 위해 자동 시작하지 않았습니다. 다시 시작을 눌러주세요.";
            failRun(message);
            return;
          }
          await startRunFromTopic(topic);
          return;
        }

        const report = localStorage.getItem(`run:${runId}:report`);
        const reportPath = localStorage.getItem(`run:${runId}:report_path`);
        const isRunningEntry = listRuns().some(
          (entry) => entry.runId === runId && entry.status === "running",
        );
        let hasRuntimeEvidence = replayedEventCount > 0;
        try {
          const status = await getPipelineRuntimeStatus();
          hasRuntimeEvidence = Boolean(status.running && status.app_run_id === runId);
          setRuntimeEvidence((prev) => ({
            ...(prev ?? {}),
            runId: status.app_run_id ?? prev?.runId,
            childPid: status.child_pid ?? null,
            appBinaryPath: status.app_binary_path ?? null,
            workspaceRoot: status.workspace_root,
            runtimeAgeMs: status.runtime_age_ms ?? null,
            lastEventElapsedMs: status.last_event_elapsed_ms ?? null,
          }));
        } catch {
          /* Older app runtimes do not expose this command; fall back to replay evidence. */
        }
        if (isRunningEntry && !hasRuntimeEvidence && report && reportPath) {
          markRunDone(runId);
          navigate(`/browser/${runId}/report`);
          return;
        }
        const shouldRecoverStaleRun =
          !hasRuntimeEvidence &&
          isRunningEntry &&
          topic.trim();

        if (shouldRecoverStaleRun) {
          failRun("이전 실행의 백엔드가 종료되었습니다. 자동 재시작하지 않았으니 다시 시작을 눌러주세요.");
        } else if (isRunningEntry && !hasRuntimeEvidence && !report) {
          failRun("이전 실행의 백엔드가 종료되어 실행을 계속할 수 없습니다. 다시 시작하세요.");
        }
      } catch (err) {
        const msg = err instanceof Error ? err.message : String(err);
        failRun(msg);
      }
    });

    return () => {
      mounted = false;
      if (unlistenRef.current) unlistenRef.current();
    };
  }, [failRun, runId, navigate, startRunFromTopic]);

  useEffect(() => {
    if (!runId || runError) return;

    let cancelled = false;
    const checkRuntime = async () => {
      if (cancelled || runErrorRef.current) return;
      const entry = listRuns().find((item) => item.runId === runId);
      if (entry?.status !== "running") return;

      let runtimeRunning = true;
      let lastEventElapsedMs: number | null = null;
      try {
        const status = await getPipelineRuntimeStatus();
        runtimeRunning = Boolean(status.running && status.app_run_id === runId);
        lastEventElapsedMs = status.last_event_elapsed_ms ?? null;
        setRuntimeEvidence((prev) => ({
          ...(prev ?? {}),
          runId: status.app_run_id ?? prev?.runId,
          childPid: status.child_pid ?? null,
          appBinaryPath: status.app_binary_path ?? null,
          workspaceRoot: status.workspace_root,
          runtimeAgeMs: status.runtime_age_ms ?? null,
          lastEventElapsedMs,
          stalled: Boolean(status.running && lastEventElapsedMs !== null && lastEventElapsedMs > 30000),
        }));
      } catch {
        return;
      }
      if (runtimeRunning && lastEventElapsedMs !== null && lastEventElapsedMs > 30000) {
        const seconds = Math.round(lastEventElapsedMs / 1000);
        const message =
          lastEventElapsedMs > 120000
            ? `백엔드 이벤트가 2분 넘게 도착하지 않았습니다. 실행이 멈춘 상태일 수 있으니 필요하면 다시 시작을 눌러주세요. (${seconds}초)`
            : `백엔드 이벤트가 ${seconds}초 동안 도착하지 않았습니다. 실행이 멈췄는지 확인 중입니다.`;
        setRunWarnings((prev) => [message, ...prev.filter((item) => item !== message)].slice(0, 3));
        return;
      }
      if (runtimeRunning || cancelled || runErrorRef.current) return;

      const report = localStorage.getItem(`run:${runId}:report`);
      const reportPath = localStorage.getItem(`run:${runId}:report_path`);
      if (report && reportPath) {
        markRunDone(runId);
        navigate(`/browser/${runId}/report`);
        return;
      }

      const message = "백엔드 프로세스가 종료되어 실행을 계속할 수 없습니다. 다시 시작하세요.";
      failRun(message);
      setStages((prev) => {
        const next = { ...prev };
        const active = STAGES.find((stage) => next[stage].status === "active");
        if (active) {
          next[active] = {
            ...next[active],
            status: "error",
            completedAt: Date.now(),
            message,
          };
        }
        return next;
      });
    };

    const timer = window.setInterval(() => {
      void checkRuntime();
    }, 4000);

    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [failRun, navigate, runError, runId]);

  const completedCount = STAGES.filter((s) => stages[s].status === "completed").length;
  const activeStage = STAGES.find((s) => stages[s].status === "active");
  const activeStageState = activeStage ? stages[activeStage] : undefined;
  const latestStage = activeStage
    ?? [...STAGES].reverse().find((s) => stages[s].lastEventAt || stages[s].status === "completed")
    ?? "intake";
  const latestStageState = stages[latestStage];
  const liveSignalAge = signalAge(now, latestStageState.lastEventAt);
  const liveStatusLabel = runError
    ? "실행 중단"
    : activeStage
    ? "실시간 진행 중"
    : completedCount === STAGES.length
    ? "완료"
    : "첫 백엔드 신호 대기";
  const liveDetail = runError
    ? runError
    : activeStageState?.message || latestStageState.message || "백엔드 이벤트를 기다리는 중입니다.";
  const totalProgress = (completedCount / STAGES.length) * 100;
  const selectedPersonaRows = browserPersonaRows(councilPersonas);
  const runtimeRunId = runtimeEvidence?.runId;
  const runtimeHeartbeatStage = runtimeEvidence?.heartbeatStage;
  const hasVisibleBackendHeartbeat = hasReceivedHeartbeat;
  const desktopRuntimeStatus = runtimeEvidence ? "Observed" : "Not observed yet";
  const backendSignalStatus = deriveBackendSignalStatus({
    runId,
    runtimeRunId,
    runtimeHeartbeatStage,
    hasVisibleBackendHeartbeat,
  });
  const sourceAccessEvidenceStatus =
    discoveredSources.size > 0
      ? `${discoveredSources.size} source event${discoveredSources.size === 1 ? "" : "s"}`
      : "Not observed yet";
  const importedKnowledgeRefCount = researchContract.importedKnowledgeRefs.length;
  const currentSessionEvidenceCount = discoveredSources.size;
  const researchSessionLabel = researchContract.researchSessionId
    ? researchContract.researchSessionId.slice(-10)
    : "pending";
  const memoryPolicyLabel = researchContract.memoryPolicy || "pending";
  const importedRefsLabel = importedKnowledgeRefCount > 0
    ? `${importedKnowledgeRefCount} explicit imported ref${importedKnowledgeRefCount === 1 ? "" : "s"}`
    : "0 explicit imports";

  async function submitInterviewAnswer(answer: string, selected?: string, isOther = false) {
    if (!interviewPrompt || interviewSubmitting) return;
    const trimmed = answer.trim();
    if (!trimmed) {
      setInterviewError("답변을 입력하거나 선택하세요.");
      return;
    }
    setInterviewSubmitting(true);
    setInterviewError(null);
    try {
      await sendAction({
        action: "interview_answer",
        q_id: interviewPrompt.id,
        answer: trimmed,
        choice: selected ?? trimmed,
        selected: selected ?? trimmed,
        other_text: isOther ? trimmed : undefined,
      });
      setInterviewAnswer("");
      setInterviewSelections([]);
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      if (isBackendGoneError(message)) {
        failRun(message);
      }
      setInterviewError(message);
      setInterviewSubmitting(false);
    }
  }

  async function submitSelectedOptions() {
    if (!interviewPrompt || interviewSelections.length === 0) {
      setInterviewError("선택지를 하나 이상 골라주세요.");
      return;
    }
    await submitInterviewAnswer(interviewSelections.join(", "), interviewSelections.join(","), false);
  }

  async function submitHitlDecision(status: "approved" | "changes_requested") {
    if (!hitlPrompt || hitlSubmitting) return;
    setHitlSubmitting(true);
    setHitlError(null);
    const annotations =
      hitlPrompt.gate === "plan" ? planReviewAnnotations(planReviewEdits) : [];
    try {
      await sendAction({
        action: "hitl_decision",
        gate: hitlPrompt.gate,
        status,
        annotations,
        comment:
          annotations.length > 0
            ? `inline plan review edits: ${annotations.length}`
            : undefined,
      });
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      if (isBackendGoneError(message)) {
        failRun(message);
      }
      setHitlError(message);
      setHitlSubmitting(false);
    }
  }

  useEffect(() => {
    const autogoals = Boolean(import.meta.env.VITE_MUCHANIPO_AUTOSTART_TOPIC);
    if (!autogoals || !interviewPrompt || interviewSubmitting || !runId) return;
    const currentRunTopic = (topic || localStorage.getItem(`run:${runId}:topic`) || "").trim();
    if (!currentRunTopic) return;
    const key = `muchanipo:auto-answer:${runId}:${interviewPrompt.id}`;
    if (sessionStorage.getItem(key)) return;
    sessionStorage.setItem(key, "1");
    const answer =
      interviewPrompt.id === "Q1_research_question"
        ? currentRunTopic
        : `${currentRunTopic} 기준으로 핵심 정의와 범위, 현장 검증, 가격/채택, 이해관계자와 규제 맥락, 한계와 검증 가능한 근거를 균형 있게 종합해줘.`;
    void submitInterviewAnswer(answer, "OTHER", true);
  }, [interviewPrompt, interviewSubmitting, runId, topic]);

  useEffect(() => {
    const autogoals = Boolean(import.meta.env.VITE_MUCHANIPO_AUTOSTART_TOPIC);
    if (!autogoals || !hitlPrompt || hitlSubmitting) return;
    const key = `muchanipo:auto-approve:${runId}:${hitlPrompt.gate}`;
    if (sessionStorage.getItem(key)) return;
    sessionStorage.setItem(key, "1");
    void submitHitlDecision("approved");
  }, [hitlPrompt, hitlSubmitting, runId]);

  async function abortRun() {
    if (aborting) return;
    setAborting(true);
    try {
      await sendAction({ action: "abort" });
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      failRun(message);
    } finally {
      setAborting(false);
    }
  }

  async function restartRun() {
    if (!runId) return;
    const runTopic = topic || localStorage.getItem(`run:${runId}:topic`) || "";
    await startRunFromTopic(runTopic, { clearArtifacts: true });
  }

  return (
    <div className="min-h-screen px-6 py-10">
      <div className="mx-auto max-w-6xl">
        {/* Header */}
        <div className="fade-in mb-8 border-b border-white/10 pb-6">
          <div className="flex items-start justify-between gap-4">
            <div className="min-w-0">
              <p className="atlas-label mb-2">Browser</p>
              <h1 className="display-serif truncate text-[32px] font-semibold leading-tight text-white md:text-[44px]">
                {topic || "(주제 없음)"}
              </h1>
              <p className="mt-1 text-xs text-tertiary">{runId}</p>
              {studioProvenance && (
                <div className="mt-3 flex flex-wrap items-center gap-2">
                  {studioProvenance.studioId && (
                    <span className="inline-flex items-center gap-1 rounded-full border border-amber-400/20 bg-amber-400/10 px-2 py-0.5 text-[10px] text-amber-100">
                      <span className="h-1 w-1 rounded-full bg-amber-300" />
                      Studio {studioProvenance.studioId.slice(-6)}
                    </span>
                  )}
                  {studioProvenance.studioModel && (
                    <span className="inline-flex items-center gap-1 rounded-full border border-sky-400/20 bg-sky-400/10 px-2 py-0.5 text-[10px] text-sky-100">
                      <span className="h-1 w-1 rounded-full bg-sky-300" />
                      {studioProvenance.studioModel}
                    </span>
                  )}
                </div>
              )}
            </div>
            <button
              type="button"
              onClick={abortRun}
              disabled={aborting}
              className="shrink-0 rounded-full border border-red-400/20 px-3 py-1.5 text-xs text-red-200 transition hover:bg-red-500/10 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {aborting ? "중단 중" : "중단"}
            </button>
          </div>
        </div>

        {/* Progress meter */}
        <div className="fade-in mb-6 flex items-center gap-3">
          <div className="h-1 flex-1 overflow-hidden rounded-full bg-white/10">
            <div
              className="h-full rounded-full bg-white transition-all duration-500"
              style={{ width: `${totalProgress}%` }}
            />
          </div>
          <span className="font-mono text-xs text-secondary">
            {completedCount}/{STAGES.length}
          </span>
        </div>

        <div className={`fade-in mb-6 overflow-hidden rounded-lg border px-4 py-4 shadow-[var(--shadow-paper)] ${
          runError
            ? "border-red-500/20 bg-red-500/5"
            : activeStage
            ? "border-emerald-400/20 bg-emerald-400/5"
            : "border-white/5 bg-white/[0.02]"
        }`}>
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div className="min-w-0">
              <div className="mb-2 flex flex-wrap items-center gap-2">
                {!runError && activeStage && (
                  <span className="relative flex h-2.5 w-2.5">
                    <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-300 opacity-60" />
                    <span className="relative inline-flex h-2.5 w-2.5 rounded-full bg-emerald-300" />
                  </span>
                )}
                <span className="text-[11px] font-semibold uppercase tracking-wider text-secondary">
                  Run
                </span>
                <span className={`min-w-[120px] max-w-[160px] truncate rounded-full border px-2 py-0.5 text-center font-mono text-[10px] uppercase tracking-[0.08em] ${
                  runError
                    ? "border-red-400/20 bg-red-400/10 text-red-200"
                    : activeStage
                    ? "border-emerald-400/20 bg-emerald-400/10 text-emerald-100"
                    : "border-white/10 bg-black/20 text-tertiary"
                }`}>
                  {liveStatusLabel}
                </span>
              </div>
              <p className="break-words text-sm leading-relaxed text-white">
                {STAGE_LABEL[latestStage]} · {liveDetail}
              </p>
              <div className="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-[11px] text-tertiary">
                {latestStageState.lastSignal && (
                  <span className="font-mono">signal {latestStageState.lastSignal}</span>
                )}
                {liveSignalAge && <span>last signal {liveSignalAge} 전</span>}
                {runtimeEvidence?.lastEventElapsedMs !== undefined && runtimeEvidence.lastEventElapsedMs !== null && (
                  <span>backend event age {formatElapsed(runtimeEvidence.lastEventElapsedMs)}</span>
                )}
                {runtimeEvidence?.runtimeAgeMs !== undefined && runtimeEvidence.runtimeAgeMs !== null && (
                  <span>runtime age {formatElapsed(runtimeEvidence.runtimeAgeMs)}</span>
                )}
              </div>
            </div>
            <div className="shrink-0 rounded-md border border-white/10 bg-black/20 px-3 py-2 text-right">
              <p className="font-mono text-lg text-white">{completedCount}/{STAGES.length}</p>
              <p className="text-[10px] uppercase tracking-wider text-tertiary">steps done</p>
            </div>
          </div>
        </div>

        <div className="fade-in mb-6 rounded-lg border border-white/5 bg-white/[0.02] px-4 py-3 shadow-[var(--shadow-paper)]">
          <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
            <div>
              <p className="text-[11px] font-semibold uppercase tracking-wider text-tertiary">
                Run health
              </p>
              <h2 className="mt-1 text-sm font-medium text-white">Backend heartbeat and source visibility</h2>
            </div>
            <span className="rounded-full border border-white/10 bg-black/20 px-2.5 py-1 font-mono text-[10px] text-tertiary">
              current run
            </span>
          </div>
          <div className="grid gap-2 md:grid-cols-3">
            <div className="rounded-lg border border-white/10 bg-black/20 px-3 py-2">
              <p className="text-[10px] font-semibold uppercase tracking-wider text-tertiary">Runtime</p>
              <p className="mt-1 text-xs text-white">{desktopRuntimeStatus}</p>
            </div>
            <div className="rounded-lg border border-white/10 bg-black/20 px-3 py-2">
              <p className="text-[10px] font-semibold uppercase tracking-wider text-tertiary">Backend signal</p>
              <p className="mt-1 text-xs text-white">{backendSignalStatus}</p>
            </div>
            <div className="rounded-lg border border-white/10 bg-black/20 px-3 py-2">
              <p className="text-[10px] font-semibold uppercase tracking-wider text-tertiary">Source access</p>
              <p className="mt-1 text-xs text-white">{sourceAccessEvidenceStatus}</p>
            </div>
          </div>
        </div>

        <div className="fade-in mb-6 rounded-lg border border-white/5 bg-white/[0.02] px-4 py-3 shadow-[var(--shadow-paper)]">
          <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
            <div>
              <p className="text-[11px] font-semibold uppercase tracking-wider text-tertiary">
                Research contract
              </p>
              <h2 className="mt-1 text-sm font-medium text-white">Current-session evidence / imported refs boundary</h2>
            </div>
            <span className="rounded-full border border-emerald-400/20 bg-emerald-400/10 px-2.5 py-1 font-mono text-[10px] text-emerald-100">
              no implicit memory
            </span>
          </div>
          <div className="grid gap-2 md:grid-cols-4">
            <div className="rounded-lg border border-white/10 bg-black/20 px-3 py-2">
              <p className="text-[10px] font-semibold uppercase tracking-wider text-tertiary">Session</p>
              <p className="mt-1 font-mono text-xs text-white">{researchSessionLabel}</p>
            </div>
            <div className="rounded-lg border border-white/10 bg-black/20 px-3 py-2">
              <p className="text-[10px] font-semibold uppercase tracking-wider text-tertiary">Memory policy</p>
              <p className="mt-1 break-words font-mono text-xs text-white">{memoryPolicyLabel}</p>
            </div>
            <div className="rounded-lg border border-white/10 bg-black/20 px-3 py-2">
              <p className="text-[10px] font-semibold uppercase tracking-wider text-tertiary">Current session evidence</p>
              <p className="mt-1 text-xs text-white">{currentSessionEvidenceCount} source event{currentSessionEvidenceCount === 1 ? "" : "s"}</p>
            </div>
            <div className="rounded-lg border border-white/10 bg-black/20 px-3 py-2">
              <p className="text-[10px] font-semibold uppercase tracking-wider text-tertiary">Imported wiki refs</p>
              <p className="mt-1 text-xs text-white">{importedRefsLabel}</p>
            </div>
          </div>
          {researchContract.importedKnowledgeRefs.length > 0 && (
            <div className="mt-3 flex flex-wrap gap-2">
              {researchContract.importedKnowledgeRefs.map((ref) => (
                <span
                  key={ref}
                  className="max-w-full truncate rounded-md border border-sky-300/15 bg-sky-300/10 px-2.5 py-1 font-mono text-[10px] text-sky-100"
                  title={ref}
                >
                  {ref}
                </span>
              ))}
            </div>
          )}
        </div>

        {runtimeEvidence && (
          <div className={`fade-in mb-6 rounded-lg border px-4 py-3 ${
            runtimeEvidence.stalled
              ? "border-amber-400/20 bg-amber-400/5"
              : "border-white/5 bg-white/[0.02]"
          }`}>
            <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-tertiary">
              <span className="font-semibold uppercase tracking-wider text-secondary">Runtime</span>
              {runtimeEvidence.childPid !== undefined && runtimeEvidence.childPid !== null && (
                <span className="font-mono">bridge pid {runtimeEvidence.childPid}</span>
              )}
              {runtimeEvidence.pythonPid && (
                <span className="font-mono">python pid {runtimeEvidence.pythonPid}</span>
              )}
              {runtimeEvidence.heartbeatStage && (
                <span>{runtimeEvidence.heartbeatStage}{runtimeEvidence.heartbeatDetail ? ` · ${runtimeEvidence.heartbeatDetail}` : ""}</span>
              )}
              {runtimeEvidence.lastEventElapsedMs !== undefined && runtimeEvidence.lastEventElapsedMs !== null && (
                <span>last event {formatElapsed(runtimeEvidence.lastEventElapsedMs)} ago</span>
              )}
              {runtimeEvidence.runtimeAgeMs !== undefined && runtimeEvidence.runtimeAgeMs !== null && (
                <span>age {formatElapsed(runtimeEvidence.runtimeAgeMs)}</span>
              )}
            </div>
            {(runtimeEvidence.pythonExecutable || runtimeEvidence.appBinaryPath) && (
              <div className="mt-2 space-y-1">
                {runtimeEvidence.pythonExecutable && (
                  <p className="truncate font-mono text-[10px] text-tertiary">
                    py {runtimeEvidence.pythonExecutable}
                  </p>
                )}
                {runtimeEvidence.appBinaryPath && (
                  <p className="truncate font-mono text-[10px] text-tertiary">
                    app {runtimeEvidence.appBinaryPath}
                  </p>
                )}
              </div>
            )}
          </div>
        )}

        <div className="fade-in mb-6 rounded-lg border border-white/5 bg-white/[0.02] p-4 shadow-[var(--shadow-paper)]">
          <div className="mb-3 flex items-center justify-between gap-3">
            <div className="min-w-0">
              <p className="text-[11px] font-semibold uppercase tracking-wider text-tertiary">
                Selected personas
              </p>
              <h2 className="mt-1 text-sm font-medium text-white">Persona provenance</h2>
            </div>
            <span className="min-w-[86px] rounded-full border border-white/10 bg-black/20 px-2 py-1 text-center font-mono text-[10px] uppercase tracking-[0.08em] text-tertiary">
              Provenance
            </span>
          </div>
          <div className="grid gap-2 md:grid-cols-2">
            {selectedPersonaRows.map((persona) => (
              <div
                key={persona.id}
                className="rounded-lg border border-white/10 bg-black/20 px-3 py-3"
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <p className="truncate text-sm font-medium text-white">{persona.name}</p>
                    <p className="mt-1 text-xs leading-5 text-secondary">{persona.role}</p>
                  </div>
                  <span className="shrink-0 rounded-md border border-white/10 px-2 py-1 text-[10px] text-tertiary">
                    Source
                  </span>
                </div>
                <p className="mt-2 break-words font-mono text-[10px] leading-5 text-tertiary">
                  {persona.provenance}
                </p>
                <p className="mt-1 text-[11px] leading-5 text-tertiary">{persona.note}</p>
              </div>
            ))}
          </div>
        </div>

        <div className="fade-in mb-6">
          <PersonaPoolCard pool={personaPool} />
        </div>

        {/* Run error banner */}
        {runError && (
          <div className="fade-in mb-6 flex items-start justify-between gap-4 rounded-lg border border-red-500/20 bg-red-500/5 px-4 py-3">
            <p className="break-all text-sm text-red-300">{runError}</p>
            <div className="flex shrink-0 items-center gap-2">
              <button
                type="button"
                onClick={restartRun}
                className="rounded-full bg-white px-3 py-1 text-xs font-medium text-black transition hover:opacity-90"
              >
                다시 시작
              </button>
              <button
                type="button"
                onClick={() => navigate("/")}
                className="rounded-full border border-white/10 px-3 py-1 text-xs text-secondary transition hover:bg-white/5 hover:text-white"
              >
                처음으로
              </button>
            </div>
          </div>
        )}

        {runWarnings.length > 0 && !runError && (
          <div className="fade-in mb-6 rounded-lg border border-amber-400/20 bg-amber-400/5 px-4 py-3">
            <p className="mb-1 text-xs font-medium uppercase tracking-wider text-amber-200">
              실행 경고
            </p>
            {runWarnings.map((warning) => (
              <p key={warning} className="break-all text-sm text-amber-100/80">
                {warning}
              </p>
            ))}
          </div>
        )}

        {/* Inline HITL approval card */}
        {hitlPrompt && (
          <div className="fade-in mb-6 overflow-hidden rounded-lg border border-amber-400/20 bg-amber-400/5 px-4 py-4">
            <div className="mb-3 flex items-start justify-between gap-4">
              <div className="min-w-0">
                <p className="text-[11px] font-semibold uppercase tracking-wider text-amber-200">
                  HITL Gate · {hitlPrompt.gate}
                </p>
                <h2 className="mt-1 text-sm font-medium leading-relaxed text-white">
                  {hitlPrompt.title}
                </h2>
                <p className="mt-1 text-xs leading-relaxed text-secondary">
                  {hitlPrompt.prompt}
                </p>
              </div>
              <span className="shrink-0 whitespace-nowrap rounded-full border border-amber-400/20 bg-amber-400/10 px-2.5 py-1 text-[10px] text-amber-200">
                승인 대기
              </span>
            </div>

            {hitlPrompt.gate === "evidence" && (
              <div className="mb-3">
                <EvidenceIndexPanel
                  evidenceRefs={hitlEvidenceRefs(hitlPrompt)}
                  compact
                  title="검토할 근거"
                />
              </div>
            )}

            {hitlPrompt.preview && hitlPrompt.gate !== "evidence" && (
              <pre className="mb-3 max-h-64 max-w-full overflow-auto whitespace-pre-wrap break-words rounded-lg border border-white/10 bg-black/20 px-3 py-2 text-xs leading-relaxed text-secondary">
                {hitlPrompt.preview}
              </pre>
            )}

            {hitlPrompt.preview && hitlPrompt.gate === "evidence" && (
              <details className="mb-3 rounded-lg border border-white/10 bg-black/15 px-3 py-2">
                <summary className="cursor-pointer text-xs text-secondary transition hover:text-white">
                  원본 evidence payload 보기
                </summary>
                <pre className="mt-2 max-h-44 max-w-full overflow-auto whitespace-pre-wrap break-words text-[11px] leading-relaxed text-tertiary">
                  {hitlPrompt.preview}
                </pre>
              </details>
            )}

            {hitlPrompt.gate === "plan" && planReviewEdits && (
              <PlannotatorPlanEditor
                state={planReviewEdits}
                onChange={setPlanReviewEdits}
                editCount={planReviewEditCount}
              />
            )}

            <div className="grid grid-cols-1 gap-2 sm:ml-auto sm:inline-grid sm:max-w-full sm:grid-cols-[max-content_max-content]">
              <button
                type="button"
                disabled={hitlSubmitting}
                onClick={() => submitHitlDecision("changes_requested")}
                className="min-h-10 min-w-0 max-w-full whitespace-nowrap rounded-full border border-white/10 px-4 py-2 text-center text-sm text-secondary transition hover:bg-white/5 hover:text-white disabled:cursor-not-allowed disabled:opacity-50"
              >
                수정 필요
              </button>
              <button
                type="button"
                disabled={hitlSubmitting}
                onClick={() => submitHitlDecision("approved")}
                className="min-h-10 min-w-0 max-w-full whitespace-nowrap rounded-full bg-white px-4 py-2 text-center text-sm font-medium text-black transition hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {hitlSubmitting
                  ? "승인 중"
                  : planReviewEditCount > 0
                  ? "수정 반영 후 계속"
                  : "승인하고 계속"}
              </button>
            </div>

            {hitlError && <p className="mt-2 break-all text-xs text-red-300">{hitlError}</p>}
          </div>
        )}

        {interviewArtifacts && (
          <div className="fade-in mb-6 overflow-hidden rounded-lg border border-white/10 bg-white/[0.03] px-4 py-4">
            <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
              <div className="min-w-0">
                <p className="text-[11px] font-semibold uppercase tracking-wider text-tertiary">
                  Deep Interview Artifacts
                </p>
                <h2 className="mt-1 break-words text-sm font-medium text-white">
                  {interviewArtifacts.workflow} · {interviewArtifacts.documentCount} documents
                </h2>
              </div>
              {interviewArtifacts.commit && (
                <span className="max-w-full truncate rounded-full border border-white/10 bg-black/20 px-2.5 py-1 font-mono text-[10px] text-secondary">
                  {interviewArtifacts.commit.slice(0, 12)}
                </span>
              )}
            </div>
            {interviewArtifacts.evidenceMarkers.length > 0 && (
              <div className="mb-3 flex flex-wrap gap-1.5">
                {interviewArtifacts.evidenceMarkers.slice(0, 8).map((marker) => (
                  <span
                    key={marker}
                    className="rounded-full border border-white/10 bg-black/20 px-2 py-0.5 text-[10px] text-tertiary"
                  >
                    {marker}
                  </span>
                ))}
              </div>
            )}
            <div className="grid gap-2 md:grid-cols-2">
              {interviewArtifacts.manifest.map((doc) => (
                <div key={doc.path} className="rounded-lg border border-white/10 bg-black/20 px-3 py-2">
                  <div className="mb-1 flex items-center justify-between gap-2">
                    <span className="min-w-0 truncate font-mono text-[11px] text-secondary">
                      {doc.path}
                    </span>
                    <span className="shrink-0 text-[10px] text-tertiary">{doc.chars} chars</span>
                  </div>
                  <p className="truncate text-xs font-medium text-white">{doc.title}</p>
                  {doc.preview && (
                    <p className="mt-1 max-h-12 overflow-hidden break-words text-[11px] leading-relaxed text-tertiary">
                      {doc.preview}
                    </p>
                  )}
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Inline HITL/interview answer card */}
        {interviewPrompt && (
          <div className="fade-in mb-6 overflow-hidden rounded-lg border border-white/10 bg-white/[0.03] px-4 py-4">
            <div className="mb-3 flex items-start justify-between gap-4">
              <div className="min-w-0">
                <p className="text-[11px] font-semibold uppercase tracking-wider text-tertiary">
                  {interviewPrompt.header}
                  {interviewPrompt.index && interviewPrompt.total
                    ? ` · ${interviewPrompt.index}/${interviewPrompt.total}`
                    : ""}
                </p>
                <h2 className="mt-1 whitespace-pre-wrap text-sm font-medium leading-relaxed text-white">
                  {interviewPrompt.text}
                </h2>
                {interviewPrompt.counselling && (
                  <div className="mt-3 rounded-lg border border-sky-400/15 bg-sky-400/5 px-3 py-2 text-[11px] leading-relaxed text-sky-100">
                    <div className="mb-1 flex flex-wrap items-center gap-2 text-[10px] uppercase tracking-wider text-sky-200/80">
                      <span className="font-semibold">Deep Interview</span>
                      {interviewPrompt.counselling.mode && <span>{interviewPrompt.counselling.mode}</span>}
                      {interviewPrompt.counselling.provider && <span>{interviewPrompt.counselling.provider}</span>}
                    </div>
                    {interviewPrompt.counselling.rationale && (
                      <p className="text-sky-100/90">{interviewPrompt.counselling.rationale}</p>
                    )}
                    {interviewPrompt.counselling.referenceInsights.length > 0 && (
                      <p className="mt-1 text-sky-100/75">
                        참고자료 단서: {interviewPrompt.counselling.referenceInsights.slice(0, 3).join(" · ")}
                      </p>
                    )}
                    {interviewPrompt.counselling.assumptionsToTest.length > 0 && (
                      <p className="mt-1 text-sky-100/75">
                        검증할 가정: {interviewPrompt.counselling.assumptionsToTest.slice(0, 2).join(" · ")}
                      </p>
                    )}
                    {interviewPrompt.counselling.prdImpact && (
                      <p className="mt-1 text-sky-100/60">해석 반영: {interviewPrompt.counselling.prdImpact}</p>
                    )}
                  </div>
                )}
              </div>
              <span className="shrink-0 whitespace-nowrap rounded-full border border-amber-400/20 bg-amber-400/10 px-2.5 py-1 text-[10px] text-amber-200">
                {interviewSubmitting ? "다음 질문 대기" : "대기 중"}
              </span>
            </div>

            {interviewClarity && (
              <div className="mb-3 rounded-lg border border-white/5 bg-black/20 px-3 py-2">
                <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-tertiary">
                  <span className="font-semibold uppercase tracking-wider text-secondary">
                    Deep Interview
                  </span>
                  {interviewClarity.mode && <span>{interviewClarity.mode}</span>}
                  {interviewClarity.researchType && <span>{interviewClarity.researchType}</span>}
                  {interviewClarity.focusLabel && <span>{interviewClarity.focusLabel}</span>}
                  {interviewClarity.coverageScore !== undefined && (
                    <span>coverage {Math.round(interviewClarity.coverageScore * 100)}%</span>
                  )}
                  {interviewClarity.ambiguityScore !== undefined && (
                    <span>ambiguity {Math.round(interviewClarity.ambiguityScore * 100)}%</span>
                  )}
                </div>
                {interviewClarity.focusQuestion && (
                  <p className="mt-1 break-words text-[11px] leading-relaxed text-secondary">
                    {interviewClarity.focusQuestion}
                  </p>
                )}
                {interviewClarity.missingDimensions.length > 0 && (
                  <p className="mt-1 truncate text-[11px] text-tertiary">
                    남은 차원: {interviewClarity.missingDimensions.join(" · ")}
                  </p>
                )}
              </div>
            )}

            {interviewPrompt.preview && (
              <pre className="mb-3 max-h-56 max-w-full overflow-auto whitespace-pre-wrap break-words rounded-lg border border-white/10 bg-black/20 px-3 py-2 text-xs leading-relaxed text-secondary">
                {interviewPrompt.preview}
              </pre>
            )}

            {activeDeepInterviewPrompt && (
              <div className="mb-3 grid gap-2 md:grid-cols-2">
                <div className="rounded-xl border border-white/10 bg-black/20 p-3">
                  <p className="text-[10px] font-semibold uppercase tracking-wider text-tertiary">
                    Unknowns board
                  </p>
                  <div className="mt-2 flex flex-wrap gap-1.5">
                    {unknownDimensions.length > 0 ? (
                      unknownDimensions.map((dimension) => (
                        <span
                          key={dimension}
                          className="rounded-full border border-amber-400/20 bg-amber-400/10 px-2 py-0.5 text-[10px] text-amber-100"
                        >
                          {dimension}
                        </span>
                      ))
                    ) : (
                      <span className="text-[11px] text-secondary">No unresolved dimensions reported.</span>
                    )}
                  </div>
                </div>

                <div className="rounded-xl border border-white/10 bg-black/20 p-3">
                  <p className="text-[10px] font-semibold uppercase tracking-wider text-tertiary">
                    Ontology map seed
                  </p>
                  <div className="mt-2 flex flex-wrap gap-1.5">
                    {(ontologyNodes.length > 0 ? ontologyNodes : ["entity", "relation", "boundary"]).map((node) => (
                      <span
                        key={node}
                        className="rounded-full border border-sky-400/20 bg-sky-400/10 px-2 py-0.5 text-[10px] text-sky-100"
                      >
                        {node}
                      </span>
                    ))}
                  </div>
                  <p className="mt-2 text-[11px] leading-relaxed text-tertiary">
                    This turn should stabilize entities, relations, triggers, constraints, or evidence boundaries.
                  </p>
                </div>

                <div className="rounded-xl border border-white/10 bg-black/20 p-3">
                  <p className="text-[10px] font-semibold uppercase tracking-wider text-tertiary">
                    Answer assimilation
                  </p>
                  <p className="mt-2 text-[11px] leading-relaxed text-secondary">
                    {interviewPrompt.counselling?.prdImpact ||
                      "Your answer will update the working interpretation before research, evidence, and council stages continue."}
                  </p>
                </div>

                <div className="rounded-xl border border-white/10 bg-black/20 p-3">
                  <p className="text-[10px] font-semibold uppercase tracking-wider text-tertiary">
                    Capability graph
                  </p>
                  <div className="mt-2 grid grid-cols-2 gap-1.5 text-[10px] text-secondary">
                    <span className="rounded-md border border-white/10 bg-white/[0.03] px-2 py-1">Ambiguity gate</span>
                    <span className="rounded-md border border-white/10 bg-white/[0.03] px-2 py-1">Source grounding</span>
                    <span className="rounded-md border border-white/10 bg-white/[0.03] px-2 py-1">Council handoff</span>
                    <span className="rounded-md border border-white/10 bg-white/[0.03] px-2 py-1">Report contract</span>
                  </div>
                </div>
              </div>
            )}

            {interviewPrompt.allowOther && (
              <div className="mb-3 rounded-xl border border-white/10 bg-black/20 p-3">
                <label className="mb-2 block text-[11px] font-semibold uppercase tracking-wider text-tertiary">
                  Socratic answer
                </label>
                <textarea
                  value={interviewAnswer}
                  disabled={interviewSubmitting}
                  onChange={(event) => setInterviewAnswer(event.target.value)}
                  onKeyDown={(event) => {
                    if ((event.metaKey || event.ctrlKey) && event.key === "Enter") {
                      void submitInterviewAnswer(interviewAnswer, "OTHER", true);
                    }
                  }}
                  placeholder="자연어로 답변하세요. 보존하려는 개체, 행위자, 트리거, 제외 의미, 제약, 또는 근거 경계를 적어주세요."
                  rows={4}
                  className="min-h-24 w-full resize-y rounded-lg border border-white/10 bg-black/30 px-3 py-2 text-sm leading-relaxed text-white placeholder-tertiary outline-none transition focus:border-white/30 focus:bg-black/40"
                />
                <div className="mt-2 flex flex-wrap items-center justify-between gap-2">
                  <p className="text-[11px] text-tertiary">⌘/Ctrl + Enter로 전송 · 답변이 정리되어 리서치가 계속됩니다</p>
                  <button
                    type="button"
                    disabled={interviewSubmitting || !interviewAnswer.trim()}
                    onClick={() => submitInterviewAnswer(interviewAnswer, "OTHER", true)}
                    className="rounded-full bg-white px-4 py-2 text-sm font-medium text-black transition hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    {interviewSubmitting ? "전송 중" : "답변 전송"}
                  </button>
                </div>
              </div>
            )}

            {(() => {
              return !activeDeepInterviewPrompt && interviewPrompt.options.length > 0;
            })() && (
              <div className="mb-3 rounded-xl border border-white/5 bg-white/[0.02] p-3">
                <p className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-tertiary">
                  추천 답변 초안
                </p>
                <div className="grid gap-2 sm:grid-cols-2">
                  {interviewPrompt.options.map((option) => (
                    <button
                      key={`${option.key}:${option.value}`}
                      type="button"
                      disabled={interviewSubmitting}
                      onClick={() => {
                        if (interviewPrompt.multiSelect) {
                          setInterviewSelections((prev) =>
                            prev.includes(option.value)
                              ? prev.filter((item) => item !== option.value)
                              : [...prev, option.value],
                          );
                        } else {
                          setInterviewSelections([option.value]);
                          setInterviewAnswer(option.description ? `${option.label}\n${option.description}` : option.label || option.value);
                          setInterviewError(null);
                        }
                      }}
                      className={`rounded-lg border px-3 py-2 text-left text-xs transition disabled:cursor-not-allowed disabled:opacity-50 ${
                        interviewSelections.includes(option.value)
                          ? "border-white/30 bg-white/10 text-white"
                          : "border-white/10 bg-black/20 text-secondary hover:border-white/25 hover:bg-white/5 hover:text-white"
                      }`}
                    >
                      <span className="mr-2 font-mono text-white">{option.key}</span>
                      <span className="font-medium">{option.label}</span>
                      {option.description && (
                        <span className="mt-1 block text-[11px] leading-relaxed text-tertiary">
                          {option.description}
                        </span>
                      )}
                    </button>
                  ))}
                </div>
              </div>
            )}

            {interviewPrompt.multiSelect && (
              <div className="mb-3 flex justify-end">
                <button
                  type="button"
                  disabled={interviewSubmitting || interviewSelections.length === 0}
                  onClick={submitSelectedOptions}
                  className="rounded-full bg-white px-4 py-2 text-sm font-medium text-black transition hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  {interviewSubmitting ? "전송 중" : "선택 완료"}
                </button>
              </div>
            )}

            {interviewError && (
              <p className="mt-2 break-all text-xs text-red-300">{interviewError}</p>
            )}
          </div>
        )}

        {/* Source discovery panel — live accumulated evidence inventory */}
        {(discoveredSources.size > 0 || knowledgeGaps.length > 0) && (
          <div className="fade-in mb-6 overflow-hidden rounded-lg border border-white/5 bg-white/[0.02] shadow-[var(--shadow-paper)]">
            <SourceDiscoveryPanel
              sources={Array.from(discoveredSources.values()).sort(
                (a, b) => b.firstSeenAt - a.firstSeenAt,
              )}
              gaps={knowledgeGaps}
              compact
            />
          </div>
        )}

        {/* Stage list (vertical, minimalist) */}
        <ul className="space-y-px overflow-hidden rounded-lg border border-white/5 shadow-[var(--shadow-paper)]">
          {STAGES.map((stage) => {
            const state = stages[stage];
            const isActive = state.status === "active";
            const isCompleted = state.status === "completed";
            const isError = state.status === "error";
            const lastSignalAge = signalAge(now, state.lastEventAt);
            const proofTone = isActive
              ? "border-emerald-400/20 bg-emerald-400/10 text-emerald-100"
              : isCompleted
              ? "border-white/10 bg-black/20 text-tertiary"
              : isError
              ? "border-red-400/20 bg-red-400/10 text-red-200"
              : "border-white/5 bg-black/10 text-tertiary";

            return (
              <li
                key={stage}
                className={`flex items-center gap-3 px-4 py-3 transition ${
                  isActive ? "bg-white/5" : "bg-white/[0.02]"
                }`}
              >
                <div className="flex h-5 w-5 shrink-0 items-center justify-center">
                  {isCompleted ? (
                    <svg className="h-4 w-4 text-white" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.5}>
                      <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
                    </svg>
                  ) : isError ? (
                    <svg className="h-4 w-4 text-red-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.5}>
                      <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                    </svg>
                  ) : isActive ? (
                    <svg className="h-3.5 w-3.5 animate-spin text-white" viewBox="0 0 24 24" fill="none">
                      <circle cx="12" cy="12" r="10" stroke="currentColor" strokeOpacity="0.3" strokeWidth="3" />
                      <path d="M12 2a10 10 0 0110 10" stroke="currentColor" strokeWidth="3" strokeLinecap="round" />
                    </svg>
                  ) : (
                    <div className="h-1.5 w-1.5 rounded-full bg-white/20" />
                  )}
                </div>

                <div className="flex-1 min-w-0">
                  <div className="flex items-baseline justify-between gap-3">
                    <span className={`text-sm ${
                      isActive
                        ? "text-white"
                        : isCompleted
                        ? "text-secondary"
                        : isError
                        ? "text-red-300"
                        : "text-tertiary"
                    }`}>
                      {STAGE_LABEL[stage]}
                    </span>
                    <span className="shrink-0 font-mono text-[10px] text-tertiary">
                      {state.durationMs ? `${Math.round(state.durationMs / 1000)}s` : ""}
                    </span>
                  </div>
                  {stage === "council" && isActive && councilRound > 0 && (
                    <p className="mt-0.5 text-[11px] text-tertiary">
                      Round <span className="font-mono text-white">{councilRound}</span> / 10
                    </p>
                  )}
                  {(state.message || state.lastSignal) && (
                    <div className="mt-1 flex flex-wrap items-center gap-1.5">
                      <span className={`min-w-[72px] text-center rounded-full border px-2 py-0.5 text-[10px] ${proofTone}`}>
                        {isActive
                          ? "실행 중"
                          : isCompleted
                          ? "완료"
                          : isError
                          ? "오류"
                          : "대기"}
                      </span>
                      {state.lastSignal && (
                        <span className="min-w-0 max-w-full truncate rounded-full border border-white/10 bg-black/20 px-2 py-0.5 font-mono text-[10px] text-secondary">
                          {state.lastSignal}
                          {lastSignalAge ? ` · ${lastSignalAge} 전` : ""}
                        </span>
                      )}
                      {state.message && (
                        <span className="min-w-0 max-w-full truncate text-[11px] text-tertiary">
                          {state.message}
                        </span>
                      )}
                    </div>
                  )}
                  {state.referenceProjects && state.referenceProjects.length > 0 && (
                    <div className="mt-2 flex flex-wrap gap-1.5">
                      {state.referenceProjects.slice(0, 5).map((project) => (
                        <span
                          key={project}
                          className="rounded-full border border-white/10 bg-black/20 px-2 py-0.5 text-[10px] text-secondary"
                        >
                          {project}
                        </span>
                      ))}
                      {state.referenceProjects.length > 5 && (
                        <span className="rounded-full border border-white/10 px-2 py-0.5 text-[10px] text-tertiary">
                          +{state.referenceProjects.length - 5}
                        </span>
                      )}
                    </div>
                  )}
                  {state.artifactKeys && state.artifactKeys.length > 0 && (
                    <p className="mt-1 truncate font-mono text-[10px] text-tertiary">
                      artifacts: {state.artifactKeys.slice(0, 8).join(" · ")}
                      {state.artifactKeys.length > 8 ? ` · +${state.artifactKeys.length - 8}` : ""}
                    </p>
                  )}
                  {stage === "council" && councilActivity.length > 0 && (
                    <div className="mt-2 space-y-2">
                      {councilPersonas.length > 0 && (
                        <div className="flex flex-wrap gap-1.5">
                          {councilPersonas.slice(0, 8).map((persona) => (
                            <span
                              key={persona}
                              className="rounded-full border border-white/10 bg-black/20 px-2 py-0.5 font-mono text-[10px] text-secondary"
                            >
                              {compactPersonaName(persona)}
                            </span>
                          ))}
                          {councilPersonas.length > 8 && (
                            <span className="rounded-full border border-white/10 px-2 py-0.5 text-[10px] text-tertiary">
                              +{councilPersonas.length - 8}
                            </span>
                          )}
                        </div>
                      )}
                      <div className="space-y-1.5">
                        {councilActivity.slice(0, 6).map((item) => {
                          const stageLabel = item.councilStage
                            ? COUNCIL_STAGE_LABEL[item.councilStage] || item.councilStage
                            : "";
                          return (
                            <div
                              key={item.id}
                              className="min-w-0 rounded-lg border border-white/5 bg-black/20 px-2.5 py-2"
                            >
                              <div className="flex items-center justify-between gap-2">
                                <span className="min-w-0 truncate text-[10px] uppercase tracking-wider text-tertiary">
                                  {item.kind === "round_start"
                                    ? `라운드 시작 · ${item.layer}`
                                    : item.kind === "round_done"
                                    ? `라운드 완료 · ${item.layer}`
                                    : item.kind === "provider_call_start"
                                      ? `호출 시작 · ${stageLabel}${item.round ? ` · R${item.round}` : ""}`
                                      : item.kind === "provider_call_done"
                                        ? `호출 완료 · ${stageLabel}${item.round ? ` · R${item.round}` : ""}`
                                        : item.kind === "provider_call_timeout"
                                          ? `타임아웃 · ${stageLabel}${item.round ? ` · R${item.round}` : ""}`
                                          : item.kind === "provider_call_error"
                                            ? `오류 · ${stageLabel}${item.round ? ` · R${item.round}` : ""}`
                                    : `${stageLabel}${item.round ? ` · R${item.round}` : ""}`}
                                </span>
                                {item.score !== undefined && (
                                  <span className="shrink-0 rounded-full border border-white/10 px-1.5 py-0.5 font-mono text-[10px] text-secondary">
                                    {item.score}
                                  </span>
                                )}
                              </div>
                              {item.kind === "round_start" && (
                                <p className="mt-1 text-xs text-secondary">
                                  페르소나 {item.activePersonaCount ?? item.activePersonaIds?.length ?? 0}명 소환
                                </p>
                              )}
                              {item.kind === "turn" && (
                                <p className="mt-1 text-xs text-secondary">
                                  <span className="font-mono text-white">
                                    {compactPersonaName(item.persona)}
                                  </span>
                                  이(가) 응답 완료
                                  {item.responseChars ? ` · ${item.responseChars} chars` : ""}
                                  {item.provider ? ` · ${item.provider}` : ""}
                                </p>
                              )}
                              {item.kind === "token" && (
                                <>
                                  <div className="mt-1 flex items-center gap-2">
                                    <span className="font-mono text-[11px] text-white">
                                      {compactPersonaName(item.persona)}
                                    </span>
                                    {item.visualizationSource === "ollama" && (
                                      <span className="rounded-full border border-emerald-400/20 bg-emerald-400/10 px-1.5 py-0.5 text-[10px] text-emerald-200">
                                        Ollama · {item.visualizerModel}
                                      </span>
                                    )}
                                  </div>
                                  <p className="mt-1 break-words text-xs leading-relaxed text-secondary">
                                    {item.text}
                                  </p>
                                </>
                              )}
                              {item.kind === "round_done" && item.text && (
                                <p className="mt-1 break-words text-[11px] leading-relaxed text-tertiary">
                                  {item.text}
                                </p>
                              )}
                              {(item.kind === "provider_call_start" ||
                                item.kind === "provider_call_done" ||
                                item.kind === "provider_call_timeout" ||
                                item.kind === "provider_call_error") && (
                                <div className="mt-1 space-y-1 text-xs leading-relaxed text-secondary">
                                  <p>
                                    {item.providerRoute ? `route ${item.providerRoute}` : "provider route unavailable"}
                                    {item.provider ? ` · provider ${item.provider}` : ""}
                                    {item.model ? ` · ${item.model}` : ""}
                                  </p>
                                  <p className="text-[11px] text-tertiary">
                                    {item.persona ? compactPersonaName(item.persona) : "persona"}
                                    {item.timeoutSec !== undefined ? ` · timeout ${item.timeoutSec}s` : ""}
                                    {item.elapsedSec !== undefined ? ` · elapsed ${item.elapsedSec}s` : ""}
                                    {item.responseChars ? ` · ${item.responseChars} chars` : ""}
                                    {item.errorClass ? ` · ${item.errorClass}` : ""}
                                    {item.blocksProductPass ? " · blocks product pass" : ""}
                                  </p>
                                  {item.text && (
                                    <p className="break-words text-[11px] leading-relaxed text-tertiary">
                                      {item.text}
                                    </p>
                                  )}
                                </div>
                              )}
                            </div>
                          );
                        })}
                      </div>
                    </div>
                  )}
                  {(stage === "research" || stage === "evidence") && researchActivity.length > 0 && (
                    <div className="mt-2 space-y-1.5">
                      {researchActivity
                        .filter((item) => researchProgressStage({ event: "research_progress", status: item.status }, item) === stage)
                        .slice(0, 5)
                        .map((item) => {
                          const copy = researchActivityCopy(item);
                          return (
                        <div
                          key={item.id}
                          className="min-w-0 rounded-lg border border-white/5 bg-black/20 px-2.5 py-2"
                        >
                          <div className="flex items-center justify-between gap-2">
                            <span className="text-[10px] uppercase tracking-wider text-tertiary">
                              {copy.label}
                              {item.queryIndex && item.queryCount
                                ? ` · ${item.queryIndex}/${item.queryCount}`
                                : ""}
                            </span>
                            {item.sourceGrade && (
                              <span className="shrink-0 rounded-full border border-white/10 px-1.5 py-0.5 font-mono text-[10px] text-secondary">
                                {item.sourceGrade}
                              </span>
                            )}
                          </div>
                          {item.status === "research_plan_ready" ? (
                            <div className="mt-1 space-y-1.5 text-xs leading-relaxed text-secondary">
                              <p>{copy.message}</p>
                              <div className="flex flex-wrap gap-1">
                                {researchPlanSummaryChips(item).map((detail) => (
                                  <span
                                    key={detail}
                                    className="rounded border border-white/10 px-1.5 py-0.5 font-mono text-[10px] text-tertiary"
                                  >
                                    {detail}
                                  </span>
                                ))}
                              </div>
                              <div className="space-y-1">
                                {researchPlanDisplayRows(item).map((row, routeIndex) => (
                                  <details
                                    key={`${row.query || "route"}-${routeIndex}`}
                                    className="min-w-0 rounded border border-white/5 bg-white/[0.02] px-2 py-1"
                                    open={routeIndex < 3}
                                  >
                                    <summary className="cursor-pointer break-words text-[11px] text-secondary marker:text-tertiary">
                                      {routeIndex + 1}. {row.query || `query ${routeIndex + 1}`}
                                    </summary>
                                    <div className="mt-1 space-y-0.5">
                                      {row.routeDetails.length > 0 && (
                                        <p className="break-words text-[10px] text-tertiary">
                                          {row.routeDetails.join(" · ")}
                                        </p>
                                      )}
                                      {row.continueReason && (
                                        <p className="break-words text-[10px] text-tertiary">
                                          continue reason: {row.continueReason}
                                        </p>
                                      )}
                                      {row.authorityRequirement && (
                                        <p className="break-words text-[10px] text-tertiary">
                                          authority requirement: {row.authorityRequirement}
                                        </p>
                                      )}
                                      {row.acceptanceRules.length > 0 && (
                                        <p className="break-words text-[10px] text-tertiary">
                                          acceptance rules: {row.acceptanceRules.join("; ")}
                                        </p>
                                      )}
                                    </div>
                                  </details>
                                ))}
                              </div>
                            </div>
                          ) : item.status === "source_found" || item.status === "source_evaluated" ? (
                            <>
                              <p className="mt-1 truncate text-xs text-secondary">
                                {item.sourceTitle || "로컬/내부 근거"}
                              </p>
                              {item.sourceUrl && (
                                <p className="mt-0.5 truncate font-mono text-[10px] text-tertiary">
                                  {item.sourceUrl}
                                </p>
                              )}
                              {item.status === "source_evaluated" && (
                                <div className="mt-1 flex flex-wrap gap-1 text-[10px] text-tertiary">
                                  {item.sourceKind && <span>kind: {item.sourceKind}</span>}
                                  {item.facetIds && item.facetIds.length > 0 && (
                                    <span>facets: {item.facetIds.join(", ")}</span>
                                  )}
                                  {item.relevanceScore !== undefined && (
                                    <span>relevance: {Math.round(item.relevanceScore * 100)}%</span>
                                  )}
                                </div>
                              )}
                              {item.reason && (
                                <p className="mt-1 break-words text-[11px] leading-relaxed text-tertiary">
                                  {item.reason}
                                </p>
                              )}
                              {item.query && (
                                <p className="mt-1 break-words text-[11px] leading-relaxed text-tertiary">
                                  {item.query}
                                </p>
                              )}
                            </>
                          ) : item.status === "knowledge_gap" ? (
                            <div className="mt-1 space-y-1 text-xs leading-relaxed text-secondary">
                              <p>{item.message || "필수 facet 근거가 부족합니다."}</p>
                              <p className="text-[11px] text-tertiary">
                                {item.facetId || "facet"}: {item.acceptedCount ?? 0}/{item.minAcceptedSources ?? "?"} accepted sources
                              </p>
                            </div>
                          ) : item.status === "facet_summary" ? (
                            <p className="mt-1 break-words text-xs leading-relaxed text-secondary">
                              근거 facet 요약 완료 · gaps {item.gapCount ?? 0}
                            </p>
                          ) : item.status === "source_audit_gate" || item.status === "claim_evidence_gate" || item.status === "max_plus_benchmark_scored" || item.status === "research_quality_ready" ? (
                            <div className="mt-1 space-y-1 text-xs leading-relaxed text-secondary">
                              <p>{copy.message}</p>
                              {item.benchmarkId && (
                                <p className="break-words font-mono text-[10px] leading-relaxed text-tertiary">
                                  {item.benchmarkId}
                                </p>
                              )}
                              {researchQualityDetailChips(item).length > 0 && (
                                <div className="flex flex-wrap gap-1">
                                  {researchQualityDetailChips(item).map((detail) => (
                                    <span
                                      key={detail}
                                      className="rounded border border-white/10 px-1.5 py-0.5 font-mono text-[10px] text-tertiary"
                                    >
                                      {detail}
                                    </span>
                                  ))}
                                </div>
                              )}
                              {item.metrics && Object.keys(item.metrics).length > 0 && (
                                <div className="flex flex-wrap gap-1">
                                  {Object.entries(item.metrics).map(([key, value]) => (
                                    <span
                                      key={key}
                                      className="rounded border border-white/10 px-1.5 py-0.5 font-mono text-[10px] text-tertiary"
                                    >
                                      {formatBenchmarkMetricLabel(key)} {formatBenchmarkMetricValue(value)}
                                    </span>
                                  ))}
                                </div>
                              )}
                              {item.reason && (
                                <p className="break-words text-[11px] leading-relaxed text-tertiary">
                                  {item.reason}
                                </p>
                              )}
                            </div>
                          ) : (
                            <p className="mt-1 break-words text-xs leading-relaxed text-secondary">
                              {item.query || copy.message}
                            </p>
                          )}
                          {[item.facetId ? `facet ${item.facetId}` : undefined, item.purpose ? `purpose ${item.purpose}` : undefined, item.sourceClass ? `source class ${item.sourceClass}` : undefined, item.intent ? `intent ${item.intent}` : undefined, item.backend ? `backend ${item.backend}` : undefined]
                            .filter(Boolean).length > 0 && (
                            <p className="mt-1 break-words text-[10px] leading-relaxed text-tertiary">
                              {[item.facetId ? `facet ${item.facetId}` : undefined, item.purpose ? `purpose ${item.purpose}` : undefined, item.sourceClass ? `source class ${item.sourceClass}` : undefined, item.intent ? `intent ${item.intent}` : undefined, item.backend ? `backend ${item.backend}` : undefined]
                                .filter(Boolean)
                                .join(" · ")}
                            </p>
                          )}
                          {item.continueReason && (
                            <p className="mt-1 break-words text-[10px] leading-relaxed text-tertiary">
                              continue reason: {item.continueReason}
                            </p>
                          )}
                          {item.authorityRequirement && (
                            <p className="mt-1 break-words text-[10px] leading-relaxed text-tertiary">
                              authority requirement: {item.authorityRequirement}
                            </p>
                          )}
                          {item.acceptanceRules && item.acceptanceRules.length > 0 && (
                            <p className="mt-1 break-words text-[10px] leading-relaxed text-tertiary">
                              acceptance rules: {item.acceptanceRules.join("; ")}
                            </p>
                          )}
                          {item.backends && item.backends.length > 0 && (
                            <p className="mt-1 truncate text-[11px] text-tertiary">
                              {item.backends.join(" · ")}
                            </p>
                          )}
                        </div>
                          );
                        })}
                    </div>
                  )}
                </div>
              </li>
            );
          })}
        </ul>

        {/* Report preview */}
        {reportPreview && !finalReport && (
          <div className="fade-in mt-8 rounded-lg border border-white/5 bg-white/[0.02] p-4 shadow-[var(--shadow-paper)]">
            <p className="mb-3 text-[11px] uppercase tracking-wider text-tertiary">
              Report preview
            </p>
            <div className="space-y-3">
              <EvidenceIndexPanel markdown={reportPreview} compact title="보고서 근거 요약" />
              <details className="rounded-lg border border-white/10 bg-black/15 px-3 py-2">
                <summary className="cursor-pointer text-xs text-secondary transition hover:text-white">
                  원본 Markdown 보기
                </summary>
                <pre className="mt-2 max-h-56 overflow-auto whitespace-pre-wrap break-words text-[11px] leading-relaxed text-tertiary">
                  {reportPreview}
                </pre>
              </details>
            </div>
          </div>
        )}

        {/* Final report */}
        {finalReport && (
          <div className="fade-in mt-8 rounded-lg border border-emerald-500/10 bg-emerald-500/[0.02] p-4 shadow-[var(--shadow-paper)]">
            <p className="mb-3 flex items-center gap-2 text-[11px] font-semibold uppercase tracking-wider text-emerald-200">
              <svg className="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
              </svg>
              Final report
            </p>
            <div className="space-y-3">
              <EvidenceIndexPanel markdown={finalReport} compact title="보고서 근거 요약" />
              <details className="rounded-lg border border-white/10 bg-black/15 px-3 py-2">
                <summary className="cursor-pointer text-xs text-secondary transition hover:text-white">
                  원본 Markdown 보기
                </summary>
                <pre className="mt-2 max-h-96 overflow-auto whitespace-pre-wrap break-words text-[11px] leading-relaxed text-tertiary">
                  {finalReport}
                </pre>
              </details>
            </div>
          </div>
        )}

        {/* Streaming token cards (minimal monochrome) */}
        {tokenCards.length > 0 && (
          <div className="fade-in mt-8">
            <p className="mb-3 text-[11px] uppercase tracking-wider text-tertiary">
              Council activity
            </p>
            <div className="space-y-px overflow-hidden rounded-lg border border-white/5">
              {tokenCards.map((card, idx) => (
                <div
                  key={idx}
                  className="bg-white/[0.02] px-4 py-3"
                >
                  <div className="mb-1 flex items-center gap-2 text-[10px] text-tertiary">
                    <span className="font-mono text-white">{card.persona}</span>
                    {card.layer && <span>·</span>}
                    {card.layer && <span>{card.layer}</span>}
                    {card.round !== undefined && <span>·</span>}
                    {card.round !== undefined && <span>R{card.round}</span>}
                  </div>
                  <p className="break-words text-xs leading-relaxed text-secondary">{card.text}</p>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
