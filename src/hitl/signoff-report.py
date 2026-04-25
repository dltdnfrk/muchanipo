#!/usr/bin/env python3
"""
MuchaNipo Sign-off Report -- UNCERTAIN 결과를 HTML 보고서로 변환
================================================================
Sign-off Queue의 항목을 시각적 HTML 보고서로 생성하는 도구.

Usage:
    python signoff-report.py <queue-id>              # 특정 항목 HTML 생성
    python signoff-report.py --all                   # 전체 대기 항목 HTML 생성
    python signoff-report.py <queue-id> --open       # 생성 후 브라우저에서 열기
"""

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime
from html import escape
from pathlib import Path
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
SCRIPT_DIR = Path(__file__).resolve().parent
# Support configurable queue dir via env var or CLI --queue-dir
_DEFAULT_QUEUE_DIR = SCRIPT_DIR / "signoff-queue"
SIGNOFF_QUEUE_DIR = Path(os.environ.get("MUCHANIPO_QUEUE_DIR", str(_DEFAULT_QUEUE_DIR)))
REPORTS_DIR = Path(os.environ.get("MUCHANIPO_REPORTS_DIR", str(SCRIPT_DIR / "reports")))


# ---------------------------------------------------------------------------
# Data Loading
# ---------------------------------------------------------------------------
def load_entry(entry_id: str) -> Optional[Dict[str, Any]]:
    """Load a single sign-off queue entry by ID."""
    candidate = SIGNOFF_QUEUE_DIR / f"{entry_id}.json"
    if candidate.exists():
        with open(candidate, "r", encoding="utf-8") as f:
            return json.load(f)

    # Fallback: scan all files
    for fpath in SIGNOFF_QUEUE_DIR.glob("sq-*.json"):
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                data = json.load(f)
            if data.get("id") == entry_id:
                return data
        except (json.JSONDecodeError, OSError):
            continue
    return None


def load_all_pending() -> List[Dict[str, Any]]:
    """Load all pending entries from the signoff-queue directory."""
    entries = []
    if not SIGNOFF_QUEUE_DIR.exists():
        return entries
    for fpath in sorted(SIGNOFF_QUEUE_DIR.glob("sq-*.json")):
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                data = json.load(f)
            if data.get("status", "pending") in ("pending", None):
                entries.append(data)
        except (json.JSONDecodeError, OSError):
            continue
    return entries


# ---------------------------------------------------------------------------
# HTML Generation
# ---------------------------------------------------------------------------
def _e(text: Any) -> str:
    """Escape HTML entities."""
    return escape(str(text)) if text else ""


def _verdict_class(verdict: str) -> str:
    """Return CSS class for verdict badge."""
    v = verdict.upper()
    if v == "PASS":
        return "badge-pass"
    if v == "FAIL":
        return "badge-fail"
    return "badge-uncertain"


def _score_bar(score: int, max_score: int = 10) -> str:
    """Generate CSS-only score bar HTML."""
    pct = min(score / max_score * 100, 100)
    filled = round(score)
    empty = max_score - filled
    blocks_filled = "\u2588" * filled
    blocks_empty = "\u2591" * empty
    return (
        f'<div class="score-row">'
        f'<div class="score-bar-track">'
        f'<div class="score-bar-fill" style="width:{pct:.0f}%"></div>'
        f'</div>'
        f'<span class="score-blocks">{blocks_filled}{blocks_empty}</span>'
        f'<span class="score-value">{score}/{max_score}</span>'
        f'</div>'
    )


def _confidence_gauge(confidence: float) -> str:
    """Generate a CSS-only confidence gauge."""
    pct = min(confidence * 100, 100)
    color = "#ef4444" if pct < 40 else "#f59e0b" if pct < 65 else "#10b981"
    return (
        f'<div class="confidence-gauge">'
        f'<div class="confidence-track">'
        f'<div class="confidence-fill" style="width:{pct:.0f}%;background:{color}"></div>'
        f'</div>'
        f'<span class="confidence-label">{pct:.0f}%</span>'
        f'</div>'
    )


