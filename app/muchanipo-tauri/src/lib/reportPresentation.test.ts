import { describe, expect, it } from "vitest";
import {
  accessStatusLabel,
  evidenceSourcesFromRefs,
  normalizeAccessStatus,
  parseEvidenceIndex,
  type EvidenceAccessStatus,
} from "./reportPresentation";

describe("accessStatusLabel safe wording", () => {
  it("never returns blocked", () => {
    const label = accessStatusLabel("blocked");
    expect(label).not.toContain("blocked");
    expect(label).not.toContain("Blocked");
  });

  it("never returns found", () => {
    const label = accessStatusLabel("oa_copy_found");
    expect(label).not.toContain("found");
    expect(label).not.toContain("Found");
  });

  it("never returns copy", () => {
    const label = accessStatusLabel("oa_copy_found");
    expect(label).not.toContain("copy");
    expect(label).not.toContain("Copy");
  });

  it("uses neutral labels for all statuses", () => {
    expect(accessStatusLabel("full_text_available")).toBe("Full text");
    expect(accessStatusLabel("abstract_only")).toBe("Abstract");
    expect(accessStatusLabel("oa_copy_found")).toBe("Open access");
    expect(accessStatusLabel("blocked")).toBe("Restricted");
    expect(accessStatusLabel("alternative_evidence")).toBe("Alternative");
  });

  it("labels missing access status explicitly", () => {
    const labelFor = accessStatusLabel as (status?: EvidenceAccessStatus) => string;
    expect(labelFor()).toBe("Not reported");
  });

  it("never contains bypass-like language for any status", () => {
    const allStatuses: EvidenceAccessStatus[] = [
      "full_text_available",
      "abstract_only",
      "oa_copy_found",
      "blocked",
      "alternative_evidence",
    ];
    const forbidden = ["bypass", "breach", "crack", "unlock", "hack", "circumvent", "paywall"];
    for (const status of allStatuses) {
      const label = accessStatusLabel(status);
      for (const word of forbidden) {
        expect(label.toLowerCase()).not.toContain(word);
      }
    }
  });
});

describe("normalizeAccessStatus parsing", () => {
  it("maps paywalled input to blocked type internally", () => {
    expect(normalizeAccessStatus("paywalled")).toBe("blocked");
    expect(normalizeAccessStatus("login_required")).toBe("blocked");
    expect(normalizeAccessStatus("access_restricted")).toBe("blocked");
  });

  it("maps unpaywall_oa input to oa_copy_found type", () => {
    expect(normalizeAccessStatus("unpaywall_oa")).toBe("oa_copy_found");
    expect(normalizeAccessStatus("open_access_copy")).toBe("oa_copy_found");
  });

  it("returns undefined for unknown values", () => {
    expect(normalizeAccessStatus("unknown")).toBeUndefined();
    expect(normalizeAccessStatus("")).toBeUndefined();
    expect(normalizeAccessStatus(null)).toBeUndefined();
  });
});

describe("parseEvidenceIndex access_status from markdown", () => {
  it("parses access_status from Evidence Index markdown", () => {
    const md = `
## Evidence Index

### Evidence Health
- Trusted evidence: 2 / 2
- Verified claim ratio: 1.00
- Unsupported finding count: 0

### Sources
- \`openalex:W123\` Sample Paper
  - URL: https://example.com/paper
  - Grade: A
  - Provenance: openalex
  - Access status: open_access
  - Quote: sample quote

## Chapter 1: Intro
Some content.
`;
    const result = parseEvidenceIndex(md);
    expect(result.sources).toHaveLength(1);
    expect(result.sources[0].accessStatus).toBe("oa_copy_found");
  });

  it("parses blocked access_status from markdown", () => {
    const md = `
## Evidence Index
### Sources
- \`crossref:xyz\` Paywalled Paper
  - URL: https://doi.org/10.1/1
  - Grade: B
  - Provenance: crossref
  - Access status: blocked
`;
    const result = parseEvidenceIndex(md);
    expect(result.sources[0].accessStatus).toBe("blocked");
  });
});

describe("evidenceSourcesFromRefs safe wording", () => {
  it("carries access_status from refs without altering it", () => {
    const refs = [
      {
        id: "test:1",
        source_title: "Paper",
        access_status: "oa_copy_found",
      },
    ];
    const sources = evidenceSourcesFromRefs(refs);
    expect(sources).toHaveLength(1);
    expect(sources[0].accessStatus).toBe("oa_copy_found");
  });

  it("normalizes alternative access_status synonyms", () => {
    const refs = [
      { id: "t:1", source_title: "X", access_status: "paywalled" },
      { id: "t:2", source_title: "Y", access_status: "full_text" },
      { id: "t:3", source_title: "Z", access_status: "open_access_copy" },
    ];
    const sources = evidenceSourcesFromRefs(refs);
    expect(sources[0].accessStatus).toBe("blocked");
    expect(sources[1].accessStatus).toBe("full_text_available");
    expect(sources[2].accessStatus).toBe("oa_copy_found");
  });
});
