"""MECE Tree — Mutually Exclusive Collectively Exhaustive issue tree.

McKinsey 핵심 도구. 큰 질문을 sub-question으로 쪼개되:
- 하위 가지끼리 겹치지 않고 (mutually exclusive)
- 합치면 전체를 다룸 (collectively exhaustive)
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class MECENode:
    """1 issue node — sub-question 또는 hypothesis."""
    label: str
    rationale: str = ""
    children: List["MECENode"] = field(default_factory=list)
    is_leaf_hypothesis: bool = False  # True면 testable hypothesis

    def add_child(self, node: "MECENode") -> None:
        self.children.append(node)


@dataclass
class MECETree:
    """root question + MECE 분해 tree."""
    root_question: str
    root: MECENode

    def to_markdown(self) -> str:
        lines = [f"## MECE Issue Tree", "", f"**Root:** {self.root_question}", ""]
        lines += self._render_node(self.root, depth=0)
        return "\n".join(lines).rstrip()

    def _render_node(self, node: MECENode, depth: int) -> List[str]:
        indent = "  " * depth
        marker = "🎯" if node.is_leaf_hypothesis else "▸"
        lines = [f"{indent}- {marker} **{node.label}**"]
        if node.rationale:
            lines.append(f"{indent}  _{node.rationale}_")
        for child in node.children:
            lines += self._render_node(child, depth + 1)
        return lines

    def leaf_hypotheses(self) -> List[MECENode]:
        """Testable leaf nodes — council이 검증할 hypothesis 목록."""
        out: List[MECENode] = []
        self._collect_leaves(self.root, out)
        return out

    def _collect_leaves(self, node: MECENode, out: List[MECENode]) -> None:
        if node.is_leaf_hypothesis:
            out.append(node)
        for c in node.children:
            self._collect_leaves(c, out)
