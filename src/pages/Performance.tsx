import { AppShell } from "@/components/AppShell";
import { PageBody, PageHeader, Workspace } from "@/components/system/layout";
import { Bar, Callout, EmptyNote, Panel, Stat } from "@/components/system/panels";
import { Button } from "@/components/ui/button";
import type { MetricsSnapshot } from "@/api/types";
import { useTelemetry } from "@/hooks/use-telemetry";
import { formatCount, formatMs, formatPercent } from "@/lib/format";
import { Loader2, RefreshCw } from "lucide-react";

function StageBreakdown({ metrics }: { metrics: MetricsSnapshot }) {
  const stages = metrics.stages;
  if (stages.length === 0) {
    return (
      <EmptyNote>
        No completed queries have produced stage timings yet.
      </EmptyNote>
    );
  }

  const max = Math.max(...stages.map((stage) => stage.ms ?? 0), 0.001);

  return (
    <ul className="space-y-2">
      {stages.map((stage) => (
        <li key={stage.label}>
          <div className="flex items-center gap-3 text-[11.5px]">
            <span className="min-w-0 flex-1 truncate">{stage.label}</span>
            <span className="term-dim w-14 text-right tabular-nums">
              {formatMs(stage.ms)}
            </span>
          </div>
          <Bar
            fraction={(stage.ms ?? 0) / max}
            tone={stage.ms !== undefined && stage.ms === max ? "warn" : "info"}
            className="mt-1"
          />
        </li>
      ))}
    </ul>
  );
}

function Outcomes({ metrics }: { metrics: MetricsSnapshot }) {
  const rows = [
    {
      label: "Answered",
      value: metrics.answers,
      tone: "ok" as const,
      hint: "evidence gate passed",
    },
    {
      label: "Answered with uncertainty",
      value: metrics.answersWithUncertainty,
      tone: "warn" as const,
      hint: "partial evidence, no abstention",
    },
    {
      label: "Abstained",
      value: metrics.abstentions,
      tone: "warn" as const,
      hint: "no unsupported answer generated",
    },
    {
      label: "Errors",
      value: metrics.errors,
      tone: "bad" as const,
      hint: "failed requests",
    },
  ];

  const total = rows.reduce((sum, row) => sum + (row.value ?? 0), 0);
  if (total === 0) {
    return <EmptyNote>No query outcomes recorded yet.</EmptyNote>;
  }

  return (
    <ul className="space-y-3">
      {rows.map((row) => {
        const value = row.value ?? 0;
        return (
          <li key={row.label}>
            <div className="flex items-center gap-2 text-[11.5px]">
              <span className="min-w-0 flex-1 truncate">{row.label}</span>
              <span className="term-dim text-[10.5px]">{row.hint}</span>
              <span className="w-20 text-right tabular-nums">
                {formatCount(row.value)}
                <span className="term-dim ml-1.5 text-[10.5px]">
                  {formatPercent(total ? value / total : undefined)}
                </span>
              </span>
            </div>
            <Bar
              fraction={total ? value / total : 0}
              tone={row.tone}
              className="mt-1"
            />
          </li>
        );
      })}
    </ul>
  );
}

function PerformanceWorkspace() {
  const { metrics, loading, error, refresh } = useTelemetry();

  return (
    <Workspace>
      <PageHeader
        title="Performance"
        description="Query latency, pipeline stages and answer outcomes."
      >
        <Button size="sm" variant="outline" className="h-7 text-[11px]" onClick={refresh}>
          <RefreshCw className="size-3.5" />
          Refresh
        </Button>
      </PageHeader>

      <PageBody>
        {loading && !metrics ? (
          <div className="flex items-center gap-2 py-6 text-[12px] text-muted-foreground">
            <Loader2 className="size-3.5 animate-spin" />
            Loading metrics…
          </div>
        ) : error && !metrics ? (
          <Callout tone="bad" title="Could not load metrics">
            {error}
          </Callout>
        ) : metrics ? (
          <>
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-6">
              <Stat
                label="p50 latency"
                value={formatMs(metrics.latency.p50)}
                hint="median"
              />
              <Stat label="p95 latency" value={formatMs(metrics.latency.p95)} />
              <Stat
                label="p99 latency"
                value={formatMs(metrics.latency.p99)}
                hint={metrics.latency.p99 === undefined ? "not reported" : undefined}
              />
              <Stat label="Queries" value={formatCount(metrics.queries)} />
              <Stat
                label="Abstentions"
                value={formatCount(metrics.abstentions)}
                tone="warn"
              />
              <Stat label="Errors" value={formatCount(metrics.errors)} tone="bad" />
            </div>

            <Panel
              title="Stage breakdown"
              description="Mean time spent in each stage of the query pipeline"
            >
              <StageBreakdown metrics={metrics} />
            </Panel>

            <Panel
              title="Answer outcomes"
              description="All three decisions the evidence gate can produce"
            >
              <Outcomes metrics={metrics} />
            </Panel>

          </>
        ) : (
          <EmptyNote>No metrics available.</EmptyNote>
        )}
      </PageBody>
    </Workspace>
  );
}

export default function Performance() {
  return (
    <AppShell>
      {() => <PerformanceWorkspace />}
    </AppShell>
  );
}
