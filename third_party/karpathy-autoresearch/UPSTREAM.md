# karpathy/autoresearch Upstream Snapshot

- Source: https://github.com/karpathy/autoresearch
- Pinned revision: `228791fb499afffb54b46200aca536f79142f117`
- Local snapshot date: 2026-05-03
- License declaration: upstream `README.md` says `MIT`.
- License boundary: the pinned upstream tree does not include a standalone
  `LICENSE` file in this local snapshot. Keep this notice with copied material
  and verify release packaging before external redistribution.

## Local Use

Muchanipo vendors the upstream source as implementation evidence and adapts the
runtime loop in `src/research/karpathy_autoresearch.py`.

The upstream ML target is:

- fixed context/runtime utilities in `prepare.py`;
- one mutable experiment file, `train.py`;
- `program.md` as the natural-language research-org program;
- fixed metric output in `results.tsv`;
- strict keep/discard based on metric improvement.

The Muchanipo adaptation keeps the loop mechanics but changes the experiment
surface from `train.py` to `ResearchPlan.queries`, and changes the fixed metric
from `val_bpb` to `source_grounding_gap_score`. It writes to ignored scratch
run directories instead of resetting the user's git worktree.
