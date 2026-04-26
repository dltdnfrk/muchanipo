"""Prompt builders for debate agents."""
from __future__ import annotations


def generic_agent_prompt(name: str, role: str) -> str:
    return f"You are {name}, acting as {role}. Review the report, cite evidence ids, and produce next actions."
