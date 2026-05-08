export interface DiscoveredSource {
  key: string;
  title: string;
  url?: string;
  grade?: string;
  kind?: string;
  status: "found" | "accepted" | "rejected";
  accessStatus?: string;
  relevanceScore?: number;
  reason?: string;
  facetIds?: string[];
  backends?: string[];
  query?: string;
  firstSeenAt: number;
  evaluatedAt?: number;
}

export interface KnowledgeGap {
  facetId: string;
  message?: string;
  acceptedCount?: number;
  minAcceptedSources?: number;
  firstSeenAt: number;
}

export interface SourceDiscoveryPanelProps {
  sources: DiscoveredSource[];
  gaps: KnowledgeGap[];
  compact?: boolean;
}

function sourceKey(activity: {
  sourceUrl?: string;
  sourceTitle?: string;
  query?: string;
}): string {
  return (activity.sourceUrl || activity.sourceTitle || activity.query || "unknown").trim();
}

export function buildDiscoveredSourceMap(
  prev: Map<string, DiscoveredSource>,
  activity: {
    status: string;
    sourceTitle?: string;
    sourceUrl?: string;
    sourceGrade?: string;
    sourceKind?: string;
    accessStatus?: string;
    accepted?: boolean;
    relevanceScore?: number;
    reason?: string;
    facetIds?: string[];
    backends?: string[];
    query?: string;
  },
): Map<string, DiscoveredSource> {
  const key = sourceKey(activity);
  const existing = prev.get(key);
  const now = Date.now();

  if (activity.status === "source_found") {
    const next: DiscoveredSource = {
      key,
      title: activity.sourceTitle || key,
      url: activity.sourceUrl || undefined,
      grade: activity.sourceGrade || existing?.grade,
      kind: activity.sourceKind || existing?.kind,
      accessStatus: activity.accessStatus || existing?.accessStatus,
      status: existing?.status || "found",
      relevanceScore:
        activity.relevanceScore !== undefined
          ? activity.relevanceScore
          : existing?.relevanceScore,
      reason: activity.reason || existing?.reason,
      facetIds: activity.facetIds || existing?.facetIds,
      backends: activity.backends || existing?.backends,
      query: activity.query || existing?.query,
      firstSeenAt: existing?.firstSeenAt || now,
      evaluatedAt: existing?.evaluatedAt,
    };
    return new Map(prev).set(key, next);
  }

  if (activity.status === "source_evaluated") {
    const next: DiscoveredSource = {
      key,
      title: activity.sourceTitle || existing?.title || key,
      url: activity.sourceUrl || existing?.url,
      grade: activity.sourceGrade || existing?.grade,
      kind: activity.sourceKind || existing?.kind,
      accessStatus: activity.accessStatus || existing?.accessStatus,
      status: activity.accepted === true ? "accepted" : "rejected",
      relevanceScore:
        activity.relevanceScore !== undefined
          ? activity.relevanceScore
          : existing?.relevanceScore,
      reason: activity.reason || existing?.reason,
      facetIds: activity.facetIds || existing?.facetIds,
      backends: activity.backends || existing?.backends,
      query: activity.query || existing?.query,
      firstSeenAt: existing?.firstSeenAt || now,
      evaluatedAt: now,
    };
    return new Map(prev).set(key, next);
  }

  return prev;
}

export function buildKnowledgeGaps(
  prev: KnowledgeGap[],
  activity: {
    status: string;
    facetId?: string;
    message?: string;
    acceptedCount?: number;
    minAcceptedSources?: number;
  },
): KnowledgeGap[] {
  if (activity.status !== "knowledge_gap") return prev;
  const facetId = activity.facetId || "unknown";
  const filtered = prev.filter((g) => g.facetId !== facetId);
  return [
    ...filtered,
    {
      facetId,
      message: activity.message,
      acceptedCount: activity.acceptedCount,
      minAcceptedSources: activity.minAcceptedSources,
      firstSeenAt: Date.now(),
    },
  ];
}

export function discoveryBreadth(sources: DiscoveredSource[]): { backends: string[]; queries: string[] } {
  const backendSet = new Set<string>();
  const querySet = new Set<string>();
  for (const s of sources) {
    if (s.backends) s.backends.forEach((b) => backendSet.add(b));
    if (s.query) querySet.add(s.query);
  }
  return { backends: Array.from(backendSet), queries: Array.from(querySet) };
}

