export interface EvidenceHealth {
  trusted?: string;
  verifiedClaimRatio?: string;
  unsupportedFindingCount?: string;
  gradeCounts?: string;
}

export type EvidenceAccessStatus =
  | "full_text_available"
  | "abstract_only"
  | "oa_copy_found"
  | "blocked"
  | "alternative_evidence";

export interface EvidenceSource {
  id: string;
  provider: string;
  providerLabel: string;
  title: string;
  url?: string;
  grade?: string;
  provenance?: string;
  quote?: string;
  accessStatus?: EvidenceAccessStatus;
}

export interface EvidenceIndex {
  health: EvidenceHealth;
  sources: EvidenceSource[];
}

const PROVIDER_LABELS: Record<string, string> = {
  arxiv: "arXiv",
  crossref: "Crossref",
  insight_forge: "InsightForge",
  mempalace: "MemPalace",
  openalex: "OpenAlex",
  semantic_scholar: "Semantic Scholar",
  vault: "Vault",
  web_search: "Web",
};

export function parseEvidenceIndex(markdown: string): EvidenceIndex {
  const block = extractEvidenceBlock(markdown);
  if (!block) return { health: {}, sources: [] };

  return {
    health: parseEvidenceHealth(block),
    sources: parseEvidenceSources(block),
  };
}

export function evidenceSourcesFromRefs(refs: unknown): EvidenceSource[] {
  if (!Array.isArray(refs)) return [];
  return refs
    .map((raw): EvidenceSource | null => {
      if (!raw || typeof raw !== "object") return null;
      const item = raw as Record<string, unknown>;
      const id = cleanText(String(item.id ?? ""));
      const title = cleanText(String((item.source_title ?? item.title ?? id) || "출처"));
      const url = cleanText(String(item.source_url ?? item.url ?? ""));
      const grade = cleanText(String(item.source_grade ?? item.grade ?? ""));
      const provenance =
        typeof item.provenance === "string"
          ? cleanText(item.provenance)
          : item.provenance && typeof item.provenance === "object"
          ? cleanText(String((item.provenance as Record<string, unknown>).kind ?? ""))
          : "";
      const provider = inferProvider(id || url || provenance);
      return {
        id,
        provider,
        providerLabel: PROVIDER_LABELS[provider] || titleCase(provider),
        title,
        url: url || undefined,
        grade: grade || undefined,
        provenance: provenance || undefined,
        quote: cleanText(String(item.quote ?? "")).trim() || undefined,
        accessStatus: normalizeAccessStatus(
          item.access_status ?? item.accessStatus ?? item.full_text_status ?? item.source_access_status,
        ),
      };
    })
    .filter((item): item is EvidenceSource => item !== null);
}

export function summarizeEvidenceSource(source: EvidenceSource): string {
  const parts = [source.providerLabel];
  if (source.grade) parts.push(`Grade ${source.grade}`);
  parts.push(accessStatusLabel(source.accessStatus));
  return parts.join(" · ");
}

export function accessStatusLabel(status?: EvidenceAccessStatus): string {
  if (!status) return "Not reported";
  const labels: Record<EvidenceAccessStatus, string> = {
    full_text_available: "Full text",
    abstract_only: "Abstract",
    oa_copy_found: "Open access",
    blocked: "Restricted",
    alternative_evidence: "Alternative",
  };
  return labels[status];
}

export function normalizeAccessStatus(value: unknown): EvidenceAccessStatus | undefined {
  const clean = String(value ?? "")
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

export function compactEvidenceId(id: string): string {
  const clean = id.trim();
  if (!clean) return "";
  if (clean.length <= 34) return clean;
  const prefix = clean.slice(0, 18);
  const suffix = clean.slice(-10);
  return `${prefix}...${suffix}`;
}

export function displayEvidenceUrl(url: string | undefined): string {
  if (!url) return "";
  if (url.startsWith("mempalace:")) return url.replace(/^mempalace:/, "mempalace · ");
  try {
    const parsed = new URL(url);
    const host = parsed.hostname.replace(/^www\./, "");
    const path = parsed.pathname === "/" ? "" : parsed.pathname;
    return `${host}${path}`.slice(0, 90);
  } catch {
    return url.length > 90 ? `${url.slice(0, 86)}...` : url;
  }
}

function extractEvidenceBlock(markdown: string): string {
  const match = markdown.match(/##\s*Evidence Index\s*\n([\s\S]*?)(?=\n##\s*Chapter|\n##\s+[^\n]+|$)/i);
  return match?.[1] ?? "";
}

function parseEvidenceHealth(block: string): EvidenceHealth {
  const health: EvidenceHealth = {};
  const trusted = block.match(/Trusted evidence:\s*([^\n]+)/i);
  const ratio = block.match(/Verified claim ratio:\s*([^\n]+)/i);
  const unsupported = block.match(/Unsupported finding count:\s*([^\n]+)/i);
  const grades = block.match(/Source grade counts:\s*([^\n]+)/i);
  if (trusted) health.trusted = cleanText(trusted[1]);
  if (ratio) health.verifiedClaimRatio = cleanText(ratio[1]);
  if (unsupported) health.unsupportedFindingCount = cleanText(unsupported[1]);
  if (grades) health.gradeCounts = cleanText(grades[1]);
  return health;
}

function parseEvidenceSources(block: string): EvidenceSource[] {
  const sourceStart = block.search(/###\s*Sources/i);
  const sourceBlock = sourceStart >= 0 ? block.slice(sourceStart) : block;
  const lines = sourceBlock.split("\n");
  const sources: EvidenceSource[] = [];
  let current: EvidenceSource | null = null;

  for (const rawLine of lines) {
    const line = rawLine.trim();
    const sourceMatch = line.match(/^-\s+`([^`]+)`\s*(.*)$/);
    if (sourceMatch) {
      if (current) sources.push(current);
      const id = cleanText(sourceMatch[1]);
      const title = cleanText(sourceMatch[2]) || id;
      const provider = inferProvider(id);
      current = {
        id,
        provider,
        providerLabel: PROVIDER_LABELS[provider] || titleCase(provider),
        title,
      };
      continue;
    }

    if (!current) continue;
    const fieldMatch = line.match(/^-\s+([^:]+):\s*(.*)$/);
    if (!fieldMatch) continue;
    const key = fieldMatch[1].trim().toLowerCase();
    const value = cleanText(fieldMatch[2]);
    if (key === "url") current.url = value;
    if (key === "grade") current.grade = value;
    if (key === "provenance") current.provenance = value;
    if (key === "quote") current.quote = value;
    if (key === "access status" || key === "access_status" || key === "source access status") {
      current.accessStatus = normalizeAccessStatus(value);
    }
  }

  if (current) sources.push(current);
  return sources;
}

function inferProvider(value: string): string {
  const clean = value.trim().toLowerCase();
  if (!clean) return "source";
  if (clean.startsWith("vault-")) return "vault";
  if (clean.startsWith("insight_forge-")) return "insight_forge";
  if (clean.startsWith("mempalace:")) return "mempalace";
  const prefix = clean.split(":")[0]?.replace(/[^a-z0-9_ -]/g, "").trim();
  return prefix || "source";
}

function titleCase(value: string): string {
  return value
    .split(/[_\s-]+/)
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

function cleanText(value: string): string {
  return value
    .replace(/<[^>]+>/g, "")
    .replace(/\s+/g, " ")
    .trim();
}