def generate_html(entry: Dict[str, Any]) -> str:
    """Generate a self-contained HTML report from a sign-off queue entry."""
    entry_id = _e(entry.get("id", "unknown"))
    timestamp = _e(entry.get("timestamp", ""))
    topic = _e(entry.get("topic", ""))
    council_id = _e(entry.get("council_id", ""))

    eval_result = entry.get("eval_result", {})
    scores = eval_result.get("scores", {})
    total = eval_result.get("total", 0)
    verdict = eval_result.get("verdict", "UNCERTAIN")
    reasoning = _e(eval_result.get("reasoning", ""))

    report = entry.get("council_report", {})
    consensus = _e(report.get("consensus", ""))
    dissent = _e(report.get("dissent", ""))
    evidence = report.get("evidence", [])
    recommendations = report.get("recommendations", [])
    confidence = report.get("confidence", 0)
    personas = report.get("personas", [])

    verdict_cls = _verdict_class(verdict)
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")

    # Build score bars (v2.1 — 11 axes including citation_fidelity)
    score_labels = {
        "usefulness": "Usefulness",
        "reliability": "Reliability",
        "novelty": "Novelty",
        "actionability": "Actionability",
        "completeness": "Completeness",
        "evidence_quality": "Evidence Quality",
        "perspective_diversity": "Perspective Diversity",
        "coherence": "Coherence",
        "depth": "Depth",
        "impact": "Impact",
        "citation_fidelity": "Citation Fidelity",
    }
    score_rows_html = ""
    for key, label in score_labels.items():
        val = scores.get(key, 0)
        score_rows_html += (
            f'<div class="score-item">'
            f'<span class="score-label">{label}</span>'
            f'{_score_bar(val)}'
            f'</div>'
        )

    # Total row — dynamic rubric_max (10pt × axis count present in scores; falls
    # back to 100 if scores empty). Replaces hardcoded /40 from v1 4-axis era.
    rubric_max = max(1, len(scores) * 10) if scores else 100
    total_pct = min(total / rubric_max * 100, 100)
    score_rows_html += (
        f'<div class="score-item score-total">'
        f'<span class="score-label">Total</span>'
        f'<div class="score-row">'
        f'<div class="score-bar-track total-track">'
        f'<div class="score-bar-fill total-fill" style="width:{total_pct:.0f}%"></div>'
        f'</div>'
        f'<span class="score-value total-value">{total}/{rubric_max} &mdash; '
        f'<span class="{verdict_cls}">{_e(verdict)}</span></span>'
        f'</div>'
        f'</div>'
    )

    # Persona cards
    persona_cards_html = ""
    for p in personas:
        p_name = _e(p.get("name", ""))
        p_role = _e(p.get("role", ""))
        p_conf = p.get("confidence", 0)
        p_position = _e(p.get("position", ""))
        persona_cards_html += (
            f'<div class="persona-card">'
            f'<div class="persona-header">'
            f'<h3 class="persona-name">{p_name}</h3>'
            f'<span class="persona-role">{p_role}</span>'
            f'</div>'
            f'{_confidence_gauge(p_conf)}'
            f'<p class="persona-position">{p_position}</p>'
            f'</div>'
        )

    # Evidence list
    evidence_html = ""
    for i, ev in enumerate(evidence, 1):
        evidence_html += f'<li>{_e(ev)}</li>'

    # Recommendations checklist
    rec_html = ""
    for i, rec in enumerate(recommendations, 1):
        rec_html += (
            f'<li class="rec-item">'
            f'<span class="rec-checkbox">&#9744;</span>'
            f'<span>{_e(rec)}</span>'
            f'</li>'
        )

    # Dissent section (split by persona if multiple paragraphs)
    dissent_paragraphs = ""
    if dissent:
        for para in dissent.split("\n"):
            para = para.strip()
            if para:
                dissent_paragraphs += f'<div class="dissent-card"><p>{para}</p></div>'

    html = f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Sign-off Report: {topic}</title>
<link rel="preconnect" href="https://cdn.jsdelivr.net">
<link href="https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/variable/pretendardvariable-dynamic-subset.min.css" rel="stylesheet">
<style>
/* ================================================================
   MuchaNipo Sign-off Report -- CSS-only, no JavaScript
   ================================================================ */
