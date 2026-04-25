"""Dream cycle automation — vault scan + episodic dedup + cluster summary.

Importing :mod:`src.dream.dream_runner` directly avoids the runtime warning
that would otherwise appear when invoking ``python3 -m src.dream.dream_runner``
through ``tools/dream_cycle.sh``.
"""

__all__ = ["DreamRunner", "DreamRunReport", "run_dream_cycle"]
