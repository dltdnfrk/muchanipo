## Variant: Studio-led split with Browser preview

### Design stance
Keep Studio as the primary thinking surface while making Browser visibly locked/queued until the graph is ready.

### Key choices
- Layout: left navigation, central Deep Interview, right Unknowns + Browser preview, bottom execution rail.
- Typography: system stack, restrained sizes, stable headings; no animated/rotating headline copy.
- Color: dark tool workspace with one warm accent for the current unknown.
- Interaction model: answer creates a new turn and updates ontology; it does not mutate prior text in place.

### Copy guardrails
- Use stable product nouns: Studio, Browser, Goal, Unknown, Evidence, Report.
- Avoid decorative AI language in visible chrome.
- Keep technical routing/model details out of primary UI unless the user opens logs/settings.
- Browser is visible as a preview/locked execution area so the split is obvious without overwhelming Studio.

### Trade-offs
- Strong at: showing the mental model and preventing “one long pipeline” feel.
- Weak at: Browser is still preview-only; a full Browser screen variant should be sketched/implemented next.

### Best for
Power users who need to see what is unresolved before letting the system execute research and report generation.
