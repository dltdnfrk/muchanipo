"""Academic research API clients."""
from __future__ import annotations

from .openalex import OpenAlexClient
from .semantic_scholar import SemanticScholarClient

__all__ = ["OpenAlexClient", "SemanticScholarClient"]
