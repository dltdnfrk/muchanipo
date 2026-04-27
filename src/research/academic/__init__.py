"""Academic research API clients."""
from __future__ import annotations

from .arxiv import ArxivClient
from .core import CoreClient
from .crossref import CrossRefClient
from .openalex import OpenAlexClient
from .semantic_scholar import SemanticScholarClient

__all__ = ["ArxivClient", "CoreClient", "CrossRefClient", "OpenAlexClient", "SemanticScholarClient"]
