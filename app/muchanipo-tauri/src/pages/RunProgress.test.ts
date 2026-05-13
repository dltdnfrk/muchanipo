import { describe, expect, it } from "vitest";
import {
  deriveBackendSignalStatus,
  eventFeedsCurrentSessionEvidenceLedger,
  normalizeImportedKnowledgeRefs,
  normalizeResearchQualityReadyActivity,
  normalizeResearchActivity,
  parseEventBoolean,
  researchQualityDetailChips,
  researchActivityCopy,
  researchPlanDisplayRows,
  researchPlanSummaryChips,
  researchProgressStage,
  updateResearchContractFromEvent,
} from "./RunProgress";

describe("deriveBackendSignalStatus", () => {
  it("shows backend signal when runtime status matches the current app run", () => {
    expect(
      deriveBackendSignalStatus({
        runId: "run-current",
        runtimeRunId: "run-current",
        runtimeHeartbeatStage: "interview",
        hasVisibleBackendHeartbeat: false,
      }),
    ).toBe("Backend run signals observed");
  });

  it("shows backend signal from visible heartbeat when runtime polling has not refreshed app_run_id yet", () => {
    expect(
      deriveBackendSignalStatus({
        runId: "run-current",
        runtimeRunId: undefined,
        runtimeHeartbeatStage: "interview",
        hasVisibleBackendHeartbeat: true,
      }),
    ).toBe("Backend run signals observed");
  });

  it("waits for backend signal for a stale runtime without visible heartbeat", () => {
    expect(
      deriveBackendSignalStatus({
        runId: "run-current",
        runtimeRunId: "run-old",
        runtimeHeartbeatStage: "interview",
        hasVisibleBackendHeartbeat: false,
      }),
    ).toBe("Waiting for live backend signal");
  });
});

describe("parseEventBoolean", () => {
  it("does not treat the string false as truthy", () => {
    expect(parseEventBoolean(false)).toBe(false);
    expect(parseEventBoolean("false")).toBe(false);
    expect(parseEventBoolean("0")).toBe(false);
    expect(parseEventBoolean("no")).toBe(false);
    expect(parseEventBoolean(true)).toBe(true);
    expect(parseEventBoolean("true")).toBe(true);
    expect(parseEventBoolean("1")).toBe(true);
    expect(parseEventBoolean("yes")).toBe(true);
  });
});

