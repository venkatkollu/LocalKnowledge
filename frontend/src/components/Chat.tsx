import { useCallback, useEffect, useRef, useState } from "react";
import { askKnowledgeStream } from "@/api/knowledge";
import type { ChatResponse } from "@/api/types";
import { Answer } from "@/components/Answer";
import { Button } from "@/components/ui/button";
import { CornerDownLeft, Loader2 } from "lucide-react";

interface Turn { id: string; question: string; response: ChatResponse }

export function Chat() {
  const [turns, setTurns] = useState<Turn[]>([]);
  const [input, setInput] = useState("");
  const [pending, setPending] = useState(false);
  const [streamingAnswer, setStreamingAnswer] = useState("");
  const [error, setError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const counter = useRef(0);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => () => abortRef.current?.abort(), []);
  useEffect(() => { if (scrollRef.current) scrollRef.current.scrollTop = scrollRef.current.scrollHeight; }, [turns, pending]);

  const submit = useCallback(async (event?: React.FormEvent) => {
    event?.preventDefault();
    const question = input.trim();
    if (!question || pending) return;
    setInput(""); setPending(true); setStreamingAnswer(""); setError(null);
    const controller = new AbortController();
    abortRef.current = controller;
    try {
      const response = await askKnowledgeStream(question, controller.signal, (token) => setStreamingAnswer((current) => current + token));
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
          {pending ? <div className="space-y-2"><div className="flex items-center gap-2 text-[12px] text-muted-foreground"><Loader2 className="size-3.5 animate-spin" /> Streaming answer…</div>{streamingAnswer ? <div className="rounded-lg border border-border bg-card px-3 py-3 text-[12.5px] leading-6 whitespace-pre-wrap">{streamingAnswer}</div> : null}</div> : null}
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
