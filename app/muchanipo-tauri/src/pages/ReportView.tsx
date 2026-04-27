import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { fetchReport, type FinalReport } from "../lib/tauriClient";
import ChapterCard from "../components/ChapterCard";

export default function ReportView() {
  const { runId } = useParams<{ runId: string }>();
  const [report, setReport] = useState<FinalReport | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!runId) return;
    setLoading(true);
    fetchReport(runId)
      .then((r) => {
        setReport(r);
        setLoading(false);
      })
      .catch((err) => {
        setError(err instanceof Error ? err.message : "보고서를 불러올 수 없습니다.");
        setLoading(false);
      });
  }, [runId]);

  if (loading) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-[#15141B]">
        <div className="h-8 w-8 animate-spin rounded-full border-2 border-[#FFB347] border-t-transparent" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-[#15141B] px-4">
        <p className="text-red-400">{error}</p>
      </div>
    );
  }

  if (!report) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-[#15141B] px-4">
        <p className="text-[#8A8599]">보고서가 없습니다.</p>
      </div>
    );
  }

  const exportMarkdown = () => {
    const lines: string[] = [`# ${report.title}`, ``, `> Brief ID: ${report.brief_id}`, ``];
    for (const ch of report.chapters) {
      lines.push(`## ${ch.chapter_no}. ${ch.title}`);
      lines.push(``);
      lines.push(ch.lead_claim);
      lines.push(``);
      if (ch.body_claims.length) {
        for (const claim of ch.body_claims) {
          lines.push(`- ${claim}`);
        }
        lines.push(``);
      }
      if (ch.scr) {
        lines.push(`**Situation:** ${ch.scr.situation}`);
        lines.push(`**Complication:** ${ch.scr.complication}`);
        lines.push(`**Resolution:** ${ch.scr.resolution}`);
        lines.push(``);
      }
      if (ch.source_layers.length) {
        lines.push(`_Sources: ${ch.source_layers.join(", ")}_`);
        lines.push(``);
      }
    }
    const blob = new Blob([lines.join("\n")], { type: "text/markdown" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${report.title.replace(/\s+/g, "_")}.md`;
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="min-h-screen bg-[#15141B] px-4 py-10">
      <div className="mx-auto max-w-4xl">
        <div className="mb-8 flex flex-col items-start justify-between gap-4 md:flex-row md:items-center">
          <div>
            <h1 className="text-2xl font-bold text-[#E8E0D0]">{report.title}</h1>
            <p className="mt-1 text-sm text-[#8A8599]">Brief ID: {report.brief_id}</p>
          </div>
          <button
            onClick={exportMarkdown}
            className="rounded-lg border border-[#2A2833] bg-[#1E1D26] px-4 py-2 text-sm font-medium text-[#E8E0D0] transition hover:border-[#FFB347] hover:text-[#FFB347]"
          >
            Markdown 다운로드
          </button>
        </div>

        <div className="space-y-6">
          {report.chapters.map((chapter) => (
            <ChapterCard
              key={chapter.chapter_no}
              chapter={chapter}
              highlightScr={chapter.chapter_no === 1}
            />
          ))}
        </div>

        <div className="mt-10 rounded-xl border border-[#2A2833] bg-[#1E1D26] p-6">
          <h3 className="mb-3 text-sm font-semibold text-[#FFB347]">원문 보고서 (Markdown)</h3>
          <div className="prose prose-invert max-w-none prose-sm">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>
              {report.chapters
                .map(
                  (c) =>
                    `## ${c.chapter_no}. ${c.title}\n\n${c.lead_claim}\n\n${c.body_claims
                      .map((b) => `- ${b}`)
                      .join("\n")}`,
                )
                .join("\n\n")}
            </ReactMarkdown>
          </div>
        </div>
      </div>
    </div>
  );
}
