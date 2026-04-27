"""MuchaNipo serve runtime — JSON-line event protocol for native shell."""

from .events import Action, Event, emit, parse_action

__all__ = ["Action", "Event", "emit", "parse_action"]
