import { useMemo, useState } from "react";
import {
  exportAnnotations,
  exportLinkedDocAnnotations,
  parseMarkdownToBlocks,
  wrapFeedbackForAgent,
} from "../plannotator-port/parser";
import {
  AnnotationType,
  type Annotation,
  type Block as PlannotatorBlock,
} from "../plannotator-port/types";

export interface PlanReviewEditValues {
  oneLine: string;
  resolution: string;
  targetUser: string;
  scenario: string;
  deliverable: string;
  successMetrics: string;
  flowStart: string;
  flowQuestionnaire: string;
  flowOutput: string;
}

export interface PlanReviewEditState {
  original: PlanReviewEditValues;
  current: PlanReviewEditValues;
}

type PlanReviewFieldKey = keyof PlanReviewEditValues;
type PlanDocKey = "prd" | "features" | "flow";

interface PlanReviewPromptLike {
  gate: string;
  payload?: Record<string, unknown>;
}

interface PlanBlock {
  id: string;
  doc: PlanDocKey;
  blockType: "heading" | "paragraph" | "list-item";
  key: PlanReviewFieldKey;
  label: string;
  target: string;
  startLine: number;
  originalText: string;
  currentText: string;
  helper: string;
}

interface TargetSpec {
  key: PlanReviewFieldKey;
  target: string;
  doc: PlanDocKey;
  blockType: PlanBlock["blockType"];
  label: string;
  helper: string;
}

const TARGETS: TargetSpec[] = [
  {
    key: "oneLine",
    target: "planning_prd.overview.one_line",
    doc: "prd",
    blockType: "heading",
    label: "PRD overview",
    helper: "01_PRD.md / overview.one_line",
  },
  {
    key: "resolution",
    target: "planning_prd.core_value.resolution",
    doc: "prd",
    blockType: "paragraph",
    label: "Core value",
    helper: "01_PRD.md / core_value.resolution",
  },
  {
    key: "successMetrics",
    target: "planning_prd.success_metrics",
    doc: "prd",
    blockType: "list-item",
    label: "Success metrics",
    helper: "01_PRD.md / success_metrics",
  },
  {
    key: "targetUser",
    target: "planning_prd.target_scenarios.0.user_group",
    doc: "features",
    blockType: "paragraph",
    label: "Target user",
    helper: "02_FEATURES.md / target_scenarios[0].user_group",
  },
  {
    key: "deliverable",
    target: "feature_hierarchy.0.features.0.name",
    doc: "features",
    blockType: "heading",
    label: "Feature seed",
    helper: "02_FEATURES.md / feature_hierarchy[0].features[0].name",
  },
  {
    key: "scenario",
    target: "planning_prd.target_scenarios.0.scenario",
    doc: "features",
    blockType: "paragraph",
    label: "Scenario",
    helper: "02_FEATURES.md / target_scenarios[0].scenario",
  },
  {
    key: "flowStart",
    target: "user_flow.nodes.start.label",
    doc: "flow",
    blockType: "list-item",
    label: "Start",
    helper: "03_USER_FLOW.md / nodes.start.label",
  },
  {
    key: "flowQuestionnaire",
    target: "user_flow.nodes.questionnaire.label",
    doc: "flow",
    blockType: "list-item",
    label: "Interview",
    helper: "03_USER_FLOW.md / nodes.questionnaire.label",
  },
  {
    key: "flowOutput",
    target: "user_flow.nodes.output.label",
    doc: "flow",
    blockType: "list-item",
    label: "Output",
    helper: "03_USER_FLOW.md / nodes.output.label",
  },
];

const DOCS: { key: PlanDocKey; file: string; label: string }[] = [
  { key: "prd", file: "01_PRD.md", label: "PRD" },
  { key: "features", file: "02_FEATURES.md", label: "Features" },
  { key: "flow", file: "03_USER_FLOW.md", label: "User flow" },
];

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

function stringValue(value: unknown): string {
  return typeof value === "string" ? value : value == null ? "" : String(value);
}

function firstRecord(value: unknown): Record<string, unknown> {
  return Array.isArray(value) ? asRecord(value[0]) : {};
}

