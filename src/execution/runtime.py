"""Minimal execution runtime wrapper."""
from __future__ import annotations

from .models import ModelGateway


class ExecutionRuntime:
    def __init__(self, model_gateway: ModelGateway):
        self.model_gateway = model_gateway
