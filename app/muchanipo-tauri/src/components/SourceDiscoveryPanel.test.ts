import { describe, expect, it } from "vitest";
import {
  buildDiscoveredSourceMap,
  discoveryBreadth,
  displayAccessStatus,
} from "./SourceDiscoveryPanel";

describe("displayAccessStatus safe wording", () => {
  it("normalizes upstream access-status synonyms before display", () => {
    expect(displayAccessStatus("paywalled")).toBe("Restricted");
    expect(displayAccessStatus("login_required")).toBe("Restricted");
    expect(displayAccessStatus("open_access_copy")).toBe("Open access");
  });

  it("never returns blocked", () => {
    expect(displayAccessStatus("blocked")).not.toContain("blocked");
    expect(displayAccessStatus("blocked")).not.toContain("Blocked");
  });

  it("never returns found", () => {
    expect(displayAccessStatus("oa_copy_found")).not.toContain("found");
    expect(displayAccessStatus("oa_copy_found")).not.toContain("Found");
  });

  it("never returns copy", () => {
    expect(displayAccessStatus("oa_copy_found")).not.toContain("copy");
    expect(displayAccessStatus("oa_copy_found")).not.toContain("Copy");
  });

  it("never returns bypass-like language", () => {
    const allStatuses = [
      "full_text_available",
      "abstract_only",
      "oa_copy_found",
      "blocked",
      "alternative_evidence",
    ];
    const forbidden = ["bypass", "breach", "crack", "unlock", "hack", "circumvent", "paywall"];
    for (const status of allStatuses) {
      const label = displayAccessStatus(status);
      for (const word of forbidden) {
        expect(label.toLowerCase()).not.toContain(word);
      }
    }
  });

  it("uses neutral labels for all canonical statuses", () => {
    expect(displayAccessStatus("full_text_available")).toBe("Full text");
    expect(displayAccessStatus("abstract_only")).toBe("Abstract");
    expect(displayAccessStatus("oa_copy_found")).toBe("Open access");
    expect(displayAccessStatus("blocked")).toBe("Restricted");
    expect(displayAccessStatus("alternative_evidence")).toBe("Alternative");
  });

  it("falls back gracefully for unknown statuses", () => {
    expect(displayAccessStatus("unknown_status")).toBe("unknown status");
    expect(displayAccessStatus(undefined)).toBe("Not reported");
  });
});

describe("discoveryBreadth computation", () => {
  it("collects unique backends across sources", () => {
    const sources = [
      { key: "a", title: "A", status: "found" as const, firstSeenAt: 1, backends: ["openalex", "crossref"] },
      { key: "b", title: "B", status: "found" as const, firstSeenAt: 2, backends: ["openalex", "semantic_scholar"] },
      { key: "c", title: "C", status: "found" as const, firstSeenAt: 3 },
    ];
    const result = discoveryBreadth(sources);
    expect(result.backends).toEqual(["openalex", "crossref", "semantic_scholar"]);
  });

  it("collects unique queries across sources", () => {
    const sources = [
      { key: "a", title: "A", status: "found" as const, firstSeenAt: 1, query: "q1" },
      { key: "b", title: "B", status: "found" as const, firstSeenAt: 2, query: "q1" },
      { key: "c", title: "C", status: "found" as const, firstSeenAt: 3, query: "q2" },
    ];
    const result = discoveryBreadth(sources);
    expect(result.queries).toEqual(["q1", "q2"]);
  });

  it("returns empty arrays when no metadata present", () => {
    const result = discoveryBreadth([]);
    expect(result.backends).toEqual([]);
    expect(result.queries).toEqual([]);
  });
});

describe("buildDiscoveredSourceMap access status propagation", () => {
  it("carries access_status on source_found", () => {
    const map = buildDiscoveredSourceMap(new Map(), {
      status: "source_found",
      sourceTitle: "Paper",
      sourceUrl: "https://example.com",
      accessStatus: "open_access",
    });
    const source = map.get("https://example.com");
    expect(source).toBeDefined();
    expect(source!.accessStatus).toBe("open_access");
    expect(source!.status).toBe("found");
  });

  it("upgrades access_status on source_evaluated", () => {
    const initial = buildDiscoveredSourceMap(new Map(), {
      status: "source_found",
      sourceTitle: "Paper",
      sourceUrl: "https://example.com",
      accessStatus: "abstract_only",
    });
    const upgraded = buildDiscoveredSourceMap(initial, {
      status: "source_evaluated",
      sourceTitle: "Paper",
      sourceUrl: "https://example.com",
      accessStatus: "full_text_available",
      accepted: true,
    });
    const source = upgraded.get("https://example.com");
    expect(source!.accessStatus).toBe("full_text_available");
    expect(source!.status).toBe("accepted");
  });

  it("preserves existing access_status if new event lacks it", () => {
    const initial = buildDiscoveredSourceMap(new Map(), {
      status: "source_found",
      sourceTitle: "Paper",
      sourceUrl: "https://example.com",
      accessStatus: "oa_copy_found",
    });
    const next = buildDiscoveredSourceMap(initial, {
      status: "source_evaluated",
      sourceTitle: "Paper",
      sourceUrl: "https://example.com",
      accepted: false,
    });
    const source = next.get("https://example.com");
    expect(source!.accessStatus).toBe("oa_copy_found");
    expect(source!.status).toBe("rejected");
  });
});