function nodeLabel(nodes: unknown, nodeId: string, fallback: string): string {
  if (!Array.isArray(nodes)) return fallback;
  const node = nodes.find((item) => asRecord(item).id === nodeId);
  const record = asRecord(node);
  return stringValue(record.label) || fallback;
}

function buildBlocks(state: PlanReviewEditState): PlanBlock[] {
  return TARGETS.map((spec, index) => ({
    id: `block-${index}`,
    doc: spec.doc,
    blockType: spec.blockType,
    key: spec.key,
    label: spec.label,
    target: spec.target,
    startLine: index + 1,
    originalText: state.original[spec.key],
    currentText: state.current[spec.key],
    helper: spec.helper,
  }));
}

function updatePlanReviewField(
  state: PlanReviewEditState,
  key: PlanReviewFieldKey,
  value: string,
): PlanReviewEditState {
  return {
    ...state,
    current: {
      ...state.current,
      [key]: value,
    },
  };
}

function annotationHeading(block: PlanBlock): string {
  if (block.blockType === "heading") return "Change heading";
  if (block.blockType === "list-item") return "Change list item";
  return "Change paragraph";
}

function toPlannotatorBlocks(blocks: PlanBlock[]): PlannotatorBlock[] {
  return blocks.map((block, index) => ({
    id: block.id,
    type: block.blockType,
    content: block.originalText,
    level: block.blockType === "heading" ? 3 : 0,
    order: index + 1,
    startLine: block.startLine,
  }));
}

function toPlannotatorAnnotation(block: PlanBlock): Annotation {
  return {
    id: `annotation-${block.id}`,
    blockId: block.id,
    startOffset: 0,
    endOffset: block.originalText.length,
    type: AnnotationType.COMMENT,
    text: block.currentText.trim(),
    originalText: block.originalText,
    createdA: 0,
    author: "Muchanipo",
    source: "plannotator-inline-port",
  };
}

function blocksToMarkdown(blocks: PlanBlock[]): string {
  const lines: string[] = ["# Muchanipo Plan Review", ""];
  DOCS.forEach((doc) => {
    lines.push(`## ${doc.file}`, "");
    blocks
      .filter((block) => block.doc === doc.key)
      .forEach((block) => {
        lines.push(`### ${block.label}`, "", block.currentText.trim() || "(empty)", "");
      });
  });
  return lines.join("\n");
}

function exportPlanFeedback(blocks: PlanBlock[]): string {
  const changed = blocks.filter(
    (block) => block.currentText.trim() !== block.originalText.trim(),
  );
  if (changed.length === 0) return "No changes detected.";
  const annotations = changed.map(toPlannotatorAnnotation);
  const output = exportAnnotations(
    toPlannotatorBlocks(blocks),
    annotations,
    [],
    "Plan Feedback",
    "plan",
    { sourceConverted: true },
  );
  const linkedDocs = new Map(
    DOCS.map((doc) => {
      const docBlocks = blocks.filter((block) => block.doc === doc.key);
      const docAnnotations = changed
        .filter((block) => block.doc === doc.key)
        .map(toPlannotatorAnnotation);
      return [
        doc.file,
        {
          annotations: docAnnotations,
          globalAttachments: [],
          blocks: toPlannotatorBlocks(docBlocks),
          isConverted: true,
        },
      ];
    }),
  );
  const linkedOutput = exportLinkedDocAnnotations(linkedDocs);
  const targetIndex = changed
    .map((block) => `Target: \`${block.target}\`\n${annotationHeading(block)}`)
    .join("\n\n");
  return wrapFeedbackForAgent(`${output}\n${linkedOutput}\n${targetIndex}`);
}

