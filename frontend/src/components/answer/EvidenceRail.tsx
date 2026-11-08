import type { Citation } from "@/api/types";
import { cn } from "@/lib/utils";
import { BookOpen, Check, ChevronDown, Copy } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { citationLocation, verificationStyle } from "./source-utils";

function EvidenceSkeleton() {
  return (
    <div className="space-y-5 px-4 py-4" aria-hidden>
      {[0, 1, 2].map((row) => (
        <div key={row} className="flex gap-3 motion-safe:animate-pulse">
          <div className="mt-0.5 size-5 shrink-0 rounded bg-muted" />
          <div className="min-w-0 flex-1 space-y-2">
            <div className="h-2.5 w-2/3 rounded-full bg-muted" />
            <div className="h-2 w-1/3 rounded-full bg-muted/80" />
            <div className="h-2 w-full rounded-full bg-muted/60" />
            <div className="h-2 w-4/5 rounded-full bg-muted/60" />
          </div>
        </div>
      ))}
      <span className="sr-only">Loading sources</span>
    </div>
  );
}

export function EvidenceRail({
  citations,
  question,
  loading = false,
  selectedIndex,
  onSelect,
  inSheet = false,
  className,
}: {
  citations: Citation[];
  question?: string;
  loading?: boolean;
  selectedIndex: number | null;
  onSelect: (index: number) => void;
  inSheet?: boolean;
  className?: string;
}) {
  const [copied, setCopied] = useState<number | null>(null);
  const listRef = useRef<HTMLOListElement>(null);

  useEffect(() => {
    if (selectedIndex === null) return;
    const row = listRef.current?.querySelector<HTMLElement>(
      `[data-source-index="${selectedIndex}"]`,
    );
    row?.scrollIntoView({
      block: "nearest",
      behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches
        ? "auto"
        : "smooth",
    });
  }, [selectedIndex]);

  const copyPassage = (citation: Citation, index: number) => {
    void navigator.clipboard
      ?.writeText(citation.excerpt)
      .then(() => {
        setCopied(index);
        toast("Passage copied");
        window.setTimeout(() => setCopied(null), 1600);
      })
      .catch(() => toast.error("Could not copy the passage"));
  };

  return (
    <aside
      className={cn(
        "kos-sources-panel",
        inSheet && "in-sheet flex w-full flex-col",
        className,
      )}
    >
      <header className="kos-sources-header">
        <h2>Sources</h2>
        {citations.length > 0 ? (
          <span className="kos-sources-count">{citations.length}</span>
        ) : null}
        {loading && citations.length === 0 ? (
          <span className="ml-auto font-mono text-[10px] text-muted-foreground">
            retrieving
          </span>
        ) : null}
      </header>

      <div className="chat-scroll min-h-0 flex-1 overflow-y-auto">
        {question ? (
          <p className="line-clamp-2 border-b border-border/60 px-5 py-3 text-[11.5px] leading-5 text-muted-foreground">
            “{question}”
          </p>
        ) : null}

        {loading && citations.length === 0 ? <EvidenceSkeleton /> : null}

        {!loading && citations.length === 0 ? (
          <div className="kos-sources-empty">
            <BookOpen />
            <h3>{question ? "No passages cited" : "No sources yet"}</h3>
            <p>
              {question
                ? "This answer did not reference a retrieved document."
                : "Ask a question and the passages behind the answer will collect here."}
            </p>
          </div>
        ) : null}

        {citations.length > 0 ? (
          <ol ref={listRef}>
            {citations.map((citation, index) => {
              const selected = selectedIndex === index;
              const verification = verificationStyle(citation.verification);
              return (
                <li
                  key={`${citation.chunkId}-${index}`}
                  className="border-b border-border/60 last:border-b-0"
                >
                  <button
                    type="button"
                    className={cn(
                      "flex w-full items-start gap-2.5 px-5 py-3 text-left transition-colors hover:bg-[var(--kos-hover)]",
                      selected && "bg-[var(--kos-active)]",
                    )}
                    onClick={() => onSelect(index)}
                    data-source-index={index}
                    aria-expanded={selected}
                    aria-label={`Source ${index + 1}: ${citation.filename}`}
                  >
                    <span className="mt-0.5 inline-flex size-5 shrink-0 items-center justify-center rounded bg-muted font-mono text-[9.5px] text-muted-foreground">
                      {index + 1}
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="flex items-center gap-2">
                        <span className="min-w-0 flex-1 truncate text-[12px] font-medium text-foreground">
                          {citation.filename}
                        </span>
                        {verification ? (
                          <span
                            className={cn(
                              "inline-flex shrink-0 items-center gap-1 text-[9px] tracking-wide uppercase",
                              verification.className,
                            )}
                          >
                            <span
                              className={cn(
                                "size-1 rounded-full",
                                verification.dotClassName,
                              )}
                            />
                            {verification.label}
                          </span>
                        ) : null}
                      </span>
                      <span className="mt-0.5 block font-mono text-[10px] text-muted-foreground">
                        {citationLocation(citation)}
                      </span>
                      {!selected ? (
                        <span className="mt-1.5 line-clamp-2 text-[11px] leading-5 text-muted-foreground">
                          {citation.excerpt}
                        </span>
                      ) : null}
                    </span>
                    <ChevronDown
                      className={cn(
                        "mt-1 size-3.5 shrink-0 text-muted-foreground/60 transition-transform",
                        selected && "rotate-180",
                      )}
                    />
                  </button>

                  {selected ? (
                    <div className="px-5 pb-4">
                      <div className="overflow-hidden rounded-md bg-muted/70">
                        <div className="chat-scroll max-h-[min(38vh,320px)] overflow-y-auto px-3 py-2.5">
                          <p className="text-[12px] leading-6 whitespace-pre-wrap text-foreground/85">
                            {citation.excerpt}
                          </p>
                        </div>
                        <div className="flex justify-end border-t border-border/50 px-2 py-1.5">
                          <button
                            type="button"
                            className="answer-action"
                            onClick={() => copyPassage(citation, index)}
                          >
                            {copied === index ? (
                              <Check className="size-3.5" />
                            ) : (
                              <Copy className="size-3.5" />
                            )}
                            {copied === index ? "Copied" : "Copy passage"}
                          </button>
                        </div>
                      </div>
                    </div>
                  ) : null}
                </li>
              );
            })}
          </ol>
        ) : null}
      </div>
    </aside>
  );
}
