import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import ChapterCard from "../components/ChapterCard";
import { parseChapterMarkdown } from "../lib/parseChapterMarkdown";
import type { Chapter } from "../lib/tauriClient";

export default function ReportView() {
  const { runId } = useParams<{ runId: string }>();
  const [markdown, setMarkdown] = useState<string>("");
  const [chapters, setChapters] = useState<Chapter[]>([]);
  const [showRaw, setShowRaw] = useState(false);
  const [topic, setTopic] = useState<string>("");

  useEffect(() => {
    if (!runId) return;
    try {
      const md = localStorage.getItem(`run:${runId}:report`) || "";
      setMarkdown(md);
      setChapters(parseChapterMarkdown(md));
      setTopic(localStorage.getItem(`run:${runId}:topic`) || "");
    } catch {
      /* ignore */
    }
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