export function normalizePlanReviewEditState(
  prompt: PlanReviewPromptLike,
): PlanReviewEditState | null {
  if (prompt.gate !== "plan" || !prompt.payload) return null;
  const editablePlan = asRecord(prompt.payload.editable_plan);
  const summary = asRecord(editablePlan.editable_summary);
  const planningPrd = asRecord(editablePlan.planning_prd);
  const overview = asRecord(planningPrd.overview);
  const coreValue = asRecord(planningPrd.core_value);
  const firstScenario = firstRecord(planningPrd.target_scenarios);
  const firstRequirement = firstRecord(editablePlan.feature_hierarchy);
  const firstFeature = firstRecord(firstRequirement.features);
  const userFlow = asRecord(editablePlan.user_flow);
  const nodes = userFlow.nodes;
  const successMetrics = Array.isArray(planningPrd.success_metrics)
    ? planningPrd.success_metrics.map((item) => stringValue(item)).filter(Boolean).join("\n")
    : "";
  const values: PlanReviewEditValues = {
    oneLine: stringValue(overview.one_line || summary.research_question),
    resolution: stringValue(coreValue.resolution || summary.purpose),
    targetUser: stringValue(firstScenario.user_group),
    scenario: stringValue(firstScenario.scenario || summary.context),
    deliverable: stringValue(firstFeature.name || summary.deliverable_type),
    successMetrics: successMetrics || stringValue(summary.quality_bar),
    flowStart: nodeLabel(nodes, "start", "아이디어 입력"),
    flowQuestionnaire: nodeLabel(nodes, "questionnaire", "기획 질문지 답변"),
    flowOutput: nodeLabel(nodes, "output", stringValue(summary.deliverable_type) || "결과물"),
  };
  if (!values.oneLine && !values.resolution && !values.scenario && !values.deliverable) {
    return null;
  }
  return { original: values, current: values };
}

export function planReviewAnnotations(
  state: PlanReviewEditState | null,
): Record<string, unknown>[] {
  if (!state) return [];
  const blocks = buildBlocks(state);
  return blocks
    .filter((block) => block.currentText.trim() !== block.originalText.trim())
    .map((block) => ({
      type: "edit",
      plannotator_type: "COMMENT",
      source: "plannotator-inline-port",
      blockId: block.id,
      target: block.target,
      replacement: block.currentText.trim(),
      text: block.currentText.trim(),
      originalText: block.originalText,
      selectedText: block.originalText,
      startOffset: 0,
      endOffset: block.originalText.length,
      lineLabel: `line ${block.startLine}`,
      document: DOCS.find((doc) => doc.key === block.doc)?.file,
      instruction: "Apply this Plannotator inline plan annotation before targeting.",
    }));
}

interface PlannotatorPlanEditorProps {
  state: PlanReviewEditState;
  onChange: (next: PlanReviewEditState) => void;
  editCount: number;
}

