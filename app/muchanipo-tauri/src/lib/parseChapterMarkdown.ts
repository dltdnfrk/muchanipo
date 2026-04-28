import type { Chapter, SCR } from "./tauriClient";

/**
 * Parse a MBB 6-chapter markdown report into structured Chapter objects.
 *
 * Expected markdown shape:
 *   ## Chapter 1: Executive Summary
 *   **Lead claim sentence here**
 *
 *   - Body claim one
 *   - Body claim two
 *
 *   **Situation:** ...
 *   **Complication:** ...
 *   **Resolution:** ...
 *
 *   _Sources: layer1, layer2_
 */
export function parseChapterMarkdown(md: string): Chapter[] {
  const chapters: Chapter[] = [];

  // Split by "## Chapter N:" headers
  const blocks = md.split(/\n## Chapter\s+(\d+):\s*/i).filter(Boolean);

  // If the markdown starts with a preamble before Chapter 1, blocks[0] is preamble.
  // We only process blocks that follow a chapter number.
  for (let i = 1; i < blocks.length; i += 2) {
    const chapterNo = parseInt(blocks[i], 10);
    const body = blocks[i + 1] || "";
    chapters.push(parseBlock(chapterNo, body));
  }

  // Fallback: if no chapters found, try looser regex
  if (chapters.length === 0) {
    const regex = /##\s*Chapter\s+(\d+)[\s:]*(.+?)\n([\s\S]*?)(?=##\s*Chapter|$)/gi;
    let m;
    while ((m = regex.exec(md)) !== null) {
      const no = parseInt(m[1], 10);
      const title = m[2].trim();
      const content = m[3];
      chapters.push(parseBlock(no, content, title));
    }
  }

  return chapters.sort((a, b) => a.chapter_no - b.chapter_no);
}

function parseBlock(
  chapterNo: number,
  body: string,
  overrideTitle?: string,
): Chapter {
  const lines = body.split("\n").map((l) => l.trimEnd());

  // Title from first line if not overridden
  let title = overrideTitle || "";
  if (!title && lines[0]) {
    title = lines[0].replace(/^#+\s*/, "").trim();
  }

  // Lead claim: first **bold** line
  let lead_claim = "";
  const boldMatch = body.match(/\*\*(.+?)\*\*/);
  if (boldMatch) {
    lead_claim = boldMatch[1].trim();
  }

  // Body claims: bullet lines
  const body_claims: string[] = [];
  for (const line of lines) {
    if (line.startsWith("- ") || line.startsWith("* ")) {
      body_claims.push(line.replace(/^[-*]\s+/, "").trim());
    }
  }

  // Source layers: `_Sources: ...` or `Sources: ...`
  let source_layers: string[] = [];
  const sourceMatch = body.match(/\*?\*?_?Sources?:?_?\*?\*?\s*([\s\S]+?)(?=\n{2,}|\n##|$)/i);
  if (sourceMatch) {
    source_layers = sourceMatch[1]
      .split(/[,;]/)
      .map((s) => s.trim())
      .filter(Boolean);
  }

  // SCR (Chapter 1 usually)
  let scr: SCR | undefined;
  const sit = body.match(/\*\*Situation:\*\*\s*(.+?)(?=\n\*\*|$)/is);
  const comp = body.match(/\*\*Complication:\*\*\s*(.+?)(?=\n\*\*|$)/is);
  const res = body.match(/\*\*Resolution:\*\*\s*(.+?)(?=\n\*\*|$)/is);
  if (sit || comp || res) {
    scr = {
      situation: sit ? sit[1].trim() : "",
      complication: comp ? comp[1].trim() : "",
      resolution: res ? res[1].trim() : "",
    };
  }

  return {
    chapter_no: chapterNo,
    title,
    lead_claim,
    body_claims,
    source_layers,
    scr,
  };
}