:root {{
  --color-primary: #059669;
  --color-bg: #f8fafc;
  --color-surface: #ffffff;
  --color-text: #1e293b;
  --color-text-secondary: #64748b;
  --color-border: #e2e8f0;
  --color-pass: #10b981;
  --color-uncertain: #f59e0b;
  --color-fail: #ef4444;
  --color-bar-bg: #e2e8f0;
  --color-bar-fill: #059669;
  --shadow-card: 0 1px 3px rgba(0,0,0,0.06), 0 1px 2px rgba(0,0,0,0.04);
  --shadow-card-hover: 0 4px 12px rgba(0,0,0,0.08);
  --radius: 12px;
  --radius-sm: 8px;
  --font-family: 'Pretendard Variable', Pretendard, -apple-system, BlinkMacSystemFont, system-ui, Roboto, 'Helvetica Neue', 'Segoe UI', 'Apple SD Gothic Neo', 'Noto Sans KR', 'Malgun Gothic', 'Apple Color Emoji', 'Segoe UI Emoji', 'Segoe UI Symbol', sans-serif;
}}

@media (prefers-color-scheme: dark) {{
  :root {{
    --color-bg: #0f172a;
    --color-surface: #1e293b;
    --color-text: #f1f5f9;
    --color-text-secondary: #94a3b8;
    --color-border: #334155;
    --color-bar-bg: #334155;
    --shadow-card: 0 1px 3px rgba(0,0,0,0.3), 0 1px 2px rgba(0,0,0,0.2);
    --shadow-card-hover: 0 4px 12px rgba(0,0,0,0.4);
  }}
}}

*, *::before, *::after {{
  box-sizing: border-box;
  margin: 0;
  padding: 0;
}}

body {{
  font-family: var(--font-family);
  background: var(--color-bg);
  color: var(--color-text);
  line-height: 1.7;
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
}}

.container {{
  max-width: 860px;
  margin: 0 auto;
  padding: 24px 20px 80px;
}}

/* ---- Header ---- */
.report-header {{
  background: var(--color-surface);
  border-radius: var(--radius);
  box-shadow: var(--shadow-card);
  padding: 32px;
  margin-bottom: 24px;
  border-top: 4px solid var(--color-primary);
}}

.report-header h1 {{
  font-size: 1.5rem;
  font-weight: 700;
  margin-bottom: 8px;
  line-height: 1.3;
}}

.header-meta {{
  display: flex;
  flex-wrap: wrap;
  gap: 12px 24px;
  margin-top: 12px;
  font-size: 0.85rem;
  color: var(--color-text-secondary);
}}

.header-meta span {{
  display: inline-flex;
  align-items: center;
  gap: 4px;
}}

.badge {{
  display: inline-block;
  padding: 3px 12px;
  border-radius: 20px;
  font-size: 0.75rem;
  font-weight: 700;
  letter-spacing: 0.05em;
  text-transform: uppercase;
}}

.badge-pass {{
  background: var(--color-pass);
  color: #fff;
}}

.badge-uncertain {{
  background: var(--color-uncertain);
  color: #fff;
}}

.badge-fail {{
  background: var(--color-fail);
  color: #fff;
}}

/* ---- Section card ---- */
.section {{
  background: var(--color-surface);
  border-radius: var(--radius);
  box-shadow: var(--shadow-card);
  padding: 28px 32px;
  margin-bottom: 20px;
}}

.section h2 {{
  font-size: 1.1rem;
  font-weight: 700;
  margin-bottom: 16px;
  padding-bottom: 8px;
  border-bottom: 2px solid var(--color-border);
  display: flex;
  align-items: center;
  gap: 8px;
}}

.section h2 .icon {{
  font-size: 1.2rem;
}}

/* ---- Score Dashboard ---- */
.score-dashboard {{
  display: flex;
  flex-direction: column;
  gap: 12px;
}}

.score-item {{
  display: flex;
  align-items: center;
  gap: 12px;
}}

.score-label {{
  width: 110px;
  font-size: 0.9rem;
  font-weight: 500;
  color: var(--color-text-secondary);
  flex-shrink: 0;
}}