type SourceAccessStatus =
  | "full_text_available"
  | "abstract_only"
  | "oa_copy_found"
  | "blocked"
  | "alternative_evidence";

const SOURCE_ACCESS_LABELS: Record<SourceAccessStatus, string> = {
  full_text_available: "Full text",
  abstract_only: "Abstract",
  oa_copy_found: "Open access",
  blocked: "Restricted",
  alternative_evidence: "Alternative",
};

export function normalizeSourceAccessStatus(status: string | undefined): SourceAccessStatus | undefined {
  const clean = String(status ?? "")
    .trim()
    .toLowerCase()
    .replace(/[\s-]+/g, "_");
  if (!clean) return undefined;
  if (["full_text_available", "full_text", "pdf_available", "open_pdf"].includes(clean)) {
    return "full_text_available";
  }
  if (["abstract_only", "metadata_only", "abstract"].includes(clean)) return "abstract_only";
  if (["oa_copy_found", "open_access_copy", "oa_copy", "unpaywall_oa", "open_access"].includes(clean)) {
    return "oa_copy_found";
  }
  if (["blocked", "paywalled", "login_required", "access_restricted"].includes(clean)) return "blocked";
  if (["alternative_evidence", "alternative", "substitute_evidence"].includes(clean)) {
    return "alternative_evidence";
  }
  return undefined;
}

export function displayAccessStatus(status: string | undefined): string {
  const normalized = normalizeSourceAccessStatus(status);
  if (normalized) return SOURCE_ACCESS_LABELS[normalized];
  return status ? status.replace(/_/g, " ") : "Not reported";
}

export default function SourceDiscoveryPanel({ sources, gaps, compact = false }: SourceDiscoveryPanelProps) {
  const accepted = sources.filter((s) => s.status === "accepted");
  const rejected = sources.filter((s) => s.status === "rejected");
  const pending = sources.filter((s) => s.status === "found");
  const { backends, queries } = discoveryBreadth(sources);

  if (sources.length === 0 && gaps.length === 0) return null;

  const visibleSources = compact ? sources.slice(0, 6) : sources;

  return (
    <section className="source-discovery-panel">
      <header className="flex flex-col gap-3 border-b border-white/5 px-4 py-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <p className="atlas-label">Source Discovery</p>
          <h2 className="mt-1 text-lg font-semibold text-white">
            {sources.length > 0 ? `${sources.length} sources discovered` : "No sources yet"}
          </h2>
          {(backends.length > 0 || queries.length > 0) && (
            <p className="mt-1 text-[11px] text-tertiary">
              {backends.length > 0 && `Searched ${backends.length} backend${backends.length > 1 ? "s" : ""}`}
              {backends.length > 0 && queries.length > 0 && " · "}
              {queries.length > 0 && `${queries.length} query${queries.length > 1 ? "ies" : ""} produced sources`}
            </p>
          )}
        </div>
        <div className="flex flex-wrap gap-2">
          {accepted.length > 0 && (
            <MetricPill label="accepted" value={String(accepted.length)} tone="emerald" />
          )}
          {pending.length > 0 && (
            <MetricPill label="pending" value={String(pending.length)} tone="amber" />
          )}
          {rejected.length > 0 && (
            <MetricPill label="rejected" value={String(rejected.length)} tone="red" />
          )}
          {gaps.length > 0 && (
            <MetricPill label="gaps" value={String(gaps.length)} tone="sky" />
          )}
        </div>
      </header>

      {gaps.length > 0 && (
        <div className="border-b border-white/5 px-4 py-3">
          <p className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-sky-200">
            Knowledge gaps
          </p>
          <div className="flex flex-wrap gap-2">
            {gaps.map((gap) => (
              <span
                key={gap.facetId}
                className="inline-flex items-center gap-1.5 rounded-md border border-sky-300/15 bg-sky-300/10 px-2.5 py-1 text-[11px] text-sky-100"
                title={gap.message}
              >
                <span className="font-mono text-[10px] text-sky-200">{gap.facetId}</span>
                <span className="text-tertiary">·</span>
                <span>
                  {gap.acceptedCount ?? 0}/{gap.minAcceptedSources ?? "?"}
                </span>
              </span>
            ))}
          </div>
        </div>
      )}

      <div>
        {visibleSources.map((source) => (
          <SourceRow key={source.key} source={source} />
        ))}
      </div>

      {compact && sources.length > visibleSources.length && (
        <details className="border-t border-white/5 px-4 py-3">
          <summary className="cursor-pointer text-xs text-secondary transition hover:text-white">
            나머지 {sources.length - visibleSources.length}개 출처 보기
          </summary>
          <div className="mt-3 overflow-hidden rounded-lg border border-white/5">
            {sources.slice(visibleSources.length).map((source) => (
              <SourceRow key={`more-${source.key}`} source={source} />
            ))}
          </div>
        </details>
      )}
    </section>
  );
}

