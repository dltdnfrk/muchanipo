/**
 * Stable surface for the council persona pool. Reads telemetry that the Python
 * pipeline already records as artifacts on `stage_completed.artifacts.persona_*`
 * (see `src/pipeline/idea_to_council.py:_persona_generation_telemetry`). This
 * component renders a fixed-shape card so the user can see Studio → Browser
 * persona handoff: seed source (Nemotron-Personas-Korea), validation framework
 * (HACHIMI), diversity framework (MAP-Elites), council protocol (OASIS/CAMEL),
 * and pool/fallback counts.
 *
 * No copy mutates in place; status pill widths are fixed; references are stable
 * product nouns sourced from backend telemetry, not hardcoded chrome.
 */
export interface PersonaPoolSummary {
  seedSource: string;
  validationFramework: string;
  diversityFramework: string;
  councilProtocol: string;
  poolSize: number;
  poolTargetSize: number;
  activeCount: number;
  diversityCoverage: number;
  diversityBinsPerAxis: number;
  fallbacksUsed: number;
}

function formatRatio(used: number, target: number): string {
  if (!Number.isFinite(target) || target <= 0) return `${used}`;
  return `${used} / ${target}`;
}

function formatPercent(value: number): string {
  if (!Number.isFinite(value)) return "—";
  return `${(value * 100).toFixed(1)}%`;
}

export function PersonaPoolCard({ pool }: { pool: PersonaPoolSummary | null }) {
  if (!pool) {
    return (
      <section className="rounded-xl border border-white/10 bg-white/[0.02] p-4">
        <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-tertiary">
          Persona Pool
        </p>
        <p className="mt-2 text-sm text-tertiary">
          Council 단계가 시작되면 Persona seed/validation/diversity 정보가 채워집니다.
        </p>
      </section>
    );
  }

  return (
    <section className="rounded-xl border border-white/10 bg-white/[0.02] p-4">
      <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-tertiary">
        Persona Pool
      </p>

      <div className="mt-3 grid grid-cols-2 gap-3 text-[12px]">
        <Field label="Seed" value={pool.seedSource || "none"} />
        <Field label="Validation" value={pool.validationFramework || "—"} />
        <Field label="Diversity" value={pool.diversityFramework || "—"} />
        <Field label="Council" value={pool.councilProtocol || "—"} />
      </div>

      <div className="mt-3 grid grid-cols-3 gap-3 text-[12px]">
        <Metric label="Pool" value={formatRatio(pool.poolSize, pool.poolTargetSize)} />
        <Metric label="Active" value={String(pool.activeCount)} />
        <Metric label="Fallbacks" value={String(pool.fallbacksUsed)} />
      </div>

      <div className="mt-3 grid grid-cols-2 gap-3 text-[12px]">
        <Metric label="Diversity coverage" value={formatPercent(pool.diversityCoverage)} />
        <Metric label="MAP-Elites bins/axis" value={String(pool.diversityBinsPerAxis)} />
      </div>
    </section>
  );
}

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-white/10 bg-black/20 px-3 py-2">
      <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-tertiary">
        {label}
      </p>
      <p className="mt-1 truncate text-[12px] text-white">{value}</p>
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-white/10 bg-black/20 px-3 py-2">
      <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-tertiary">
        {label}
      </p>
      <p className="mt-1 font-mono text-[13px] tabular-nums text-white">{value}</p>
    </div>
  );
}

/** Map raw stage_completed.artifacts payload into a stable summary shape. */
export function normalizePersonaPoolSummary(
  artifacts: Record<string, unknown> | undefined | null,
): PersonaPoolSummary | null {
  if (!artifacts) return null;
  const seedSource = String(artifacts.persona_seed_source ?? "").trim();
  const validation = String(artifacts.persona_validation_framework ?? "").trim();
  const diversity = String(artifacts.persona_diversity_framework ?? "").trim();
  const council = String(artifacts.council_protocol ?? "").trim();
  const poolSize = Number(artifacts.persona_pool_size ?? 0);
  const poolTarget = Number(artifacts.persona_pool_target_size ?? 0);
  const active = Number(artifacts.active_persona_count ?? 0);
  const coverage = Number(artifacts.persona_diversity_coverage ?? 0);
  const bins = Number(artifacts.persona_diversity_bins_per_axis ?? 0);
  const fallbacks = Number(artifacts.persona_fallbacks_used ?? 0);

  // Require at least one identifying field to avoid showing an empty card.
  if (!seedSource && !validation && !diversity && !council && poolSize === 0) {
    return null;
  }
  return {
    seedSource,
    validationFramework: validation,
    diversityFramework: diversity,
    councilProtocol: council,
    poolSize: Number.isFinite(poolSize) ? poolSize : 0,
    poolTargetSize: Number.isFinite(poolTarget) ? poolTarget : 0,
    activeCount: Number.isFinite(active) ? active : 0,
    diversityCoverage: Number.isFinite(coverage) ? coverage : 0,
    diversityBinsPerAxis: Number.isFinite(bins) ? bins : 0,
    fallbacksUsed: Number.isFinite(fallbacks) ? fallbacks : 0,
  };
}
