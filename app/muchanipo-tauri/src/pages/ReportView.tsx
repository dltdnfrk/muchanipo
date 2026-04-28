import { useEffect, useRef, useState } from "react";
import { useParams } from "react-router-dom";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import ChapterCard from "../components/ChapterCard";
import { parseChapterMarkdown } from "../lib/parseChapterMarkdown";
import {
  getBufferedEvents,
  onBackendEvent,
  type BackendEvent,
  type Chapter,
} from "../lib/tauriClient";

export default function ReportView() {
  const { runId } = useParams<{ runId: string }>();
  const [markdown, setMarkdown] = useState<string>("");
  const [chapters, setChapters] = useState<Chapter[]>([]);
  const [showRaw, setShowRaw] = useState(false);
  const [topic, setTopic] = useState<string>("");
  const chunkKeysRef = useRef<Set<string>>(new Set());
  const finalReportReceivedRef = useRef(false);

  useEffect(() => {
    if (!runId) return;
    let mounted = true;
    let unlisten: (() => void) | undefined;
    const applyMarkdown = (md: string) => {
      if (!mounted) return;
      setMarkdown(md);
      setChapters(parseChapterMarkdown(md));
    };
    const appendChunk = (chunk: string) => {
      const key = chunk.trim();
      if (!key || finalReportReceivedRef.current || chunkKeysRef.current.has(key)) return;
      chunkKeysRef.current.add(key);
      const current = localStorage.getItem(`run:${runId}:report`) || "";
      const next = `${current}${current ? "\n\n" : ""}${chunk}`;
      localStorage.setItem(`run:${runId}:report`, next);
      applyMarkdown(next);
    };
    const handleEvent = (event: BackendEvent) => {
      if (!runId) return;
      if (event.event === "final_report") {
        const md = String(event.markdown ?? "");
        if (md) {
          finalReportReceivedRef.current = true;
          chunkKeysRef.current.clear();
          localStorage.setItem(`run:${runId}:report`, md);
          applyMarkdown(md);
        }
        return;
      }
      if (event.event === "report_chunk") {
        const chunk = String(event.markdown ?? event.delta ?? "");
        if (!chunk) return;
        appendChunk(chunk);
      }
    };
    try {
      const md = localStorage.getItem(`run:${runId}:report`) || "";
      applyMarkdown(md);
      setTopic(localStorage.getItem(`run:${runId}:topic`) || "");
    } catch {
      /* ignore */
    }
    onBackendEvent(handleEvent).then(async (cleanup) => {
      if (!mounted) {
        cleanup();
        return;
      }
      unlisten = cleanup;
      try {
        const history = await getBufferedEvents();
        const finalReports = history.filter((event) => event.event === "final_report");
        const latestFinal = finalReports[finalReports.length - 1];
        if (latestFinal) {
          handleEvent(latestFinal);
          return;
        }

        const chunks = history
          .filter((event) => event.event === "report_chunk")
          .map((event) => String(event.markdown ?? event.delta ?? ""))
          .filter(Boolean);
        if (chunks.length > 0) {
          chunkKeysRef.current.clear();
          const uniqueChunks: string[] = [];
          for (const chunk of chunks) {
            const key = chunk.trim();
            if (!key || chunkKeysRef.current.has(key)) continue;
            chunkKeysRef.current.add(key);
            uniqueChunks.push(chunk);
          }
          const rebuilt = uniqueChunks.join("\n\n");
          const current = localStorage.getItem(`run:${runId}:report`) || "";
          if (current.length >= rebuilt.length) return;
          localStorage.setItem(`run:${runId}:report`, rebuilt);
          applyMarkdown(rebuilt);
        }
      } catch {
        /* non-fatal */
      }
    });
    return () => {
      mounted = false;
      unlisten?.();
    };
  }, [runId]);

  const exportMarkdown = () => {
    if (!markdown) return;
    const blob = new Blob([markdown], { type: "text/markdown" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    const name = topic ? topic.replace(/\s+/g, "_") : runId || "report";
    a.href = url;
    a.download = `${name}.md`;
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  };

  if (!markdown) {
    return (
      <div className="flex min-h-screen flex-col items-center justify-center gap-3 px-4">
        <svg className="h-5 w-5 animate-spin text-white/60" viewBox="0 0 24 24" fill="none">
          <circle cx="12" cy="12" r="10" stroke="currentColor" strokeOpacity="0.3" strokeWidth="3" />
          <path d="M12 2a10 10 0 0110 10" stroke="currentColor" strokeWidth="3" strokeLinecap="round" />
        </svg>
        <p className="text-sm text-tertiary">보고서를 불러오는 중…</p>
      </div>
    );
  }

  return (
    <div className="min-h-screen px-6 py-10">
      <div className="mx-auto max-w-4xl">
        {/* Header */}
        <header className="fade-in mb-8 flex flex-col items-start justify-between gap-3 md:flex-row md:items-end">
          <div>
            <p className="mb-1.5 text-[11px] font-semibold uppercase tracking-wider text-tertiary">
              MBB 6-chapter report
            </p>
            <h1 className="text-2xl font-semibold tracking-tight text-white">
              {topic || "리서치 보고서"}
            </h1>
            <p className="mt-1 font-mono text-xs text-tertiary">{runId}</p>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={() => setShowRaw((s) => !s)}
              className="rounded-full border border-white/10 bg-transparent px-3.5 py-1.5 text-xs text-secondary transition hover:bg-white/5 hover:text-white"
            >
              {showRaw ? "카드 보기" : "원본 Markdown"}
            </button>
            <button
              onClick={exportMarkdown}
              className="rounded-full bg-white px-3.5 py-1.5 text-xs font-medium text-black transition hover:opacity-90"
            >
              다운로드
            </button>
          </div>
        </header>

        {/* Body */}
        {showRaw ? (
          <div className="rounded-xl border border-white/5 bg-white/[0.02] p-6">
            <div className="prose prose-invert prose-sm max-w-none prose-headings:text-white prose-strong:text-white prose-li:text-secondary prose-p:text-secondary">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>{markdown}</ReactMarkdown>
            </div>
          </div>
        ) : (
          <div className="space-y-3">
            {chapters.length > 0 ? (
              chapters.map((chapter) => (
                <ChapterCard
                  key={chapter.chapter_no}
                  chapter={chapter}
                  highlightScr={chapter.chapter_no === 1}
                />
              ))
            ) : (
              <div className="rounded-xl border border-white/5 bg-white/[0.02] p-6">
                <p className="text-sm text-tertiary">
                  파싱된 챕터가 없습니다. 원본 Markdown을 확인해주세요.
                </p>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
