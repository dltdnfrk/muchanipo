"""Top-level alias so `python3 -m muchanipo serve` works without install.

The real implementation lives in `src.muchanipo`. This shim lets the Swift
PythonRunner invoke the canonical command name from the assignment.
"""

from src.muchanipo import Action, Event, emit, parse_action  # noqa: F401
