import { AppShell } from "@/components/AppShell";
import { PageBody, PageHeader, Workspace } from "@/components/system/layout";
import { Bar, Callout, EmptyNote, Panel, Stat } from "@/components/system/panels";
import { StatusDot, type Tone } from "@/components/StatusDot";
import type { MetricsSnapshot, RagIndex } from "@/api/types";
import { useTelemetry } from "@/hooks/use-telemetry";
import { formatCount, formatDateTime, formatPercent } from "@/lib/format";
import { cn } from "@/lib/utils";
import { Loader2 } from "lucide-react";

function OutcomeRow({
  label,
  value,
  total,
  tone,
  hint,
}: {
  label: string;
  value: number;
  total: number;
  tone: Tone;
  hint: string;
}) {
  return (
    <li>
      <div className="flex items-center gap-2 text-[11.5px]">
        <span className="min-w-0 flex-1 truncate">{label}</span>
        <span className="term-dim text-[10.5px]">{hint}</span>
        <span className="w-24 text-right tabular-nums">
          {formatCount(value)}
          <span className="term-dim ml-1.5 text-[10.5px]">
            {formatPercent(total ? value / total : undefined)}
          </span>
        </span>
      </div>
      <Bar fraction={total ? value / total : 0} tone={tone} className="mt-1" />
    </li>
  );
}

function EvidenceGate({ metrics }: { metrics: MetricsSnapshot }) {
  const answers = metrics.answers ?? 0;
  const uncertain = metrics.answersWithUncertainty ?? 0;
  const abstained = metrics.abstentions ?? 0;
  const total = answers + uncertain + abstained;

  if (total === 0) {
    return (
      <EmptyNote>
        No outcomes recorded yet. The evidence gate produces one of three
        decisions per query.
      </EmptyNote>
    );
  }

  return (
    <ul className="space-y-3">
      <OutcomeRow
        label="Answer"
        value={answers}
        total={total}
        tone="ok"
        hint="evidence passed"
      />
      <OutcomeRow
        label="Answer with uncertainty"
        value={uncertain}
        total={total}
        tone="warn"
        hint="partial evidence, stated as such"
      />
      <OutcomeRow
        label="Abstain"
        value={abstained}
        total={total}
        tone="warn"
        hint="no unsupported answer generated"
      />
    </ul>
  );
}

function IndexEvaluations({ indexes }: { indexes: RagIndex[] }) {
  if (indexes.length === 0) {
    return <EmptyNote>No index builds reported.</EmptyNote>;
  }

  return (
    <div className="overflow-x-auto rounded-md border border-border bg-background">
      <table className="w-full min-w-[620px] border-collapse text-[11px]">
        <thead>
          <tr className="border-b border-border text-left">
            {["Index", "State", "Validated", "Evaluated", "Evidence score", "Built"].map(
              (heading) => (
                <th
                  key={heading}
                  className="px-3 py-1.5 font-medium text-muted-foreground"
                >
                  {heading}
                </th>
              ),
            )}
          </tr>
        </thead>
        <tbody>
          {indexes.map((index) => (
            <tr key={index.id} className="border-b border-border/60 last:border-0">
              <td className="px-3 py-1.5 font-medium">{index.id}</td>
              <td className="px-3 py-1.5">
                <span className="flex items-center gap-1.5">
                  <StatusDot
                    tone={index.state === "active" ? "ok" : "idle"}
                    pulse={index.state === "building"}
                  />
                  <span className="term-dim">{index.state}</span>
                </span>
              </td>
              <td
                className={cn(
                  "px-3 py-1.5",
                  index.validated ? "text-[var(--term-ok)]" : "term-dim",
                )}
              >
                {index.validated ? "yes" : "no"}
              </td>
              <td
                className={cn(
                  "px-3 py-1.5",
                  index.evaluated ? "text-[var(--term-ok)]" : "term-dim",
                )}
              >
                {index.evaluated ? "yes" : "no"}
              </td>
              <td className="px-3 py-1.5 tabular-nums">
                {index.evaluationScore === undefined
                  ? "—"
                  : formatPercent(index.evaluationScore)}
              </td>
              <td className="term-dim px-3 py-1.5">
                {index.builtAt ? formatDateTime(index.builtAt) : "not built"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function EvaluationsWorkspace() {
  const { metrics, indexes, loading, error } = useTelemetry();
  const queries = metrics?.queries ?? 0;
  const abstentions = metrics?.abstentions ?? 0;
  const errors = metrics?.errors ?? 0;
  const uncertain = metrics?.answersWithUncertainty ?? 0;

  return (
    <Workspace>
      <PageHeader
        title="Evaluations"
        description="How often the system answers, hedges, abstains or fails — plus per-index validation results."
      />

      <PageBody>
        {loading && !metrics ? (
          <div className="flex items-center gap-2 py-6 text-[12px] text-muted-foreground">
            <Loader2 className="size-3.5 animate-spin" />
            Loading evaluation data…
          </div>
        ) : error && !metrics ? (
          <Callout tone="bad" title="Could not load metrics">
            {error}
          </Callout>
        ) : metrics ? (
          <>
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
              <Stat label="Queries" value={formatCount(metrics.queries)} />
              <Stat
                label="Abstention rate"
                value={formatPercent(queries ? abstentions / queries : undefined)}
                hint={`${formatCount(abstentions)} abstentions`}
                tone={abstentions ? "warn" : "ok"}
              />
              <Stat
                label="Hedged answers"
                value={formatCount(metrics.answersWithUncertainty)}
                hint="answer_with_uncertainty"
                tone={uncertain ? "warn" : "ok"}
              />
              <Stat
                label="Errors"
                value={formatCount(metrics.errors)}
                tone={errors ? "bad" : "ok"}
              />
            </div>

            <Panel
              title="Evidence gate outcomes"
              description="Abstention is a feature: unsupported questions are refused rather than guessed"
            >
              <EvidenceGate metrics={metrics} />
            </Panel>

            <Panel
              title="Index validation and evaluation"
              description="Evaluation results for configured index builds"
            >
              <IndexEvaluations indexes={indexes} />
            </Panel>

            <Callout tone="info" title="Evaluation signal">
              Offline index metrics and online answer outcomes are kept with the
              workspace trace history so regressions can be compared before activation.
            </Callout>
          </>
        ) : (
          <EmptyNote>No evaluation data available.</EmptyNote>
        )}
      </PageBody>
    </Workspace>
  );
}

export default function Evaluations() {
  return (
    <AppShell>
      {() => <EvaluationsWorkspace />}
    </AppShell>
  );
}
