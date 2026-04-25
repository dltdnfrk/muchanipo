"""Visual wire renderer for framework outputs in markdown reports."""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Tuple


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return "<br>".join(_text(item) for item in value if _text(item))
    if isinstance(value, dict):
        parts = []
        for key, item in value.items():
            rendered = _text(item)
            if rendered:
                parts.append(f"{key}: {rendered}")
        return "<br>".join(parts)
    return str(value).replace("\n", "<br>").replace("|", "\\|")


def _slug(value: Any, prefix: str = "node") -> str:
    raw = "".join(ch.lower() if ch.isalnum() else "_" for ch in _text(value))
    raw = "_".join(part for part in raw.split("_") if part)
    return (raw[:48] or prefix).strip("_")


def _first(data: Dict[str, Any], *keys: str, default: Any = "") -> Any:
    for key in keys:
        if key in data and data[key] not in (None, ""):
            return data[key]
    return default


class VisualWire:
    """Build markdown tables or mermaid diagrams from framework_output."""

    PORTER_FORCES: Tuple[Tuple[str, str], ...] = (
        ("threat_new_entrants", "Threat of New Entrants"),
        ("threat_substitutes", "Threat of Substitutes"),
        ("bargaining_buyers", "Bargaining Power of Buyers"),
        ("bargaining_suppliers", "Bargaining Power of Suppliers"),
        ("rivalry", "Rivalry Among Existing Competitors"),
    )

    JTBD_DIMS = ("functional", "emotional", "social")
    SWOT_CELLS = (
        ("strengths", "Strengths"),
        ("weaknesses", "Weaknesses"),
        ("opportunities", "Opportunities"),
        ("threats", "Threats"),
    )

    @staticmethod
    def build_chart_block(framework_output: Dict[str, Any]) -> str:
        if not isinstance(framework_output, dict) or not framework_output:
            return ""

        kind = VisualWire._detect_framework(framework_output)
        if kind == "porter":
            return VisualWire._porter_table(framework_output)
        if kind == "jtbd":
            return VisualWire._jtbd_table(framework_output)
        if kind == "north_star":
            return VisualWire._north_star_graph(framework_output)
        if kind == "mece":
            return VisualWire._mece_graph(framework_output)
        if kind == "swot":
            return VisualWire._swot_table(framework_output)
        return ""

    @staticmethod
    def _detect_framework(data: Dict[str, Any]) -> Optional[str]:
        marker = _text(_first(data, "framework", "framework_type", "type", "name")).lower()
        if "porter" in marker or "5 forces" in marker:
            return "porter"
        if "jtbd" in marker or "job" in marker:
            return "jtbd"
        if "north" in marker or "star" in marker:
            return "north_star"
        if "mece" in marker:
            return "mece"
        if "swot" in marker:
            return "swot"

        keys = set(data)
        if any(key in keys for key, _ in VisualWire.PORTER_FORCES):
            return "porter"
        if VisualWire.JTBD_DIMS[0] in keys or "dimensions" in keys:
            return "jtbd"
        if "north_star" in keys or "north_star_metric" in keys or "drivers" in keys:
            return "north_star"
        if "root" in keys and ("branches" in keys or "children" in keys):
            return "mece"
        if {"strengths", "weaknesses", "opportunities", "threats"} & keys:
            return "swot"
        return None

    @staticmethod
    def _porter_table(data: Dict[str, Any]) -> str:
        rows = ["| Force | Severity | Rationale |", "|---|---|---|"]
        source_rows = data.get("forces") if isinstance(data.get("forces"), list) else None
        if source_rows:
            for item in source_rows:
                if not isinstance(item, dict):
                    continue
                rows.append(
                    "| {force} | {severity} | {rationale} |".format(
                        force=_text(_first(item, "force", "name")),
                        severity=_text(_first(item, "severity", "level")),
                        rationale=_text(_first(item, "rationale", "reason", "why")),
                    )
                )
            return "\n".join(rows)

        for key, label in VisualWire.PORTER_FORCES:
            item = data.get(key, {})
            if not isinstance(item, dict):
                item = {"severity": item}
            rows.append(
                "| {force} | {severity} | {rationale} |".format(
                    force=label,
                    severity=_text(_first(item, "severity", "level")),
                    rationale=_text(_first(item, "rationale", "reason", "why")),
                )
            )
        return "\n".join(rows)

    @staticmethod
    def _jtbd_table(data: Dict[str, Any]) -> str:
        dims = VisualWire._jtbd_dimensions(data)
        rows = ["| Dimension | Job | Current Solution | Gap |", "|---|---|---|---|"]
        for dim in VisualWire.JTBD_DIMS:
            item = dims.get(dim, {})
            rows.append(
                "| {dim} | {job} | {current} | {gap} |".format(
                    dim=dim,
                    job=_text(_first(item, "job", "desired_job")),
                    current=_text(_first(item, "current_solution", "current")),
                    gap=_text(_first(item, "underperformance_gap", "gap", "pain")),
                )
            )
        return "\n".join(rows)

    @staticmethod
    def _jtbd_dimensions(data: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
        out: Dict[str, Dict[str, Any]] = {}
        if isinstance(data.get("dimensions"), list):
            for item in data["dimensions"]:
                if isinstance(item, dict):
                    dim = _text(_first(item, "dimension", "name")).lower()
                    if dim:
                        out[dim] = item
        for dim in VisualWire.JTBD_DIMS:
            if isinstance(data.get(dim), dict):
                out[dim] = data[dim]
        return out

    @staticmethod
    def _north_star_graph(data: Dict[str, Any]) -> str:
        metric = _first(data, "north_star", "north_star_metric", "metric", default="North Star")
        lines = ["```mermaid", "graph TD", f"  north_star[\"{_text(metric)}\"]"]
        for index, driver in enumerate(VisualWire._drivers(data), start=1):
            name = _first(driver, "name", "driver", "metric", default=f"Driver {index}")
            node_id = f"driver_{index}_{_slug(name, 'driver')}"
            lines.append(f"  {node_id}[\"{_text(name)}\"]")
            lines.append(f"  north_star --> {node_id}")
        lines.append("```")
        return "\n".join(lines)

    @staticmethod
    def _drivers(data: Dict[str, Any]) -> List[Dict[str, Any]]:
        drivers = data.get("drivers", [])
        if isinstance(drivers, dict):
            return [{"name": key, **(value if isinstance(value, dict) else {"value": value})} for key, value in drivers.items()]
        if isinstance(drivers, list):
            return [item if isinstance(item, dict) else {"name": item} for item in drivers]
        return []

    @staticmethod
    def _mece_graph(data: Dict[str, Any]) -> str:
        root = data.get("root")
        if isinstance(root, dict):
            root_label = _first(root, "label", "name", "question", default="Root")
            children = _first(root, "branches", "children", default=[])
        else:
            root_label = _first(data, "root", "root_question", "question", default="Root")
            children = _first(data, "branches", "children", default=[])

        lines = ["```mermaid", "graph TD", f"  root[\"{_text(root_label)}\"]"]
        VisualWire._append_tree(lines, "root", children)
        lines.append("```")
        return "\n".join(lines)

    @staticmethod
    def _append_tree(lines: List[str], parent_id: str, children: Any, depth: int = 1) -> None:
        for index, child in enumerate(VisualWire._iter_nodes(children), start=1):
            label = _first(child, "label", "name", "question", "title", default=f"Node {index}")
            node_id = f"{parent_id}_{depth}_{index}_{_slug(label)}"
            lines.append(f"  {node_id}[\"{_text(label)}\"]")
            lines.append(f"  {parent_id} --> {node_id}")
            next_children = _first(child, "children", "branches", "leaves", default=[])
            VisualWire._append_tree(lines, node_id, next_children, depth + 1)

    @staticmethod
    def _iter_nodes(children: Any) -> Iterable[Dict[str, Any]]:
        if isinstance(children, dict):
            for label, value in children.items():
                if isinstance(value, dict):
                    yield {"label": label, **value}
                elif isinstance(value, list):
                    yield {"label": label, "children": value}
                else:
                    yield {"label": label, "value": value}
        elif isinstance(children, list):
            for item in children:
                yield item if isinstance(item, dict) else {"label": item}

    @staticmethod
    def _swot_table(data: Dict[str, Any]) -> str:
        cell = {key: _text(data.get(key, [])) for key, _ in VisualWire.SWOT_CELLS}
        return "\n".join(
            [
                "|  | Positive | Negative |",
                "|---|---|---|",
                f"| Internal | {cell['strengths']} | {cell['weaknesses']} |",
                f"| External | {cell['opportunities']} | {cell['threats']} |",
            ]
        )
