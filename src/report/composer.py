"""Report Composer — Council results to markdown reports."""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from .visual_wire import VisualWire


def _safe(text: Any) -> str:
    return str(text) if text is not None else ""


class ReportComposer:
    """Compose a council log directory into a markdown report."""

    def __init__(self, council_dir: Path):
        self.council_dir = Path(council_dir)
        if not self.council_dir.exists():
            raise FileNotFoundError(f"council_dir not found: {council_dir}")
        self.meta = self._load_meta()
        self.rounds = self._load_rounds()

    def _load_meta(self) -> dict:
        meta_path = self.council_dir / "meta.json"
        if not meta_path.exists():
            return {}
        with open(meta_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def _load_rounds(self) -> Dict[int, List[dict]]:
        out: Dict[int, List[dict]] = {}
        for fp in sorted(self.council_dir.glob("round-*-*.json")):
            try:
                round_num = int(fp.stem.split("-")[1])
            except (IndexError, ValueError):
                continue
            with open(fp, "r", encoding="utf-8") as f:
                out.setdefault(round_num, []).append(json.load(f))
        return out

    def _layer_for_round(self, round_num: int) -> Optional[Any]:
        return None

    def _position_counter(self, results: List[dict]) -> Counter:
        return Counter(r.get("position", "중립") for r in results)

    def _avg_confidence(self, results: List[dict]) -> float:
        values = [float(r.get("confidence", 0) or 0) for r in results]
        return sum(values) / len(values) if values else 0.0

    def _cover(self) -> str:
        topic = self.meta.get("topic", "Untitled Council Report")
        council_id = self.meta.get("council_id", self.council_dir.name)
        research_type = self.meta.get("research_type", "")
        timestamp = self.meta.get("timestamp") or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        return "\n".join(
            [
                f"# {topic}",
                "",
                f"- **Council ID:** {council_id}",
                f"- **Research Type:** {research_type}",
                f"- **Generated:** {timestamp}",
            ]
        )

    def _executive_summary(self) -> str:
        all_results = [item for results in self.rounds.values() for item in results]
        positions = self._position_counter(all_results)
        dominant = positions.most_common(1)[0][0] if positions else "n/a"
        confidence = self._avg_confidence(all_results)
        key_points: List[str] = []
        for result in all_results:
            key_points.extend(result.get("key_points", []) or [])
        lines = [
            "## Executive Summary",
            "",
            f"**Dominant Position:** {dominant}",
            f"**Average Confidence:** {confidence:.2f}",
            "",
            "### Core Signals",
        ]
        lines.extend(f"- {point}" for point in key_points[:6])
        if not key_points:
            lines.append("- No round outputs available yet.")
        return "\n".join(lines)

    def _table_of_contents(self) -> str:
        lines = ["## Table of Contents", ""]
        for round_num in sorted(self.rounds):
            lines.append(f"- Round {round_num}")
        lines.extend(["- Cross-Round Consensus & Dissent", "- Appendix A — Personas", "- Appendix B — Evidence Index"])
        return "\n".join(lines)

    def _chapter(self, round_num: int) -> str:
        results = self.rounds.get(round_num, [])
        if not results:
            return ""
        positions = self._position_counter(results)
        position_summary = ", ".join(f"{position}({count})" for position, count in positions.most_common())
        lines = [
            f"## Round {round_num}",
            "",
            f"**Position Mix:** {position_summary}",
            f"**Average Confidence:** {self._avg_confidence(results):.2f}",
            "",
        ]
        for result in results:
            persona = _safe(result.get("persona", "?"))
            role = _safe(result.get("role", ""))
            position = _safe(result.get("position", ""))
            lines.extend([f"### {persona} — {role}", "", f"**Position:** {position}", ""])

            key_points = result.get("key_points", []) or []
            if key_points:
                lines.append("**Key Points:**")
                lines.extend(f"- {point}" for point in key_points)
                lines.append("")

            analysis = _safe(result.get("analysis", ""))
            if analysis:
                lines.extend(["**Analysis:**", analysis, ""])

            evidence = result.get("evidence", []) or []
            if evidence:
                lines.append("**Evidence:**")
                for ev in evidence:
                    if isinstance(ev, dict):
                        claim = ev.get("claim") or ev.get("quote") or ev.get("text") or ""
                        src = ev.get("source") or ev.get("url") or ""
                        if src:
                            lines.append(f"- {claim} _(source: {src})_")
                        else:
                            lines.append(f"- {claim}")
                    else:
                        lines.append(f"- {ev}")
                lines.append("")

            framework = result.get("framework_output")
            if framework:
                chart = VisualWire.build_chart_block(framework)
                if chart:
                    lines.extend(["**Framework Output:**", chart, ""])
                else:
                    lines.extend(
                        [
                            "**Framework Output:**",
                            "```json",
                            json.dumps(framework, ensure_ascii=False, indent=2),
                            "```",
                            "",
                        ]
                    )
            lines.extend(["---", ""])
        return "\n".join(lines)

    def _consensus_dissent(self) -> str:
        if not self.rounds:
            return ""
        last_round = max(self.rounds.keys())
        last_results = self.rounds[last_round]
        positions = self._position_counter(last_results)
        if not positions:
            return ""
        dominant, dom_count = positions.most_common(1)[0]
        dissenters = [r for r in last_results if r.get("position") != dominant]
        lines = [
            "## Cross-Round Consensus & Dissent",
            "",
            f"**Dominant Position (Round {last_round}):** {dominant} ({dom_count}/{len(last_results)})",
            "",
        ]
        if dissenters:
            lines.extend(["### Dissenting Voices", ""])
            for result in dissenters:
                persona = _safe(result.get("persona", "?"))
                role = _safe(result.get("role", ""))
                pos = _safe(result.get("position", ""))
                kp = result.get("key_points", []) or []
                lines.append(f"- **{persona} ({role}, {pos}):** {kp[0] if kp else '_no key point_'}")
        else:
            lines.append("_All personas aligned on dominant position._")
        return "\n".join(lines)

    def _appendix_personas(self) -> str:
        personas = self.meta.get("personas", [])
        if not personas:
            return ""
        lines = ["## Appendix A — Personas", ""]
        for p in personas:
            lines.extend(
                [
                    f"### {p.get('name', '?')} — {p.get('role', '')}",
                    f"- **Expertise:** {', '.join(p.get('expertise', []))}",
                    f"- **Bias:** {p.get('perspective_bias', '')}",
                    f"- **Style:** {p.get('argument_style', '')}",
                    "",
                ]
            )
        return "\n".join(lines)

    def _appendix_evidence(self) -> str:
        all_ev: List[str] = []
        for results in self.rounds.values():
            for result in results:
                for ev in result.get("evidence", []) or []:
                    if isinstance(ev, dict):
                        src = ev.get("source") or ev.get("url") or ""
                        if src and src not in all_ev:
                            all_ev.append(src)
        if not all_ev:
            return ""
        lines = ["## Appendix B — Evidence Index", ""]
        lines.extend(f"{i}. {src}" for i, src in enumerate(all_ev, 1))
        return "\n".join(lines)

    def render(self) -> str:
        sections = [self._cover(), self._executive_summary(), self._table_of_contents()]
        for round_num in sorted(self.rounds.keys()):
            chapter = self._chapter(round_num)
            if chapter:
                sections.append(chapter)
        sections += [self._consensus_dissent(), self._appendix_personas(), self._appendix_evidence()]
        return "\n\n".join(s for s in sections if s)

    def write(self, output_name: str = "REPORT.md") -> Path:
        out = self.council_dir / output_name
        out.write_text(self.render(), encoding="utf-8")
        return out


def compose_report(council_dir: Path, output_name: str = "REPORT.md") -> Path:
    """Convenience wrapper for report composition."""

    return ReportComposer(council_dir).write(output_name)
