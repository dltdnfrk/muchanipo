"""Consensus helpers."""
from __future__ import annotations

def summarize_consensus(responses: list[dict]) -> str:
    return "initial council round complete" if responses else "no responses"