describe("research quality gate progress", () => {
  it("keeps source-audit and claim-evidence gates visible instead of dropping them", () => {
    const sourceAudit = normalizeResearchActivity({
      event: "research_progress",
      stage: "quality_gate",
      status: "source_audit_gate",
      message: "source audit passed",
      reason: "4/4 facets covered",
      accepted_source_count: 7,
      rejected_source_count: 2,
      gap_count: 0,
      passed: true,
    });
    const claimEvidence = normalizeResearchActivity({
      event: "research_progress",
      stage: "quality_gate",
      status: "claim_evidence_gate",
      message: "claim evidence matrix passed",
      supported_count: 5,
      partial_count: 1,
      unsupported_count: 0,
      supported_ratio: 0.833,
      passed: true,
    });
    const benchmark = normalizeResearchActivity({
      event: "research_progress",
      stage: "quality_gate",
      status: "max_plus_benchmark_scored",
      message: "B-1 fixture scored",
      benchmark_id: "muchanipo-deep-research-max-plus-b1",
      decision: "keep",
      metrics: {
        source_authority_score: 0.9,
        weak_source_penalty: 0,
        expected_claim_recall: 0.67,
        evidence_quote_coverage: 1,
        claim_traceability: 0.8,
      },
    });

    expect(sourceAudit?.status).toBe("source_audit_gate");
    expect(sourceAudit?.message).toBe("source audit passed");
    expect(sourceAudit?.reason).toBe("4/4 facets covered");
    expect(sourceAudit?.acceptedSourceCount).toBe(7);
    expect(sourceAudit?.rejectedSourceCount).toBe(2);
    expect(sourceAudit?.gapCount).toBe(0);
    expect(sourceAudit?.passed).toBe(true);
    expect(claimEvidence?.status).toBe("claim_evidence_gate");
    expect(claimEvidence?.supportedClaimCount).toBe(5);
    expect(claimEvidence?.partialClaimCount).toBe(1);
    expect(claimEvidence?.unsupportedClaimCount).toBe(0);
    expect(claimEvidence?.supportedRatio).toBe(0.833);
    expect(benchmark?.status).toBe("max_plus_benchmark_scored");
    expect(benchmark?.benchmarkId).toBe("muchanipo-deep-research-max-plus-b1");
    expect(benchmark?.decision).toBe("keep");
    expect(benchmark?.metrics).toEqual({
      source_authority_score: 0.9,
      weak_source_penalty: 0,
      expected_claim_recall: 0.67,
      evidence_quote_coverage: 1,
      claim_traceability: 0.8,
    });
    expect(researchActivityCopy(sourceAudit!).label).toBe("출처 감사 gate");
    expect(researchActivityCopy(claimEvidence!).label).toBe("Claim 근거 gate");
    expect(researchActivityCopy(benchmark!).label).toBe("Benchmark gate");
    expect(researchActivityCopy(sourceAudit!).signal).toContain("rejected sources 2");
    expect(researchActivityCopy(claimEvidence!).signal).toContain("unsupported claims 0");
    expect(researchActivityCopy(benchmark!).signal).toContain("decision keep");
    expect(researchQualityDetailChips(benchmark!)).toContain("decision keep");
  });

  it("normalizes research_plan_ready with query rationale metadata before search events", () => {
    const planReady = normalizeResearchActivity({
      event: "research_progress",
      stage: "research",
      status: "research_plan_ready",
      query_count: 2,
      queries: ["urban heat island official statistics", "urban heat island counter evidence"],
      query_routes: [
        {
          query: "urban heat island official statistics",
          facet_id: "topic",
          purpose: "find canonical official/statistical sources",
          source_class: "official",
          intent: "find_primary",
          backend: "web",
          continue_reason: "prefer canonical government/statistics/standards pages over secondary summaries",
          authority_requirement: "official-statistics required",
          acceptance_rules: ["must cite primary statistics", "reject generic blog summaries"],
        },
      ],
    });

    expect(planReady?.status).toBe("research_plan_ready");
    expect(planReady?.queryCount).toBe(2);
    expect(planReady?.queries).toEqual([
      "urban heat island official statistics",
      "urban heat island counter evidence",
    ]);
    expect(planReady?.queryRoutes).toEqual([
      {
        query: "urban heat island official statistics",
        facetId: "topic",
        purpose: "find canonical official/statistical sources",
        sourceClass: "official",
        intent: "find_primary",
        backend: "web",
        continueReason: "prefer canonical government/statistics/standards pages over secondary summaries",
        authorityRequirement: "official-statistics required",
        acceptanceRules: ["must cite primary statistics", "reject generic blog summaries"],
      },
    ]);
    expect(researchActivityCopy(planReady!).label).toBe("Research plan ready");
    expect(researchProgressStage({ event: "research_progress", status: "research_plan_ready" }, planReady)).toBe("research");
  });

  it("builds a first-class research plan summary and preserves all long query rows with route rationale", () => {
    const planReady = normalizeResearchActivity({
      event: "research_progress",
      stage: "research",
      status: "research_plan_ready",
      query_count: 6,
      queries: [
        "topic anchor official statistics",
        "topic anchor peer reviewed mechanism evidence with an intentionally long query that should wrap safely instead of being truncated",
        "topic anchor counter evidence",
        "topic anchor patents",
        "topic anchor guidelines",
        "topic anchor market reports",
      ],
      topic_anchor: "topic anchor",
      query_routes: [
        {
          query: "topic anchor official statistics",
          facet_id: "topic",
          purpose: "canonical statistics",
          source_class: "official",
          intent: "find_primary",
          backend: "web",
          continue_reason: "official source required before synthesis",
          authority_requirement: "government/statistics source",
          acceptance_rules: "primary source with locator; reject overview pages",
        },
        {
          query: "topic anchor peer reviewed mechanism evidence with an intentionally long query that should wrap safely instead of being truncated",
          facet_id: "mechanism",
          purpose: "peer-reviewed mechanism",
          source_class: "scholarly",
          intent: "mechanism",
          backend: "semantic_scholar",
        },
      ],
    });

    const rows = researchPlanDisplayRows(planReady!);
    expect(rows).toHaveLength(6);
    expect(rows[0].query).toBe("topic anchor official statistics");
    expect(rows[0].routeDetails).toContain("facet topic");
    expect(rows[0].routeDetails).toContain("purpose canonical statistics");
    expect(rows[0].routeDetails).toContain("source class official");
    expect(rows[0].routeDetails).toContain("intent find_primary");
    expect(rows[0].routeDetails).toContain("backend web");
    expect(rows[0].continueReason).toBe("official source required before synthesis");
    expect(rows[0].authorityRequirement).toBe("government/statistics source");
    expect(rows[0].acceptanceRules).toEqual(["primary source with locator; reject overview pages"]);
    expect(rows[5].query).toBe("topic anchor market reports");

    expect(researchPlanSummaryChips(planReady!)).toEqual([
      "queries 6",
      "source classes official, scholarly",
      "backends web, semantic_scholar",
      "topic anchor topic anchor",
    ]);
  });

  it("falls back to raw planned queries when query_routes is missing or partial", () => {
    const missingRoutes = normalizeResearchActivity({
      event: "research_progress",
      status: "research_plan_ready",
      query_count: 3,
      queries: ["raw query one", "raw query two", "raw query three"],
    });
    const partialRoutes = normalizeResearchActivity({
      event: "research_progress",
      status: "research_plan_ready",
      queries: ["routed query", "raw fallback query"],
      query_routes: [{ query: "routed query", source_class: "official", backend: "web" }],
    });

    expect(researchPlanDisplayRows(missingRoutes!).map((row) => row.query)).toEqual([
      "raw query one",
      "raw query two",
      "raw query three",
    ]);
    expect(researchPlanDisplayRows(partialRoutes!)).toEqual([
      expect.objectContaining({ query: "routed query", routeDetails: ["source class official", "backend web"] }),
      expect.objectContaining({ query: "raw fallback query", routeDetails: [] }),
    ]);
  });

  it("normalizes per-search route metadata when search progress already emits it", () => {
    const searching = normalizeResearchActivity({
      event: "research_progress",
      status: "searching",
      query: "topic anchor official statistics",
      query_index: 1,
      query_count: 2,
      facet_id: "topic",
      purpose: "canonical statistics",
      source_class: "official",
      intent: "find_primary",
      backend: "web",
      continue_reason: "official source required before synthesis",
    });

    expect(searching).toEqual(expect.objectContaining({
      status: "searching",
      query: "topic anchor official statistics",
      facetId: "topic",
      purpose: "canonical statistics",
      sourceClass: "official",
      intent: "find_primary",
      backend: "web",
      continueReason: "official source required before synthesis",
    }));
  });

  it("routes quality-gate research progress to the evidence stage", () => {
    expect(researchProgressStage({ event: "research_progress", stage: "quality_gate", status: "source_audit_gate" })).toBe(
      "evidence",
    );
    expect(researchProgressStage({ event: "research_progress", status: "max_plus_benchmark_scored" })).toBe("evidence");
    expect(researchProgressStage({ event: "research_quality_ready", status: "ready_before_council" })).toBe("evidence");
    expect(researchProgressStage({ event: "research_progress", status: "searching" })).toBe("research");
  });

  it("normalizes research_quality_ready as intentional quality-first completion with nested metrics", () => {
    const ready = normalizeResearchQualityReadyActivity({
      event: "research_quality_ready",
      stage: "quality_gate",
      status: "ready_before_council",
      source_audit_summary: {
        passed: true,
        accepted_source_count: 8,
        rejected_source_count: 3,
        gap_count: 0,
      },
      claim_evidence_matrix_summary: {
        supported_count: 6,
        partial_count: 1,
        unsupported_count: 0,
        supported_ratio: 0.857,
      },
      max_plus_benchmark_decision: "keep",
      max_plus_benchmark_metrics: {
        expected_claim_recall: 0.67,
        claim_traceability: 0.8,
        weak_source_penalty: 0.05,
      },
    });

    expect(ready?.status).toBe("research_quality_ready");
    expect(ready?.reason).toBe("ready_before_council");
    expect(ready?.acceptedSourceCount).toBe(8);
    expect(ready?.rejectedSourceCount).toBe(3);
    expect(ready?.unsupportedClaimCount).toBe(0);
    expect(ready?.decision).toBe("keep");
    expect(ready?.metrics?.claim_traceability).toBe(0.8);
    expect(researchActivityCopy(ready!).label).toBe("Research quality ready");
    expect(researchActivityCopy(ready!).signal).toContain("ready_before_council");
    expect(researchQualityDetailChips(ready!)).toEqual([
      "passed yes",
      "accepted sources 8",
      "rejected sources 3",
      "gaps 0",
      "supported claims 6",
      "partial claims 1",
      "unsupported claims 0",
      "supported ratio 86%",
      "decision keep",
    ]);
  });

  it("normalizes research-quality done events with JSON artifact summaries", () => {
    const ready = normalizeResearchQualityReadyActivity({
      event: "done",
      status: "research_quality_ready",
      research_quality_only: true,
      research_quality_stop: "before_council",
      artifacts: {
        source_audit_summary: JSON.stringify({
          passed: true,
          accepted_source_count: 4,
          rejected_source_count: 1,
          gap_count: 0,
        }),
        claim_evidence_matrix_summary: JSON.stringify({
          supported_count: 3,
          partial_count: 0,
          unsupported_count: 0,
          supported_ratio: 1,
        }),
        max_plus_benchmark_decision: "keep",
        max_plus_benchmark_metrics: JSON.stringify({
          expected_claim_recall: 1,
          claim_traceability: 1,
          weak_source_penalty: 0,
        }),
      },
    });

    expect(ready?.reason).toBe("before_council");
    expect(ready?.acceptedSourceCount).toBe(4);
    expect(ready?.partialClaimCount).toBe(0);
    expect(ready?.metrics?.weak_source_penalty).toBe(0);
    expect(researchActivityCopy(ready!).signal).toContain("research_quality_ready");
  });
});

