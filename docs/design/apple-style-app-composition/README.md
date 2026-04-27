# Apple-style Muchanipo App Composition

This design snapshot captures the intended end-to-end Muchanipo desktop app experience before implementation in the Tauri React app.

## Flow

```text
Idea Intake
→ PRD-style Interview
→ AutoResearch
→ Evidence / Knowledge Graph
→ Persona Generation (mirofish agents)
→ Council Meeting
→ Streaming Report
→ CLI / Provider Settings
```

## Artifacts

- [`index.html`](./index.html) — static Apple-style product/app mockup.
- [`assets/hero-and-run-flow.png`](./assets/hero-and-run-flow.png) — hero plus in-app live run composition.
- [`assets/app-structure-tiles.png`](./assets/app-structure-tiles.png) — full app structure tiles.

## Implementation direction

Target app stack is **Tauri + React**, not a Swift-native app.

Suggested route structure:

```text
/          Home / Idea Intake / product hero
/run       Live pipeline run: interview → research → graph → personas → council → report
/settings CLI/provider/capability settings
/graph     Knowledge graph explorer
/council   Council transcript and persona rounds
/report    Final report viewer/export
```

Design principles:

- macOS/iPad-style glass navigation and high-contrast hero.
- Pipeline-first UI: users should always see where the run is in the lifecycle.
- Local-first and cost-visible provider controls.
- Backend events should drive live UI state rather than placeholder screens.
