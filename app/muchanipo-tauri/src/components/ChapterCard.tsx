import type { Chapter } from "../lib/tauriClient";
import { compactEvidenceId } from "../lib/reportPresentation";

interface ChapterCardProps {
  chapter: Chapter;
  highlightScr?: boolean;
}

export default function ChapterCard({ chapter, highlightScr }: ChapterCardProps) {
  return (
    <article className="chapter-card p-6 md:p-7">
      {/* Header */}
      <header className="mb-5 grid gap-3 sm:grid-cols-[auto_1fr_auto] sm:items-center">
        <span className="inline-flex h-8 w-8 items-center justify-center rounded-md border border-white/15 bg-white/5 font-mono text-xs text-white">
          {chapter.chapter_no}
        </span>
        <h2 className="display-serif text-[24px] font-semibold leading-tight text-white">
          {chapter.title}
        </h2>
        {chapter.framework && (
          <span className="rounded-md border border-white/10 bg-white/[0.03] px-2.5 py-1 text-[10px] uppercase tracking-wider text-tertiary">
            {chapter.framework}
          </span>
        )}
      </header>

      {/* Lead claim */}
      <p className="mb-5 border-l-2 border-[var(--accent-warm)] pl-4 text-[17px] font-medium leading-8 text-white">
        {chapter.lead_claim}
      </p>

      {/* SCR (Chapter 1) */}
      {highlightScr && chapter.scr && (
        <div className="mb-5 overflow-hidden rounded-lg border border-white/5">
          {(["situation", "complication", "resolution"] as const).map((key, idx) => {
            const text = chapter.scr?.[key];
            if (!text) return null;
            return (
              <div
                key={key}
                className={`grid gap-2 bg-white/[0.02] px-4 py-3 sm:grid-cols-[128px_1fr] ${
                  idx > 0 ? "border-t border-white/5" : ""
                }`}
              >
                <span className="text-[10px] font-semibold uppercase tracking-wider text-tertiary">
                  {key}
                </span>
                <p className="text-sm leading-7 text-secondary">{text}</p>
              </div>
            );
          })}
        </div>
      )}

      {/* Body claims */}
      {chapter.body_claims.length > 0 && (
        <ul className="mb-4 space-y-2 text-sm leading-7 text-secondary">
          {chapter.body_claims.map((claim, idx) => (
            <li key={idx} className="flex gap-2.5">
              <span className="mt-3 h-1.5 w-1.5 shrink-0 rounded-full bg-[var(--accent-warm)]" />
              <span>{claim}</span>
            </li>
          ))}
        </ul>
      )}

      {/* Sources */}
      {chapter.source_layers.length > 0 && (
        <footer className="mt-5 border-t border-white/5 pt-4">
          <div className="flex flex-wrap gap-1.5">
            {chapter.source_layers.slice(0, 8).map((source, index) => (
              <span
                key={`${source}-${index}`}
                className="rounded-md border border-white/10 bg-white/[0.03] px-2 py-1 font-mono text-[10px] text-tertiary"
                title={source}
              >
                {compactEvidenceId(source)}
              </span>
            ))}
            {chapter.source_layers.length > 8 && (
              <span className="rounded-md border border-white/10 bg-white/[0.03] px-2 py-1 text-[10px] text-tertiary">
                +{chapter.source_layers.length - 8}
              </span>
            )}
          </div>
        </footer>
      )}
    </article>
  );
}