export function PlannotatorPlanEditor({
  state,
  onChange,
  editCount,
}: PlannotatorPlanEditorProps) {
  const [activeDoc, setActiveDoc] = useState<PlanDocKey>("prd");
  const blocks = useMemo(() => buildBlocks(state), [state]);
  const activeBlocks = blocks.filter((block) => block.doc === activeDoc);
  const annotations = useMemo(() => planReviewAnnotations(state), [state]);
  const feedback = useMemo(() => exportPlanFeedback(blocks), [blocks]);
  const parsedPreviewBlocks = useMemo(() => parseMarkdownToBlocks(blocksToMarkdown(blocks)), [blocks]);
  const activeDocMeta = DOCS.find((doc) => doc.key === activeDoc) ?? DOCS[0];

  return (
    <div className="mb-4 overflow-hidden rounded-lg border border-white/10 bg-black/20">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-white/10 px-3 py-2">
        <div className="min-w-0">
          <p className="text-[11px] font-semibold uppercase tracking-wider text-amber-100">
            Plannotator · embedded plan editor
          </p>
          <p className="mt-0.5 truncate font-mono text-[10px] text-tertiary">
            parser blocks {parsedPreviewBlocks.length} · packages/ui/utils/parser.ts
          </p>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          {editCount > 0 && (
            <span className="rounded-full border border-amber-400/20 px-2 py-0.5 text-[10px] text-amber-100">
              {editCount} edits
            </span>
          )}
          <button
            type="button"
            onClick={() => onChange({ ...state, current: state.original })}
            className="rounded-full border border-white/10 px-2.5 py-1 text-[10px] text-secondary transition hover:bg-white/5 hover:text-white"
          >
            원본 복원
          </button>
        </div>
      </div>

      <div className="grid gap-0 lg:grid-cols-[170px_minmax(0,1fr)_280px]">
        <div className="border-b border-white/10 p-2 lg:border-b-0 lg:border-r">
          <div className="grid grid-cols-3 gap-1 lg:grid-cols-1">
            {DOCS.map((doc) => {
              const docEditCount = blocks.filter(
                (block) =>
                  block.doc === doc.key &&
                  block.currentText.trim() !== block.originalText.trim(),
              ).length;
              return (
                <button
                  key={doc.key}
                  type="button"
                  onClick={() => setActiveDoc(doc.key)}
                  className={`min-h-11 rounded-md border px-2 py-2 text-left transition ${
                    activeDoc === doc.key
                      ? "border-amber-300/40 bg-amber-300/10 text-white"
                      : "border-white/10 text-secondary hover:bg-white/5 hover:text-white"
                  }`}
                >
                  <span className="block text-xs font-medium">{doc.label}</span>
                  <span className="mt-0.5 block truncate font-mono text-[10px] text-tertiary">
                    {doc.file}
                  </span>
                  {docEditCount > 0 && (
                    <span className="mt-1 inline-block rounded-full bg-amber-300/10 px-1.5 py-0.5 text-[10px] text-amber-100">
                      {docEditCount}
                    </span>
                  )}
                </button>
              );
            })}
          </div>
        </div>

        <div className="min-w-0 border-b border-white/10 p-3 lg:border-b-0 lg:border-r">
          <div className="mb-3 flex items-center justify-between gap-3">
            <div className="min-w-0">
              <p className="font-mono text-[10px] text-tertiary">{activeDocMeta.file}</p>
              <h3 className="mt-0.5 truncate text-sm font-medium text-white">
                {activeDocMeta.label}
              </h3>
            </div>
            <span className="shrink-0 rounded-full border border-white/10 px-2 py-0.5 text-[10px] text-secondary">
              annotation mode
            </span>
          </div>

          <div className="space-y-3">
            {activeBlocks.map((block) => {
              const changed = block.currentText.trim() !== block.originalText.trim();
              return (
                <label
                  key={block.id}
                  className={`block rounded-lg border p-3 transition ${
                    changed
                      ? "border-amber-300/40 bg-amber-300/5"
                      : "border-white/10 bg-black/20"
                  }`}
                >
                  <span className="mb-2 flex flex-wrap items-center justify-between gap-2">
                    <span className="text-xs font-medium text-white">{block.label}</span>
                    <span className="font-mono text-[10px] text-tertiary">
                      {block.id} · line {block.startLine}
                    </span>
                  </span>
                  <textarea
                    value={block.currentText}
                    onChange={(event) =>
                      onChange(updatePlanReviewField(state, block.key, event.target.value))
                    }
                    className="min-h-24 w-full resize-y rounded-md border border-white/10 bg-black/30 px-3 py-2 text-sm leading-relaxed text-white outline-none transition focus:border-amber-300/50"
                  />
                  <span className="mt-2 block truncate font-mono text-[10px] text-tertiary">
                    {block.helper}
                  </span>
                </label>
              );
            })}
          </div>
        </div>

        <div className="min-w-0 p-3">
          <p className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-amber-100">
            Annotation panel
          </p>
          <div className="max-h-64 overflow-auto rounded-md border border-white/10 bg-black/20">
            {annotations.length === 0 ? (
              <p className="px-3 py-3 text-sm text-secondary">변경 없음</p>
            ) : (
              annotations.map((annotation) => (
                <div
                  key={String(annotation.target)}
                  className="border-b border-white/5 px-3 py-2 last:border-b-0"
                >
                  <p className="font-mono text-[10px] text-amber-100">
                    {String(annotation.document)} · {String(annotation.lineLabel)}
                  </p>
                  <p className="mt-1 font-mono text-[10px] text-tertiary">
                    {String(annotation.target)}
                  </p>
                  <p className="mt-1 whitespace-pre-wrap break-words text-sm text-white">
                    {String(annotation.replacement)}
                  </p>
                </div>
              ))
            )}
          </div>

          <p className="mb-2 mt-3 text-[11px] font-semibold uppercase tracking-wider text-amber-100">
            Agent feedback export
          </p>
          <pre className="max-h-56 overflow-auto whitespace-pre-wrap break-words rounded-md border border-white/10 bg-black/20 px-3 py-2 text-[11px] leading-relaxed text-secondary">
            {feedback}
          </pre>
        </div>
      </div>
    </div>
  );
}
