# show-me-the-prd Upstream Pin

This directory vendors the prompt/runtime contract for GPTaku
`show-me-the-prd` so Muchanipo Stage 1 can be audited against source material
instead of a decorative reference claim.

- Upstream repository: https://github.com/fivetaku/show-me-the-prd
- Upstream commit: `7b22b070a685115a8687ea95fb95d398e4daf043`
- Marketplace repository: https://github.com/fivetaku/gptaku_plugins
- Marketplace submodule commit: `7b22b070a685115a8687ea95fb95d398e4daf043`
- License declared by upstream README and `.claude-plugin/plugin.json`: MIT

Vendored source paths:

- `README.md`
- `README.ko.md`
- `CHANGELOG.md`
- `.claude-plugin/plugin.json`
- `commands/show-me-the-prd.md`
- `skills/show-me-the-prd/SKILL.md`
- `skills/show-me-the-prd/references/document-templates.md`
- `skills/show-me-the-prd/references/interview-guide.md`
- `skills/show-me-the-prd/references/research-strategy.md`

Do not mark Stage 1 GPTaku parity as ready unless this pin remains present and
the local runtime adapter continues to expose the upstream workflow invariants:
dynamic unclear-item questioning, research batches between interview turns,
feature/MVP choice, data-model confirmation, phase confirmation, stack/auth
choice, and the four document outputs.