.score-row {{
  flex: 1;
  display: flex;
  align-items: center;
  gap: 10px;
}}

.score-bar-track {{
  flex: 1;
  height: 10px;
  background: var(--color-bar-bg);
  border-radius: 5px;
  overflow: hidden;
}}

.score-bar-fill {{
  height: 100%;
  background: var(--color-bar-fill);
  border-radius: 5px;
  transition: width 0.3s ease;
}}

.total-track {{
  height: 14px;
  border-radius: 7px;
}}

.total-fill {{
  border-radius: 7px;
}}

.score-blocks {{
  font-family: monospace;
  font-size: 0.8rem;
  color: var(--color-text-secondary);
  letter-spacing: 1px;
  white-space: nowrap;
}}

.score-value {{
  font-size: 0.85rem;
  font-weight: 600;
  white-space: nowrap;
  min-width: 50px;
  text-align: right;
}}

.total-value {{
  font-size: 1rem;
  font-weight: 700;
}}

.score-total {{
  margin-top: 8px;
  padding-top: 12px;
  border-top: 1px solid var(--color-border);
}}

.score-total .score-label {{
  font-weight: 700;
  color: var(--color-text);
}}

/* ---- Reasoning ---- */
.reasoning {{
  font-size: 0.9rem;
  color: var(--color-text-secondary);
  margin-top: 16px;
  padding: 16px;
  background: var(--color-bg);
  border-radius: var(--radius-sm);
  line-height: 1.8;
}}

/* ---- Consensus ---- */
.consensus-text {{
  font-size: 0.95rem;
  line-height: 1.8;
}}

.confidence-overall {{
  margin-top: 16px;
  display: flex;
  align-items: center;
  gap: 12px;
  font-size: 0.9rem;
  color: var(--color-text-secondary);
}}

/* ---- Dissent cards ---- */
.dissent-grid {{
  display: flex;
  flex-direction: column;
  gap: 12px;
}}

.dissent-card {{
  padding: 16px 20px;
  background: var(--color-bg);
  border-radius: var(--radius-sm);
  border-left: 3px solid var(--color-uncertain);
  font-size: 0.9rem;
  line-height: 1.8;
}}

/* ---- Persona cards ---- */
.persona-grid {{
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(340px, 1fr));
  gap: 16px;
}}

.persona-card {{
  padding: 20px;
  background: var(--color-bg);
  border-radius: var(--radius-sm);
  border: 1px solid var(--color-border);
}}

.persona-card:hover {{
  box-shadow: var(--shadow-card-hover);
}}

.persona-header {{
  margin-bottom: 12px;
}}

.persona-name {{
  font-size: 1rem;
  font-weight: 700;
  margin-bottom: 2px;
}}

.persona-role {{
  font-size: 0.8rem;
  color: var(--color-text-secondary);
}}

.persona-position {{
  font-size: 0.85rem;
  line-height: 1.7;
  margin-top: 12px;
  color: var(--color-text-secondary);
}}

/* ---- Confidence gauge ---- */
.confidence-gauge {{
  display: flex;
  align-items: center;
  gap: 8px;
}}

.confidence-track {{
  flex: 1;
  height: 6px;
  background: var(--color-bar-bg);
  border-radius: 3px;
  overflow: hidden;
}}

.confidence-fill {{
  height: 100%;
  border-radius: 3px;
}}

.confidence-label {{
  font-size: 0.8rem;
  font-weight: 600;
  min-width: 36px;
  text-align: right;
}}

/* ---- Evidence ---- */
.evidence-list {{
  list-style: none;
  padding: 0;
}}

.evidence-list li {{
  padding: 10px 16px;
  margin-bottom: 6px;
  background: var(--color-bg);
  border-radius: var(--radius-sm);
  font-size: 0.85rem;
  font-family: 'SF Mono', 'Fira Code', 'Consolas', monospace;
  color: var(--color-text-secondary);
  word-break: break-all;
}}

.evidence-list li::before {{
  content: "\\1F4CE\\FE0E ";
}}

/* ---- Recommendations ---- */
.rec-list {{
  list-style: none;
  padding: 0;
}}

