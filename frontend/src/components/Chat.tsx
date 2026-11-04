import { useCallback, useEffect, useRef, useState } from "react";
import { askKnowledgeStream } from "@/api/knowledge";
import type { ChatResponse } from "@/api/types";
import { Answer } from "@/components/Answer";
import { Button } from "@/components/ui/button";
import { Check, CornerDownLeft, Loader2 } from "lucide-react";

interface Turn { id: string; question: string; response: ChatResponse }

/** Stages shown while a question is in flight, so the wait reads as progress. */
const PROCESS_STEPS = ["Parsing query", "Retrieving chunks", "Reranking evidence", "Composing answer"];

function ProcessingTrace({ step, elapsed, candidates }: { step: number; elapsed: number; candidates: number | null }) {
  return (
    <div className="rounded-lg border border-border bg-card px-3 py-2.5">
      <div className="flex items-center justify-between text-[10.5px] font-medium tracking-[0.14em] text-muted-foreground uppercase">
        <span>retrieval pipeline</span>
        <span className="tabular-nums tracking-normal normal-case">{elapsed.toFixed(1)}s</span>
      </div>
      <ul className="mt-2 space-y-1.5">
        {PROCESS_STEPS.map((label, index) => {
          const done = index < step;
          const active = index === step;
          return (
            <li
              key={label}
              className={"flex items-center gap-2 text-[12px] leading-4 " + (done ? "text-foreground/75" : active ? "text-foreground" : "text-muted-foreground/45")}
            >
              <span className="flex size-3.5 shrink-0 items-center justify-center">
                {done ? (
                  <Check className="size-3 text-[var(--term-ok)]" strokeWidth={3} />
                ) : active ? (
                  <Loader2 className="size-3 animate-spin text-[var(--term-ok)]" />
                ) : (
                  <span className="text-[9px] leading-none">○</span>
                )}
              </span>
              <span className="flex-1">{label}</span>
              {index === 1 && candidates !== null ? (
                <span className="term-dim text-[10.5px] tabular-nums">{candidates} candidate{candidates === 1 ? "" : "s"}</span>
              ) : null}
            </li>
          );
        })}
      </ul>
    </div>
  );
}

export function Chat() {
  const [turns, setTurns] = useState<Turn[]>([]);
  const [input, setInput] = useState("");
  const [pending, setPending] = useState(false);
  const [streamingAnswer, setStreamingAnswer] = useState("");
  const [step, setStep] = useState(0);
  const [elapsed, setElapsed] = useState(0);
  const [candidates, setCandidates] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const counter = useRef(0);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => () => abortRef.current?.abort(), []);
  useEffect(() => { if (scrollRef.current) scrollRef.current.scrollTop = scrollRef.current.scrollHeight; }, [turns, pending]);
  useEffect(() => {
    if (!pending) return;
    const startedAt = Date.now();
    const clock = window.setInterval(() => setElapsed((Date.now() - startedAt) / 1000), 100);
    // Advance the trace while retrieval is silent; real stream events can move it further.
    const stages = window.setInterval(() => setStep((current) => (current >= 2 ? current : current + 1)), 800);
    return () => { window.clearInterval(clock); window.clearInterval(stages); };
  }, [pending]);

  const submit = useCallback(async (event?: React.FormEvent) => {
    event?.preventDefault();
    const question = input.trim();
    if (!question || pending) return;
    setInput(""); setPending(true); setStreamingAnswer(""); setError(null);
    setStep(0); setElapsed(0); setCandidates(null);
    const controller = new AbortController();
    abortRef.current = controller;
    try {
      const response = await askKnowledgeStream(
        question,
        controller.signal,
        (token) => setStreamingAnswer((current) => current + token),
        (progress) => {
          if (progress.phase === "retrieved") {
            setCandidates(progress.citations ?? 0);
            setStep((current) => Math.max(current, 2));
          } else {
            setStep(3);
          }
        },
      );
      counter.current += 1;
      setTurns((current) => [...current, { id: `turn-${counter.current}`, question, response }]);
    } catch (value) {
      if (!controller.signal.aborted) setError(value instanceof Error ? value.message : "Query failed");
    } finally {
      if (!controller.signal.aborted) { setPending(false); setStreamingAnswer(""); }
    }
  }, [input, pending]);

  const inputKeyDown = useCallback((event: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === "Enter") {
      event.preventDefault();
      submit();
    }
  }, [submit]);

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <header className="shrink-0 border-b border-border px-4 py-3">
        <div className="mx-auto w-full max-w-3xl"><h2 className="text-[13px] font-semibold tracking-tight">Ask your Knowledge Base</h2></div>
      </header>
      <div ref={scrollRef} className="term-grid min-h-0 flex-1 overflow-y-auto px-4 py-5">
        <div className="mx-auto w-full max-w-3xl space-y-7">
          {turns.length === 0 && !pending ? (
            <div className="flex min-h-[320px] items-center justify-center text-center">
              <div className="max-w-lg"><h1 className="text-xl font-bold tracking-tight">Ask your documents</h1><p className="mt-2 text-[13px] leading-6 text-muted-foreground">Ask a question about indexed documents. Answers include the evidence used by retrieval.</p></div>
            </div>
          ) : null}
          {turns.map((turn) => (
            <div key={turn.id} className="space-y-3">
              <div className="flex items-start gap-2"><span className="term-dim shrink-0 text-[12px] leading-6">user</span><span className="text-[var(--term-ok)]">❯</span><span className="text-[12.5px] leading-6 font-medium">{turn.question}</span></div>
              <Answer response={turn.response} onOpenSource={() => undefined} />
            </div>
          ))}
          {pending ? (
            <div className="space-y-2">
              <div className="flex items-start gap-2">
                <span className="term-dim shrink-0 text-[12px] leading-6">ai</span>
                <div className="min-w-0 flex-1 space-y-2">
                  <ProcessingTrace step={step} elapsed={elapsed} candidates={candidates} />
                  {streamingAnswer ? <div className="rounded-lg border border-border bg-card px-3 py-3 text-[12.5px] leading-6 whitespace-pre-wrap">{streamingAnswer}</div> : null}
                </div>
              </div>
            </div>
          ) : null}
          {error ? <div className="rounded-md border border-[var(--term-bad)]/40 bg-[var(--term-bad)]/10 px-3 py-2 text-[11.5px] text-[var(--term-bad)]">{error}</div> : null}
        </div>
      </div>
      <div className="shrink-0 border-t border-border bg-card px-4 py-3">
        <form className="mx-auto flex w-full max-w-3xl items-end gap-2 rounded-lg border border-border bg-background px-3 py-2" onSubmit={(event) => void submit(event)}>
          <span className="term-ok pb-1.5 text-[14px] leading-5 font-bold">❯</span>
          <textarea value={input} onChange={(event) => setInput(event.target.value)} onKeyDown={inputKeyDown} disabled={pending} rows={1} placeholder="Ask about your indexed documents…" className="min-h-[28px] flex-1 resize-none bg-transparent py-1 text-[13px] leading-6 outline-none" />
          <Button type="submit" size="sm" disabled={pending || !input.trim()}>{pending ? <Loader2 className="size-3.5 animate-spin" /> : <CornerDownLeft className="size-3.5" />} Ask</Button>
        </form>
      </div>
    </div>
  );
}
