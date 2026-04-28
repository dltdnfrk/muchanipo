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
      <div className="flex min-h-screen flex-col items-center justify-center gap-4 bg-[#15141B] px-4">
        <div className="h-8 w-8 animate-spin rounded-full border-2 border-[#FFB347] border-t-transparent" />
        <p className="text-sm text-[#8A8599]">보고서를 불러오는 중…</p>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-[#15141B] px-4 py-10">
      <div className="mx-auto max-w-4xl">
        <div className="mb-8 flex flex-col items-start justify-between gap-4 md:flex-row md:items-center">
          <div>
            <h1 className="text-2xl font-bold text-[#E8E0D0]">
              {topic || "리서치 보고서"}
            </h1>
            <p className="mt-1 text-sm text-[#8A8599]">Run ID: {runId}</p>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={() => setShowRaw((s) => !s)}
              className="rounded-lg border border-[#2A2833] bg-[#1E1D26] px-3 py-2 text-xs font-medium text-[#E8E0D0] transition hover:border-[#FFB347]"
            >
              {showRaw ? "카드 보기" : "원본 Markdown"}
            </button>
            <button
              onClick={exportMarkdown}
              className="rounded-lg border border-[#2A2833] bg-[#1E1D26] px-3 py-2 text-xs font-medium text-[#E8E0D0] transition hover:border-[#FFB347] hover:text-[#FFB347]"
            >
              다운로드
            </button>
          </div>
        </div>

        {showRaw ? (
          <div className="rounded-xl border border-[#2A2833] bg-[#1E1D26] p-6">
            <div className="prose prose-invert max-w-none prose-sm">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>{markdown}</ReactMarkdown>
            </div>
          </div>
        ) : (
          <div className="space-y-6">
            {chapters.length > 0 ? (
              chapters.map((chapter) => (
                <ChapterCard
                  key={chapter.chapter_no}
                  chapter={chapter}
                  highlightScr={chapter.chapter_no === 1}
                />
              ))
            ) : (
              <div className="rounded-xl border border-[#2A2833] bg-[#1E1D26] p-6">
                <p className="text-sm text-[#8A8599]">
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
