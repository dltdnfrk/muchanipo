# Plannotator Upstream Pin

This directory vendors Plannotator source so Muchanipo stage 2/4 plan-review
claims can be audited against real upstream code rather than a decorative
reference.

- Upstream repository: https://github.com/backnotprop/plannotator
- Vendored commit: `6324a0c859f06030b47d71c02b7c6fed09fa0b92`
- License: `MIT OR Apache-2.0`
- Retrieval date: 2026-05-02

Runtime integration:

- `app/muchanipo-tauri/src/plannotator-port/` copies Plannotator's
  browser-safe `types.ts`, `parser.ts`, and feedback template into the Tauri
  app source tree.
- `app/muchanipo-tauri/src/components/PlannotatorPlanEditor.tsx` embeds a
  local Tauri plan editor surface around that copied block/annotation/export
  contract.
- The port does not open a separate web page or external Plannotator service for
  the plan gate. It emits Plannotator-style block annotations directly through
  the Muchanipo HITL action channel.

Primary vendored source surfaces used by the port:

- `packages/editor/App.tsx`
- `packages/ui/components/Viewer.tsx`
- `packages/ui/components/AnnotationPanel.tsx`
- `packages/ui/components/AnnotationToolstrip.tsx`
- `packages/ui/utils/parser.ts`
- `packages/ui/types.ts`
- `packages/shared/feedback-templates.ts`
