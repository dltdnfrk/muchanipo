import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

export default function ReportView() {
  const { runId } = useParams<{ runId: string }>();
  const navigate = useNavigate();
  const [markdown, setMarkdown] = useState<string>("");
  const [reportPath, setReportPath] = useState<string>("");
  const [chapterCount, setChapterCount] = useState<number>(0);
  const [topic, setTopic] = useState<string>("");

  useEffect(() => {
    if (!runId) return;
    try {
      setMarkdown(localStorage.getItem(`run:${runId}:report`) || "");
      setReportPath(localStorage.getItem(`run:${runId}:report_path`) || "");
      setChapterCount(Number(localStorage.getItem(`run:${runId}:chapter_count`) || "0"));
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
    URL.revokeObjectURL(url);
  };

  if (!markdown) {
    return (
      <div className="flex min-h-screen flex-col items-center justify-center gap-4 bg-[#15141B] px-4">
        <p className="text-[#8A8599]">보고서를 찾을 수 없습니다.</p>
        <button
          onClick={() => navigate("/")}
          className="rounded-lg border border-[#2A2833] bg-[#1E1D26] px-4 py-2 text-sm text-[#FFB347] hover:border-[#FFB347]"
        >
          새 리서치 시작
        </button>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-[#15141B] px-4 py-10">
      <div className="mx-auto max-w-4xl">
        <div className="mb-8 flex flex-col items-start justify-between gap-4 md:flex-row md:items-center">
          <div>
            <h1 className="text-2xl font-bold text-[#E8E0D0]">
              {topic || "Muchanipo 보고서"}
            </h1>
            <p className="mt-1 text-xs text-[#6E6B7A]">
              {chapterCount} chapters · Run ID: {runId}
              {reportPath && (
                <>
                  {" · "}
                  <span className="text-[#5A5669]">{reportPath}</span>
                </>
              )}
            </p>
          </div>
          <div className="flex gap-2">
            <button
              onClick={() => navigate("/")}
              className="rounded-lg border border-[#2A2833] bg-[#1E1D26] px-4 py-2 text-sm font-medium text-[#E8E0D0] transition hover:border-[#FFB347] hover:text-[#FFB347]"
            >
              새 리서치
            </button>
            <button
              onClick={exportMarkdown}
              className="rounded-lg bg-[#FFB347] px-4 py-2 text-sm font-semibold text-[#15141B] transition hover:bg-[#e6a03f]"
            >
              Markdown 다운로드
            </button>
          </div>
        </div>

        <div className="rounded-xl border border-[#2A2833] bg-[#1E1D26] p-8">
          <article className="prose prose-invert prose-sm max-w-none prose-headings:text-[#E8E0D0] prose-strong:text-[#FFB347] prose-em:text-[#8A8599] prose-li:text-[#D0CABB]">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{markdown}</ReactMarkdown>
          </article>
        </div>
      </div>
    </div>
  );
}