function MetricPill({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone: "emerald" | "amber" | "red" | "sky";
}) {
  const toneClasses = {
    emerald: "border-emerald-300/20 bg-emerald-300/10 text-emerald-100",
    amber: "border-amber-300/20 bg-amber-300/10 text-amber-100",
    red: "border-red-300/20 bg-red-300/10 text-red-100",
    sky: "border-sky-300/20 bg-sky-300/10 text-sky-100",
  };
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-md border px-2.5 py-1 text-[11px] ${toneClasses[tone]}`}
    >
      <span className="opacity-70">{label}</span>
      <span className="font-mono font-semibold">{value}</span>
    </span>
  );
}

function SourceRow({ source }: { source: DiscoveredSource }) {
  const statusTone =
    source.status === "accepted"
      ? "border-emerald-300/25 bg-emerald-300/10 text-emerald-100"
      : source.status === "rejected"
      ? "border-red-300/20 bg-red-300/10 text-red-100"
      : "border-amber-300/20 bg-amber-300/10 text-amber-100";

  const statusLabel =
    source.status === "accepted" ? "Accepted" : source.status === "rejected" ? "Rejected" : "Found";

  return (
    <article className="grid gap-3 px-4 py-4 sm:grid-cols-[minmax(0,1fr)_auto]">
      <div className="min-w-0">
        <div className="mb-1.5 flex flex-wrap items-center gap-1.5">
          <span
            className={`rounded-md border px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${statusTone}`}
          >
            {statusLabel}
          </span>
          {source.grade && (
            <span className="rounded-md border border-white/10 bg-white/[0.03] px-2 py-0.5 text-[10px] text-secondary">
              Grade {source.grade}
            </span>
          )}
          {source.kind && (
            <span className="rounded-md border border-white/10 px-2 py-0.5 text-[10px] text-tertiary">
              {source.kind}
            </span>
          )}
          <span className="rounded-md border border-violet-300/20 bg-violet-300/10 px-2 py-0.5 text-[10px] text-violet-100">
            Access status · {displayAccessStatus(source.accessStatus)}
          </span>
          {source.relevanceScore !== undefined && (
            <span className="rounded-md border border-white/10 px-2 py-0.5 font-mono text-[10px] text-secondary">
              relevance {Math.round(source.relevanceScore * 100)}%
            </span>
          )}
        </div>
        <h3 className="break-words text-[15px] font-semibold leading-6 text-white">
          {source.title}
        </h3>
        {source.url && (
          <p className="mt-1 break-words rounded-md border border-white/10 bg-white/[0.03] px-2 py-1 font-mono text-[11px] leading-relaxed text-tertiary">
            {source.url.length > 120 ? `${source.url.slice(0, 116)}...` : source.url}
          </p>
        )}
        {source.reason && (
          <p className="mt-2 break-words text-xs leading-6 text-secondary">{source.reason}</p>
        )}
        {source.facetIds && source.facetIds.length > 0 && (
          <p className="mt-1 text-[10px] text-tertiary">facets: {source.facetIds.join(" · ")}</p>
        )}
        {source.backends && source.backends.length > 0 && (
          <p className="mt-1 text-[10px] text-tertiary">{source.backends.join(" · ")}</p>
        )}
      </div>
      <div className="min-w-0 text-left sm:max-w-44 sm:text-right">
        <p className="font-mono text-[10px] leading-relaxed text-tertiary">
          {source.firstSeenAt ? new Date(source.firstSeenAt).toLocaleTimeString() : ""}
        </p>
        {source.evaluatedAt && (
          <p className="mt-1 text-[10px] uppercase tracking-wide text-tertiary">
            evaluated {formatElapsed(source.evaluatedAt - source.firstSeenAt)}
          </p>
        )}
      </div>
    </article>
  );
}

function formatElapsed(ms: number): string {
  const seconds = Math.max(0, Math.round(ms / 1000));
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  return `${minutes}m ${seconds % 60}s`;
}
