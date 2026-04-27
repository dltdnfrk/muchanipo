import { useEffect, useRef, useState } from "react";
import { listen } from "@tauri-apps/api/event";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { BackendEvent } from "../lib/types";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "./ui/card";

interface ReportViewerProps {
  markdown?: string;
  className?: string;
}

type MermaidApi = typeof import("mermaid").default;

let mermaidApi: Promise<MermaidApi> | null = null;

async function getMermaid() {
  mermaidApi ??= import("mermaid").then((module) => {
    module.default.initialize({
      startOnLoad: false,
      securityLevel: "strict",
      theme: "neutral",
    });
    return module.default;
  });

  return mermaidApi;
}

export function ReportViewer({ markdown, className }: ReportViewerProps) {
  const [streamedMarkdown, setStreamedMarkdown] = useState("");
  const reportRef = useRef<HTMLDivElement>(null);
  const content = markdown ?? streamedMarkdown;

  useEffect(() => {
    if (markdown !== undefined) {
      return;
    }

    let unlisten: (() => void) | undefined;
    void listen<BackendEvent>("backend_event", (event) => {
      const payload = event.payload as BackendEvent;
      if (payload.type === "report_chunk") {
        setStreamedMarkdown((current) => current + payload.delta);
      }
    }).then((cleanup) => {
      unlisten = cleanup;
    });

    return () => {
      unlisten?.();
    };
  }, [markdown]);

  useEffect(() => {
    const root = reportRef.current;
    if (!root) {
      return;
    }

    const blocks = Array.from(root.querySelectorAll("pre code.language-mermaid"));
    for (const block of blocks) {
      const pre = block.parentElement;
      if (!pre || pre.dataset.mermaidRendered === "true") {
        continue;
      }

      const source = block.textContent ?? "";
      const id = `mermaid-${Math.random().toString(36).slice(2)}`;
      void getMermaid().then((mermaid) => mermaid.render(id, source)).then(({ svg }) => {
        pre.dataset.mermaidRendered = "true";
        pre.className = "overflow-x-auto rounded-md border bg-background p-4";
        pre.innerHTML = svg;
      });
    }
  }, [content]);

  return (
    <Card className={className}>
      <CardHeader>
        <CardTitle>Report</CardTitle>
        <CardDescription>
          {content.length > 0 ? "Streaming REPORT.md" : "Waiting for report output"}
        </CardDescription>
      </CardHeader>
      <CardContent>
        <div
          ref={reportRef}
          className="max-w-none space-y-4 text-sm leading-7 [&_a]:underline [&_code]:rounded-sm [&_code]:bg-muted [&_code]:px-1 [&_h1]:text-2xl [&_h1]:font-semibold [&_h2]:text-xl [&_h2]:font-semibold [&_h3]:text-lg [&_h3]:font-semibold [&_li]:ml-5 [&_ol]:list-decimal [&_pre]:overflow-x-auto [&_pre]:rounded-md [&_pre]:bg-muted [&_pre]:p-4 [&_ul]:list-disc"
        >
          {content.length > 0 ? (
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{content}</ReactMarkdown>
          ) : (
            <div className="rounded-md border border-dashed p-5 text-sm text-muted-foreground">
              Markdown chunks from the backend will render here.
            </div>
          )}
        </div>
      </CardContent>
    </Card>
  );
}
