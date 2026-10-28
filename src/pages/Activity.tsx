import { AppShell } from "@/components/AppShell";
import { PageBody, PageHeader, Workspace } from "@/components/system/layout";
import { EmptyNote, Panel } from "@/components/system/panels";
import { StatusDot, type Tone } from "@/components/StatusDot";
import { useDocuments } from "@/hooks/use-documents";
import { fetchActivity, type ActivityEvent } from "@/api/activity";
import { formatCount } from "@/lib/format";
import { cn } from "@/lib/utils";
import { Loader2 } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

type Kind = "document" | "sync" | "query" | "error";

interface Event {
  id: string;
  kind: Kind;
  at: number;
  title: string;
  detail?: string;
}

const FILTERS: { key: Kind | "all"; label: string }[] = [
  { key: "all", label: "All" },
  { key: "document", label: "Documents" },
  { key: "sync", label: "Sync" },
  { key: "query", label: "Queries" },
  { key: "error", label: "Errors" },
];

const KIND_TONE: Record<Kind, Tone> = {
  document: "info",
  sync: "ok",
  query: "info",
  error: "bad",
};

function dayLabel(epoch: number): string {
  const date = new Date(epoch);
  const today = new Date();
  if (date.toDateString() === today.toDateString()) return "Today";
  const yesterday = new Date(today.getTime() - 86_400_000);
  if (date.toDateString() === yesterday.toDateString()) return "Yesterday";
  return date.toLocaleDateString("en-US", {
    weekday: "short",
    month: "short",
    day: "numeric",
  });
}

function clock(epoch: number): string {
  return new Date(epoch).toLocaleTimeString("en-US", {
    hour: "numeric",
    minute: "2-digit",
  });
}

function ActivityWorkspace() {
  const docs = useDocuments();
  const [apiEvents, setApiEvents] = useState<ActivityEvent[]>([]);
  const [filter, setFilter] = useState<Kind | "all">("all");
  useEffect(() => { const controller = new AbortController(); void fetchActivity(controller.signal).then(setApiEvents).catch(() => undefined); return () => controller.abort(); }, [docs.jobs.length, docs.documents.length]);

  const events = useMemo<Event[]>(() => {
    const list: Event[] = [];
    for (const event of apiEvents) list.push({ id: event.id, kind: event.kind, at: event.createdAt, title: event.title, detail: event.detail });
    const changedDocIds = new Set(docs.changes.map((change) => change.documentId));

    for (const doc of docs.documents) {
      if (doc.status === "failed") {
        list.push({
          id: `${doc.id}-failed`,
          kind: "error",
          at: doc.updatedAt ?? doc.indexedAt ?? 0,
          title: `${doc.filename} sync failed`,
          detail: doc.error,
        });
      } else if (doc.status === "changed" && !changedDocIds.has(doc.id)) {
        list.push({
          id: `${doc.id}-modified`,
          kind: "document",
          at: doc.updatedAt ?? 0,
          title: `${doc.filename} modified`,
          detail: "SHA-256 differs from the indexed content hash",
        });
      }

      if (doc.indexedAt) {
        list.push({
          id: `${doc.id}-indexed`,
          kind: "sync",
          at: doc.indexedAt,
          title: `${doc.filename} indexed`,
          detail: `${formatCount(doc.chunks)} chunks embedded`,
        });
      }
    }

    for (const change of docs.changes) {
      list.push({
        id: `${change.documentId}-change`,
        kind: "document",
        at: change.changedAt,
        title: `${change.filename} modified locally`,
        detail: `${formatCount(change.previousChunks)} → ${formatCount(
          change.currentChunks,
        )} chunks${
          change.reused !== undefined
            ? ` · ${formatCount(change.reused)} reused · ${formatCount(
                change.newlyEmbedded ?? 0,
              )} newly embedded`
            : ""
        }`,
      });
    }

    for (const job of docs.jobs) {
      list.push({
        id: job.id,
        kind: job.status === "failed" ? "error" : "sync",
        at: 0,
        title: `${job.documentName ?? "knowledge base"} ${job.status}`,
        detail: `stage ${job.stage}`,
      });
    }

    return list.sort((a, b) => b.at - a.at).slice(0, 80);
  }, [apiEvents, docs.documents, docs.changes, docs.jobs]);

  const visible = filter === "all" ? events : events.filter((e) => e.kind === filter);
  const grouped = useMemo(() => {
    const map = new Map<string, Event[]>();
    for (const event of visible) {
      const label = dayLabel(event.at);
      const bucket = map.get(label);
      if (bucket) bucket.push(event);
      else map.set(label, [event]);
    }
    return [...map.entries()];
  }, [visible]);

  return (
    <Workspace>
      <PageHeader
        title="Activity"
        description="Modified, embedded, indexed and failed — reconstructed from the API's own records."
      />

      <PageBody>
        <div className="flex flex-wrap items-center gap-1">
          {FILTERS.map((option) => {
            const active = filter === option.key;
            const count =
              option.key === "all"
                ? events.length
                : events.filter((event) => event.kind === option.key).length;
            return (
              <button
                key={option.key}
                type="button"
                onClick={() => setFilter(option.key)}
                className={cn(
                  "rounded-md border px-2 py-1 text-[10.5px] transition-colors",
                  active
                    ? "border-[var(--term-ok)]/50 bg-accent font-medium text-accent-foreground"
                    : "border-border text-muted-foreground hover:bg-accent/40 hover:text-foreground",
                )}
              >
                {option.label}
                <span className="term-dim ml-1 tabular-nums">{count}</span>
              </button>
            );
          })}
        </div>

        {docs.loading ? (
          <div className="flex items-center gap-2 py-6 text-[12px] text-muted-foreground">
            <Loader2 className="size-3.5 animate-spin" />
            Loading activity…
          </div>
        ) : filter === "query" ? (
          <Panel title="Queries">
            <EmptyNote>
              No query events have been recorded yet.
            </EmptyNote>
          </Panel>
        ) : visible.length === 0 ? (
          <Panel>
            <EmptyNote>No activity recorded for this filter.</EmptyNote>
          </Panel>
        ) : (
          grouped.map(([label, items]) => (
            <section key={label} className="space-y-2">
              <p className="term-dim px-1 text-[10px] font-medium tracking-[0.14em] uppercase">
                {label}
              </p>
              <ul className="rounded-lg border border-border bg-card">
                {items.map((event) => (
                  <li
                    key={event.id}
                    className="flex items-start gap-3 border-b border-border/60 px-3 py-2 last:border-0"
                  >
                    <StatusDot
                      tone={KIND_TONE[event.kind]}
                      className="mt-1.5"
                    />
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-[11.5px] font-medium">
                        {event.title}
                      </p>
                      {event.detail ? (
                        <p className="term-dim truncate text-[10.5px]">
                          {event.detail}
                        </p>
                      ) : null}
                    </div>
                    <span className="term-dim shrink-0 text-[10.5px] tabular-nums">
                      {clock(event.at)}
                    </span>
                  </li>
                ))}
              </ul>
            </section>
          ))
        )}

      </PageBody>
    </Workspace>
  );
}

export default function Activity() {
  return (
    <AppShell>
      {() => <ActivityWorkspace />}
    </AppShell>
  );
}