.rec-item {{
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 12px 16px;
  margin-bottom: 6px;
  background: var(--color-bg);
  border-radius: var(--radius-sm);
  font-size: 0.9rem;
  line-height: 1.6;
}}

.rec-checkbox {{
  font-size: 1.1rem;
  flex-shrink: 0;
  margin-top: 1px;
}}

/* ---- Decision area ---- */
.decision-area {{
  text-align: center;
  padding: 32px;
}}

.decision-buttons {{
  display: flex;
  justify-content: center;
  gap: 16px;
  flex-wrap: wrap;
  margin-bottom: 20px;
}}

.btn {{
  display: inline-block;
  padding: 14px 32px;
  border-radius: var(--radius-sm);
  font-size: 1rem;
  font-weight: 700;
  font-family: var(--font-family);
  border: 2px solid transparent;
  cursor: default;
  text-decoration: none;
  min-width: 140px;
  text-align: center;
}}

.btn-approve {{
  background: var(--color-pass);
  color: #fff;
}}

.btn-reject {{
  background: var(--color-fail);
  color: #fff;
}}

.btn-modify {{
  background: var(--color-surface);
  color: var(--color-text);
  border-color: var(--color-border);
}}

.decision-hint {{
  font-size: 0.8rem;
  color: var(--color-text-secondary);
  line-height: 1.6;
}}

.decision-hint code {{
  display: inline-block;
  padding: 2px 8px;
  background: var(--color-bg);
  border-radius: 4px;
  font-family: 'SF Mono', 'Fira Code', 'Consolas', monospace;
  font-size: 0.78rem;
  word-break: break-all;
}}

/* ---- Footer ---- */
.report-footer {{
  text-align: center;
  padding: 24px 0;
  font-size: 0.75rem;
  color: var(--color-text-secondary);
  border-top: 1px solid var(--color-border);
  margin-top: 32px;
}}

/* ---- Responsive ---- */
@media (max-width: 640px) {{
  .container {{
    padding: 12px 10px 60px;
  }}

  .report-header {{
    padding: 20px 16px;
  }}

  .report-header h1 {{
    font-size: 1.2rem;
  }}

  .section {{
    padding: 20px 16px;
  }}

  .persona-grid {{
    grid-template-columns: 1fr;
  }}

  .score-blocks {{
    display: none;
  }}

  .score-label {{
    width: 90px;
    font-size: 0.8rem;
  }}

  .decision-buttons {{
    flex-direction: column;
    align-items: center;
  }}

  .btn {{
    width: 100%;
    max-width: 280px;
  }}

  .header-meta {{
    flex-direction: column;
    gap: 6px;
  }}
}}

/* ---- Print ---- */
@media print {{
  body {{
    background: #fff;
  }}

  .section, .report-header {{
    box-shadow: none;
    border: 1px solid #ddd;
    break-inside: avoid;
  }}

  .decision-area {{
    display: none;
  }}
}}
</style>
</head>
<body>