describe("research contract ledger separation", () => {
  it("normalizes only explicit imported refs and keeps empty default as zero imports", () => {
    expect(normalizeImportedKnowledgeRefs(undefined)).toEqual([]);
    expect(normalizeImportedKnowledgeRefs([])).toEqual([]);
    expect(normalizeImportedKnowledgeRefs('["obsidian://wiki/a", " report:b "]')).toEqual([
      "obsidian://wiki/a",
      "report:b",
    ]);
  });

  it("tracks imported refs on the contract without feeding them into current-session evidence", () => {
    const started = updateResearchContractFromEvent(
      { importedKnowledgeRefs: [] },
      {
        event: "run_started",
        research_session_id: "research-current",
        app_run_id: "app-current",
        memory_policy: "no_implicit_cross_session_memory",
        imported_knowledge_refs: ["obsidian://wiki/old-run"],
      },
    );

    expect(started).toEqual({
      researchSessionId: "research-current",
      appRunId: "app-current",
      memoryPolicy: "no_implicit_cross_session_memory",
      importedKnowledgeRefs: ["obsidian://wiki/old-run"],
    });
    expect(eventFeedsCurrentSessionEvidenceLedger({
      event: "run_started",
      imported_knowledge_refs: ["obsidian://wiki/old-run"],
    })).toBe(false);
    expect(eventFeedsCurrentSessionEvidenceLedger({
      event: "research_progress",
      status: "source_found",
      source_title: "current session source",
    })).toBe(true);
  });
});
