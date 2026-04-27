import type { Chapter } from "../lib/tauriClient";

interface ChapterCardProps {
  chapter: Chapter;
  highlightScr?: boolean;
}

export default function ChapterCard({ chapter, highlightScr }: ChapterCardProps) {
  return (
    <div className="rounded-xl border border-[#2A2833] bg-[#1E1D26] p-6 shadow-sm">
      <div className="mb-4 flex items-center gap-3">
        <span className="inline-flex h-8 w-8 items-center justify-center rounded-full bg-[#FFB347] text-sm font-bold text-[#15141B]">
          {chapter.chapter_no}
        </span>
        <h2 className="text-lg font-semibold text-[#E8E0D0]">{chapter.title}</h2>
      </div>

      <p className="mb-4 text-base font-bold leading-relaxed text-[#E8E0D0]">
        {chapter.lead_claim}
      </p>

      {chapter.body_claims.length > 0 && (
        <ul className="mb-4 list-disc space-y-1 pl-5 text-sm text-[#C8C0B0]">
          {chapter.body_claims.map((claim, idx) => (
            <li key={idx}>{claim}</li>
          ))}
        </ul>
      )}

      {highlightScr && chapter.scr && (
        <div className="mb-4 grid grid-cols-1 gap-3 md:grid-cols-3">
          <div className="rounded-lg bg-[#15141B] p-4">
            <div className="mb-1 text-xs font-semibold uppercase tracking-wide text-[#FFB347]">
              Situation
            </div>
            <p className="text-sm text-[#E8E0D0]">{chapter.scr.situation}</p>
          </div>
          <div className="rounded-lg bg-[#15141B] p-4">
            <div className="mb-1 text-xs font-semibold uppercase tracking-wide text-[#FFB347]">
              Complication
            </div>
            <p className="text-sm text-[#E8E0D0]">{chapter.scr.complication}</p>
          </div>
          <div className="rounded-lg bg-[#15141B] p-4">
            <div className="mb-1 text-xs font-semibold uppercase tracking-wide text-[#FFB347]">
              Resolution
            </div>
            <p className="text-sm text-[#E8E0D0]">{chapter.scr.resolution}</p>
          </div>
        </div>
      )}

      {chapter.source_layers.length > 0 && (
        <div className="mt-4 border-t border-[#2A2833] pt-3">
          <p className="text-xs text-[#6E6B7A]">
            Sources: {chapter.source_layers.join(", ")}
          </p>
        </div>
      )}
    </div>
  );
}