<div class="container">

  <!-- Header -->
  <header class="report-header">
    <h1>{topic}</h1>
    <div class="header-meta">
      <span><strong>ID:</strong> {entry_id}</span>
      <span><strong>Council:</strong> {council_id}</span>
      <span><strong>Date:</strong> {timestamp}</span>
      <span class="badge {verdict_cls}">{_e(verdict)}</span>
    </div>
  </header>

  <!-- Score Dashboard -->
  <section class="section">
    <h2><span class="icon">&#x1F4CA;</span> Eval Scores</h2>
    <div class="score-dashboard">
      {score_rows_html}
    </div>
    {f'<div class="reasoning">{reasoning}</div>' if reasoning else ''}
  </section>

  <!-- Council Consensus -->
  <section class="section">
    <h2><span class="icon">&#x1F91D;</span> Council 합의</h2>
    <p class="consensus-text">{consensus}</p>
    <div class="confidence-overall">
      <span>Overall Confidence:</span>
      {_confidence_gauge(confidence)}
    </div>
  </section>

  <!-- Dissent -->
  {f'''<section class="section">
    <h2><span class="icon">&#x2696;&#xFE0E;</span> 반론 (Dissenting Views)</h2>
    <div class="dissent-grid">
      {dissent_paragraphs}
    </div>
  </section>''' if dissent else ''}

  <!-- Personas -->
  {f'''<section class="section">
    <h2><span class="icon">&#x1F465;</span> 페르소나별 분석</h2>
    <div class="persona-grid">
      {persona_cards_html}
    </div>
  </section>''' if personas else ''}

  <!-- Evidence -->
  {f'''<section class="section">
    <h2><span class="icon">&#x1F4D1;</span> 근거 자료 ({len(evidence)}건)</h2>
    <ul class="evidence-list">
      {evidence_html}
    </ul>
  </section>''' if evidence else ''}

  <!-- Recommendations -->
  {f'''<section class="section">
    <h2><span class="icon">&#x2705;</span> 권고사항</h2>
    <ul class="rec-list">
      {rec_html}
    </ul>
  </section>''' if recommendations else ''}

  <!-- Decision Area -->
  <section class="section decision-area">
    <h2 style="justify-content:center;border-bottom:none;"><span class="icon">&#x1F3AF;</span> 결정</h2>
    <div class="decision-buttons">
      <span class="btn btn-approve">&#x2714; 승인</span>
      <span class="btn btn-reject">&#x2718; 거절</span>
      <span class="btn btn-modify">&#x270E; 수정</span>
    </div>
    <p class="decision-hint">
      터미널에서 실행:<br>
      <code>python signoff-queue.py approve {entry_id}</code><br>
      <code>python signoff-queue.py reject {entry_id} --reason "사유"</code><br>
      <code>python signoff-queue.py modify {entry_id} --note "수정 내용"</code>
    </p>
  </section>

  <footer class="report-footer">
    MuchaNipo AutoResearch &middot; Sign-off Report &middot; Generated {now_str}
  </footer>

</div>

</body>
</html>"""

    return html


# ---------------------------------------------------------------------------
# File Output
# ---------------------------------------------------------------------------
def write_report(entry: Dict[str, Any], open_browser: bool = False) -> Path:
    """Generate HTML and write to reports directory. Returns the output path."""
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    entry_id = entry.get("id", "unknown")
    html = generate_html(entry)

    output_path = REPORTS_DIR / f"{entry_id}.html"
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"Report generated: {output_path}")

    if open_browser:
        try:
            subprocess.run(["open", str(output_path)], check=True)
            print("Opened in browser.")
        except (subprocess.CalledProcessError, FileNotFoundError):
            print(f"Could not open browser. Open manually: {output_path}", file=sys.stderr)

    return output_path


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="MuchaNipo Sign-off Report -- HTML 보고서 생성",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python signoff-report.py sq-20260409-123456
  python signoff-report.py sq-20260409-123456 --open
  python signoff-report.py --all
        """,
    )
    parser.add_argument(
        "id",
        nargs="?",
        help="Sign-off queue entry ID (e.g., sq-20260409-123456)",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Generate reports for all pending entries",
    )
    parser.add_argument(
        "--open",
        action="store_true",
        help="Open the generated report in browser (macOS only)",
    )
    parser.add_argument(
        "--queue-dir",
        default=None,
        help="Override signoff-queue directory path",
    )
    parser.add_argument(
        "--reports-dir",
        default=None,
        help="Override reports output directory path",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    # Apply CLI overrides for directories
    global SIGNOFF_QUEUE_DIR, REPORTS_DIR
    if args.queue_dir:
        SIGNOFF_QUEUE_DIR = Path(args.queue_dir)
    if args.reports_dir:
        REPORTS_DIR = Path(args.reports_dir)

    if not args.id and not args.all:
        parser.print_help()
        return 1

    if args.all:
        entries = load_all_pending()
        if not entries:
            print("No pending entries in sign-off queue.")
            return 0
        for entry in entries:
            write_report(entry, open_browser=False)
        print(f"\nGenerated {len(entries)} report(s) in {REPORTS_DIR}")
        return 0

    entry = load_entry(args.id)
    if not entry:
        print(f"ERROR: Entry not found: {args.id}", file=sys.stderr)
        return 1

    write_report(entry, open_browser=args.open)
    return 0


if __name__ == "__main__":
    sys.exit(main())
