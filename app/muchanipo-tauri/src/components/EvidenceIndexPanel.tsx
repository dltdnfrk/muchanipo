import {
  compactEvidenceId,
  displayEvidenceUrl,
  evidenceSourcesFromRefs,
  parseEvidenceIndex,
  summarizeEvidenceSource,
  accessStatusLabel,
  type EvidenceHealth,
  type EvidenceSource,
} from "../lib/reportPresentation";

interface EvidenceIndexPanelProps {
  markdown?: string;
  evidenceRefs?: unknown;
  compact?: boolean;
  title?: string;
}

export default function EvidenceIndexPanel({
  markdown = "",
  evidenceRefs,
  compact = false,
  title = "근거 출처",
}: EvidenceIndexPanelProps) {
  const parsed = markdown ? parseEvidenceIndex(markdown) : { health: {}, sources: [] };
  const sources = evidenceSourcesFromRefs(evidenceRefs);
  const evidenceSources = sources.length > 0 ? sources : parsed.sources;
  const health = parsed.health;
  const visibleSources = compact ? evidenceSources.slice(0, 6) : evidenceSources;

  if (evidenceSources.length === 0 && !hasHealth(health)) return null;

  return (
    <section className="evidence-index-panel">
      <header className="flex flex-col gap-3 border-b border-white/5 px-4 py-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <p className="atlas-label">
            Evidence Index
          </p>
          <h2 className="mt-1 text-lg font-semibold text-white">{title}</h2>
        </div>
        <div className="flex flex-wrap gap-2">
          {health.trusted && <MetricPill label="trusted" value={health.trusted} />}
          {health.verifiedClaimRatio && <MetricPill label="verified" value={health.verifiedClaimRatio} />}
          {health.unsupportedFindingCount && (
            <MetricPill label="unsupported" value={health.unsupportedFindingCount} />
          )}
          {!health.trusted && evidenceSources.length > 0 && (
            <MetricPill label="sources" value={String(evidenceSources.length)} />
          )}
        </div>
      </header>

      {health.gradeCounts && (
        <div className="border-b border-white/5 px-4 py-2 text-xs text-tertiary">
          Grade counts · {health.gradeCounts}
        </div>
      )}

      <div>
        {visibleSources.map((source, index) => (
          <EvidenceSourceRow key={`${source.id}-${index}`} source={source} compact={compact} />
        ))}
      </div>

      {compact && evidenceSources.length > visibleSources.length && (
        <details className="border-t border-white/5 px-4 py-3">
          <summary className="cursor-pointer text-xs text-secondary transition hover:text-white">
            나머지 {evidenceSources.length - visibleSources.length}개 출처 보기
          </summary>
          <div className="mt-3 overflow-hidden rounded-lg border border-white/5">
            {evidenceSources.slice(visibleSources.length).map((source, index) => (
              <EvidenceSourceRow key={`${source.id}-more-${index}`} source={source} compact />
            ))}
          </div>
        </details>
      )}
    </section>
  );
}

function MetricPill({ label, value }: { label: string; value: string }) {
  return (
    <span className="inline-flex items-center gap-1 rounded-md border border-white/10 bg-white/[0.03] px-2.5 py-1 text-[11px] text-secondary">
      <span className="text-tertiary">{label}</span>
      <span className="font-mono text-white">{value}</span>
    </span>
  );
}

function EvidenceSourceRow({ source, compact }: { source: EvidenceSource; compact?: boolean }) {
  const gradeTone =
    source.grade === "A"
      ? "border-emerald-300/25 bg-emerald-300/10 text-emerald-100"
      : source.grade === "B"
      ? "border-sky-300/20 bg-sky-300/10 text-sky-100"
      : "border-white/10 bg-white/[0.03] text-secondary";
  const accessTone = source.accessStatus
    ? "border-amber-300/15 bg-amber-300/10 text-amber-100"
    : "border-white/10 bg-white/[0.03] text-tertiary";

  return (
    <article className="evidence-row grid gap-3 px-4 py-4 sm:grid-cols-[minmax(0,1fr)_auto]">
      <div className="min-w-0">
        <div className="mb-1.5 flex flex-wrap items-center gap-1.5">
          <span className="rounded-md border border-white/10 bg-white/[0.03] px-2 py-0.5 text-[10px] font-medium uppercase tracking-wide text-tertiary">
            {source.providerLabel}
          </span>
          {source.grade && (
            <span className={`rounded-md border px-2 py-0.5 text-[10px] font-semibold ${gradeTone}`}>
              {source.grade}
            </span>
          )}
          {source.provenance && (
            <span className="rounded-md border border-white/10 px-2 py-0.5 text-[10px] text-tertiary">
              {source.provenance}
            </span>
          )}
          <span className={`rounded-md border px-2 py-0.5 text-[10px] ${accessTone}`}>
            Access status · {accessStatusLabel(source.accessStatus)}
          </span>
        </div>
        <h3 className="break-words text-[15px] font-semibold leading-6 text-white">
          {source.title}
        </h3>
        {source.url && (
          <p className="mt-1 break-words rounded-md border border-white/10 bg-white/[0.03] px-2 py-1 font-mono text-[11px] leading-relaxed text-tertiary">
            {displayEvidenceUrl(source.url)}
          </p>
        )}
        {!compact && source.quote && (
          <p className="mt-2 break-words text-xs leading-6 text-secondary">
            {source.quote}
          </p>
        )}
      </div>
      <div className="min-w-0 text-left sm:max-w-44 sm:text-right">
        <p className="font-mono text-[10px] leading-relaxed text-tertiary">
          {compactEvidenceId(source.id)}
        </p>
        <p className="mt-1 text-[10px] uppercase tracking-wide text-tertiary">
          {summarizeEvidenceSource(source)}
        </p>
      </div>
    </article>
  );
}

function hasHealth(health: EvidenceHealth): boolean {
  return Boolean(
    health.trusted ||
      health.verifiedClaimRatio ||
      health.unsupportedFindingCount ||
      health.gradeCounts,
  );
}
