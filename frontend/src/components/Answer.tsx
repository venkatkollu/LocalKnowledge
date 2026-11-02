import type { ChatResponse, Citation } from "@/api/types";
import { sendFeedback } from "@/api/feedback";
import { ThumbsDown, ThumbsUp } from "lucide-react";
import { useState } from "react";

export function Answer({ response, onOpenSource }: { response: ChatResponse; onOpenSource: (citation: Citation) => void }) {
  const [feedback, setFeedback] = useState<1 | -1 | null>(null);
  const [selectedCitation, setSelectedCitation] = useState<Citation | null>(null);
  return (
    <article className="space-y-3 rounded-lg border border-border bg-card px-3 py-3">
      <p className="whitespace-pre-wrap text-[12.5px] leading-6">{response.answer}</p>
      {response.citations.length > 0 ? (
        <div className="border-t border-border pt-2">
          <p className="term-dim mb-1.5 text-[10px] tracking-[0.12em] uppercase">Sources</p>
          <div className="flex flex-wrap gap-1.5">
            {response.citations.map((citation, index) => (
              <button key={citation.chunkId} type="button" onClick={() => { setSelectedCitation(citation); onOpenSource(citation); }} className="rounded border border-border px-2 py-1 text-left text-[10.5px] hover:bg-accent">
                [{index + 1}] {citation.filename}:{citation.lineStart ?? ""}
              </button>
            ))}
          </div>
          {selectedCitation ? <div className="mt-2 rounded-md border border-border bg-background px-3 py-2 text-[11px] leading-5"><p className="term-dim mb-1 font-mono text-[10px]">{selectedCitation.filename}{selectedCitation.lineStart ? ` · lines ${selectedCitation.lineStart}–${selectedCitation.lineEnd ?? selectedCitation.lineStart}` : ""}</p><p className="whitespace-pre-wrap text-muted-foreground">{selectedCitation.excerpt}</p></div> : null}
        </div>
      ) : null}
      <div className="flex items-center gap-1 border-t border-border pt-2">
        <span className="term-dim mr-1 text-[10px]">Was this useful?</span>
        <button type="button" aria-label="Helpful answer" className="rounded p-1 text-muted-foreground hover:bg-accent" onClick={() => { setFeedback(1); if (response.traceId) void sendFeedback(response.traceId, 1).catch(() => undefined); }}><ThumbsUp className={feedback === 1 ? "size-3.5 text-[var(--term-ok)]" : "size-3.5"} /></button>
        <button type="button" aria-label="Unhelpful answer" className="rounded p-1 text-muted-foreground hover:bg-accent" onClick={() => { setFeedback(-1); if (response.traceId) void sendFeedback(response.traceId, -1).catch(() => undefined); }}><ThumbsDown className={feedback === -1 ? "size-3.5 text-[var(--term-bad)]" : "size-3.5"} /></button>
      </div>
    </article>
  );
}
