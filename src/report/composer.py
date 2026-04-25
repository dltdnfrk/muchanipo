"""Report Composer — Council results → MBB-급 markdown deck."""
from __future__ import annotations

import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

# round_layers (C24) import
_BASE_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(_BASE_DIR / "council"))
try:
    from round_layers import DEFAULT_LAYERS, RoundLayer  # type: ignore
except ImportError:  # pragma: no cover
    DEFAULT_LAYERS = []
    RoundLayer = None  # type: ignore


def _safe(text: Any) -> str:
    return str(text) if text is not None else ""


class ReportComposer:
    """Council 디렉토리 → REPORT.md 합성."""

    def __init__(self, council_dir: Path):
        self.council_dir = Path(council_dir)
        if not self.council_dir.exists():
            raise FileNotFoundError(f"council_dir not found: {council_dir}")
        self.meta = self._load_meta()
        self.rounds: Dict[int, List[dict]] = self._load_rounds()

    # ---------------------------------------------------------------- loaders
    def _load_meta(self) -> dict:
        meta_path = self.council_dir / "meta.json"
        if not meta_path.exists():
            return {}
        with open(meta_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def _load_rounds(self) -> Dict[int, List[dict]]:
        out: Dict[int, List[dict]] = {}
        for fp in sorted(self.council_dir.glob("round-*-*.json")):
            stem = fp.stem  # round-{N}-{persona}
            try:
                round_num = int(stem.split("-")[1])
            except (IndexError, ValueError):
                continue
            with open(fp, "r", encoding="utf-8") as f:
                data = json.load(f)
            out.setdefault(round_num, []).append(data)
        return out

    # ---------------------------------------------------------------- helpers
    def _layer_for_round(self, round_num: int) -> Optional[RoundLayer]:
        if not DEFAULT_LAYERS:
            return None
        idx = min(round_num - 1, len(DEFAULT_LAYERS) - 1)
        return DEFAULT_LAYERS[idx] if idx >= 0 else None

    def _position_counter(self, results: List[dict]) -> Counter:
        return Counter(r.get("position", "중립") for r in results)

    def _avg_confidence(self, results: List[dict]) -> float:
        if not results:
            return 0.0
        vals = [float(r.get("confidence", 0.0)) for r in results]
        return sum(vals) / len(vals)

    # ---------------------------------------------------------------- sections
    def _cover(self) -> str:
        topic = _safe(self.meta.get("topic", "(no topic)"))
        council_id = _safe(self.meta.get("council_id", ""))
        rt = _safe(self.meta.get("research_type", "exploratory"))
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        n_personas = len(self.meta.get("personas", []))
        max_rounds = self.meta.get("max_rounds", "?")
        return (
            f"# {topic}\n\n"
            f"**Council Report — MBB-style Synthesis**\n\n"
            f"| Field | Value |\n"
            f"|---|---|\n"
            f"| Council ID | `{council_id}` |\n"
            f"| Research Type | `{rt}` |\n"
            f"| Personas | {n_personas} |\n"
            f"| Max Rounds | {max_rounds} |\n"
            f"| Generated | {ts} |\n"
        )

    def _executive_summary(self) -> str:
        last_round = max(self.rounds.keys()) if self.rounds else 0
        last_results = self.rounds.get(last_round, [])
        if not last_results:
            return "## Executive Summary\n\n_No round data available._"

        positions = self._position_counter(last_results)
        avg_conf = self._avg_confidence(last_results)
        dominant = positions.most_common(1)[0] if positions else ("중립", 0)

        # L10 chapter 결과 우선 (있으면)
        synthesis_results = self.rounds.get(10, last_results)
        top_points: List[str] = []
        for r in synthesis_results[:3]:
            for kp in r.get("key_points", [])[:2]:
                top_points.append(f"- {kp}")

        lines = [
            "## Executive Summary",
            "",
            f"**Net Position:** {dominant[0]} ({dominant[1]}/{len(last_results)} 페르소나)",
            f"**Average Confidence:** {avg_conf:.2f}",
            "",
            "**Top Findings:**",
        ]
        lines += top_points or ["- _findings not yet synthesized_"]
        lines += [
            "",
            "**Position Distribution:**",
            "",
            "| Position | Count |",
            "|---|---|",
        ]
        for pos, cnt in positions.most_common():
            lines.append(f"| {pos} | {cnt} |")
        return "\n".join(lines)

    def _table_of_contents(self) -> str:
        lines = ["## Table of Contents", ""]
        for round_num in sorted(self.rounds.keys()):
            layer = self._layer_for_round(round_num)
            chapter = layer.chapter_title if layer else f"Round {round_num}"
            lines.append(f"- Chapter {round_num} — {chapter}")
        lines += [
            "- Cross-Round Consensus & Dissent",
            "- Appendix A: Personas",
            "- Appendix B: Evidence Index",
        ]
        return "\n".join(lines)

    def _chapter(self, round_num: int) -> str:
        layer = self._layer_for_round(round_num)
        results = self.rounds.get(round_num, [])
        if not results:
            return ""

        chapter_title = layer.chapter_title if layer else f"Round {round_num}"
        focus_q = layer.focus_question if layer else ""

        positions = self._position_counter(results)
        avg_conf = self._avg_confidence(results)

        lines = [
            f"## Chapter {round_num} — {chapter_title}",
            "",
        ]
        if focus_q:
            lines += [f"**Focus Question:** {focus_q}", ""]
        lines += [
            f"**Round Confidence:** {avg_conf:.2f}",
            f"**Positions:** "
            + ", ".join(f"{p}({c})" for p, c in positions.most_common()),
            "",
            "### Persona Findings",
            "",
        ]

        for r in results:
            persona = _safe(r.get("persona", "?"))
            role = _safe(r.get("role", ""))
            position = _safe(r.get("position", "중립"))
            confidence = float(r.get("confidence", 0.0))
            analysis = _safe(r.get("analysis") or r.get("updated_analysis", ""))
            key_points = r.get("key_points", []) or []
            evidence = r.get("evidence", []) or []
            framework = r.get("framework_output")

            lines += [
                f"#### {persona} — {role}",
                f"- **Position:** {position}  |  **Confidence:** {confidence:.2f}",
            ]
            if analysis:
                lines += ["", f"{analysis}", ""]
            if key_points:
                lines.append("**Key Points:**")
                for kp in key_points:
                    lines.append(f"- {kp}")
                lines.append("")
            if evidence:
                lines.append("**Evidence:**")
                for ev in evidence:
                    if isinstance(ev, dict):
                        claim = ev.get("claim") or ev.get("text", "")
                        src = ev.get("source") or ev.get("url", "")
                        lines.append(f"- {claim} _(source: {src})_")
                    else:
                        lines.append(f"- {ev}")
                lines.append("")
            if framework:
                lines += ["**Framework Output:**", "```json",
                          json.dumps(framework, ensure_ascii=False, indent=2),
                          "```", ""]
            lines.append("---")
            lines.append("")

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
        dissenters = [r for r in last_results
                      if r.get("position") != dominant]

        lines = [
            "## Cross-Round Consensus & Dissent",
            "",
            f"**Dominant Position (Round {last_round}):** {dominant} ({dom_count}/{len(last_results)})",
            "",
        ]
        if dissenters:
            lines += ["### Dissenting Voices", ""]
            for r in dissenters:
                persona = _safe(r.get("persona", "?"))
                role = _safe(r.get("role", ""))
                pos = _safe(r.get("position", ""))
                kp = r.get("key_points", []) or []
                lines.append(f"- **{persona} ({role}, {pos}):** "
                             + (kp[0] if kp else "_no key point_"))
        else:
            lines.append("_All personas aligned on dominant position._")
        return "\n".join(lines)

    def _appendix_personas(self) -> str:
        personas = self.meta.get("personas", [])
        if not personas:
            return ""
        lines = ["## Appendix A — Personas", ""]
        for p in personas:
            lines += [
                f"### {p.get('name', '?')} — {p.get('role', '')}",
                f"- **Expertise:** {', '.join(p.get('expertise', []))}",
                f"- **Bias:** {p.get('perspective_bias', '')}",
                f"- **Style:** {p.get('argument_style', '')}",
                "",
            ]
        return "\n".join(lines)

    def _appendix_evidence(self) -> str:
        all_ev: List[str] = []
        for results in self.rounds.values():
            for r in results:
                for ev in r.get("evidence", []) or []:
                    if isinstance(ev, dict):
                        src = ev.get("source") or ev.get("url", "")
                        if src and src not in all_ev:
                            all_ev.append(src)
        if not all_ev:
            return ""
        lines = ["## Appendix B — Evidence Index", ""]
        for i, src in enumerate(all_ev, 1):
            lines.append(f"{i}. {src}")
        return "\n".join(lines)

    # --------------------------------------------------------------- public
    def render(self) -> str:
        sections = [
            self._cover(),
            self._executive_summary(),
            self._table_of_contents(),
        ]
        for round_num in sorted(self.rounds.keys()):
            chapter = self._chapter(round_num)
            if chapter:
                sections.append(chapter)
        sections += [
            self._consensus_dissent(),
            self._appendix_personas(),
            self._appendix_evidence(),
        ]
        return "\n\n".join(s for s in sections if s)

    def write(self, output_name: str = "REPORT.md") -> Path:
        out = self.council_dir / output_name
        out.write_text(self.render(), encoding="utf-8")
        return out


def compose_report(council_dir: Path, output_name: str = "REPORT.md") -> Path:
    """Convenience: ReportComposer wrapper."""
    return ReportComposer(council_dir).write(output_name)
