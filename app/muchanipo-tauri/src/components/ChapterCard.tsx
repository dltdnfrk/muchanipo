import type { Chapter } from "../lib/tauriClient";

interface ChapterCardProps {
  chapter: Chapter;
  highlightScr?: boolean;
}

export default function ChapterCard({ chapter, highlightScr }: ChapterCardProps) {
  return (
    <article className="rounded-xl border border-white/5 bg-white/[0.02] p-6">
      {/* Header */}
      <header className="mb-4 flex items-center gap-3">
        <span className="inline-flex h-7 w-7 items-center justify-center rounded-full border border-white/15 bg-white/5 font-mono text-xs text-white">
          {chapter.chapter_no}
        </span>
        <h2 className="text-base font-semibold tracking-tight text-white">
          {chapter.title}
        </h2>
        {chapter.framework && (
          <span className="ml-auto rounded-full border border-white/10 bg-white/[0.03] px-2.5 py-0.5 text-[10px] uppercase tracking-wider text-tertiary">
            {chapter.framework}
          </span>
        )}
      </header>

      {/* Lead claim */}
      <p className="mb-5 text-[15px] font-medium leading-relaxed text-white">
        {chapter.lead_claim}
      </p>

      {/* SCR (Chapter 1) */}
      {highlightScr && chapter.scr && (
        <div className="mb-5 overflow-hidden rounded-xl border border-white/5">
          {(["situation", "complication", "resolution"] as const).map((key, idx) => {
            const text = chapter.scr?.[key];
            if (!text) return null;
            return (
              <div
                key={key}
                className={`flex gap-4 bg-white/[0.02] px-4 py-3 ${
                  idx > 0 ? "border-t border-white/5" : ""
                }`}
              >
                <span className="w-28 shrink-0 text-[10px] font-semibold uppercase tracking-wider text-tertiary">
                  {key}
                </span>
                <p className="flex-1 text-sm leading-relaxed text-secondary">{text}</p>
              </div>
            );
          })}
        </div>
      )}

      {/* Body claims */}
      {chapter.body_claims.length > 0 && (
        <ul className="mb-4 space-y-1.5 text-sm leading-relaxed text-secondary">
          {chapter.body_claims.map((claim, idx) => (
            <li key={idx} className="flex gap-2.5">
              <span className="mt-2 h-1 w-1 shrink-0 rounded-full bg-white/30" />
              <span>{claim}</span>
            </li>
          ))}
        </ul>
      )}

      {/* Sources */}
      {chapter.source_layers.length > 0 && (
        <footer className="mt-4 border-t border-white/5 pt-3">
          <p className="font-mono text-[11px] text-tertiary">
            Sources · {chapter.source_layers.join(" · ")}
          </p>
        </footer>
      )}
    </article>
  );
}
