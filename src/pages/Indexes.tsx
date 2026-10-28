import { AppShell } from "@/components/AppShell";
import { PageBody, PageHeader, Workspace } from "@/components/system/layout";
import { Callout, EmptyNote, KeyValue, Panel } from "@/components/system/panels";
import { StatusDot, type Tone } from "@/components/StatusDot";
import { Button } from "@/components/ui/button";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import type { IndexState, RagIndex } from "@/api/types";
import {
  useTelemetry,
  type IndexAction,
} from "@/hooks/use-telemetry";
import { formatCount, formatDateTime, formatPercent } from "@/lib/format";
import { cn } from "@/lib/utils";
import {
  Blocks,
  ChevronRight,
  Loader2,
  Plus,
  RefreshCw,
  Undo2,
} from "lucide-react";

const STATE_TONE: Record<IndexState, Tone> = {
  building: "info",
  ready: "ok",
  active: "ok",
  retired: "idle",
};

const LIFECYCLE = [
  "create",
  "build",
  "validate",
  "evaluate",
  "activate",
  "rollback",
];

function IndexCard({
  index,
  busy,
  onAction,
}: {
  index: RagIndex;
  busy: boolean;
  onAction: (id: string, action: IndexAction) => void;
}) {
  const isActive = index.state === "active";
  const isBuilding = index.state === "building";

  return (
    <Collapsible className="group rounded-lg border border-border bg-card">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5 px-3 py-2.5">
        <StatusDot tone={STATE_TONE[index.state]} pulse={isBuilding} />
        <span className="text-[12.5px] font-semibold tracking-tight">
          {index.id}
        </span>
        <span
          className={cn(
            "rounded-full border px-2 py-0.5 text-[9.5px] tracking-wide uppercase",
            isActive
              ? "border-[var(--term-ok)]/40 text-[var(--term-ok)]"
              : isBuilding
                ? "border-[var(--term-info)]/40 text-[var(--term-info)]"
                : "border-border text-muted-foreground",
          )}
        >
          {index.state}
        </span>
        {index.notes ? (
          <span className="term-dim hidden truncate text-[10.5px] lg:inline">
            {index.notes}
          </span>
        ) : null}

        <div className="ml-auto flex flex-wrap items-center gap-1.5">
          {index.state === "building" || index.state === "ready" ? (
            <Button
              size="sm"
              variant="outline"
              className="h-6 px-2 text-[10.5px]"
              disabled={busy}
              onClick={() => onAction(index.id, "build")}
            >
              {busy ? (
                <Loader2 className="size-3 animate-spin" />
              ) : (
                <RefreshCw className="size-3" />
              )}
              Build
            </Button>
          ) : null}
          {!index.validated ? (
            <Button
              size="sm"
              variant="outline"
              className="h-6 px-2 text-[10.5px]"
              disabled={busy || isBuilding}
              onClick={() => onAction(index.id, "validate")}
            >
              Validate
            </Button>
          ) : null}
          {index.validated && !index.evaluated ? (
            <Button
              size="sm"
              variant="outline"
              className="h-6 px-2 text-[10.5px]"
              disabled={busy}
              onClick={() => onAction(index.id, "evaluate")}
            >
              Evaluate
            </Button>
          ) : null}
          {!isActive && !isBuilding ? (
            <Button
              size="sm"
              className="h-6 px-2 text-[10.5px]"
              disabled={busy}
              onClick={() => onAction(index.id, "activate")}
            >
              Activate
            </Button>
          ) : null}
          {isActive ? (
            <Button
              size="sm"
              variant="outline"
              className="h-6 px-2 text-[10.5px]"
              disabled={busy}
              onClick={() => onAction(index.id, "rollback")}
            >
              <Undo2 className="size-3" />
              Rollback
            </Button>
          ) : null}

          <CollapsibleTrigger asChild>
            <Button
              size="sm"
              variant="ghost"
              className="h-6 px-2 text-[10.5px]"
            >
              <ChevronRight className="size-3.5 transition-transform group-data-[state=open]:rotate-90" />
              Details
            </Button>
          </CollapsibleTrigger>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-2 border-t border-border px-3 py-2.5 sm:grid-cols-4">
        {[
          { label: "Embedding", value: index.embedding ?? "—" },
          {
            label: "Dimensions",
            value: index.dimensions ? String(index.dimensions) : "—",
          },
          { label: "Revision", value: index.revision ? String(index.revision) : "—" },
          { label: "Documents", value: formatCount(index.documents) },
        ].map((cell) => (
          <div key={cell.label}>
            <p className="term-dim text-[10px] tracking-[0.1em] uppercase">
              {cell.label}
            </p>
            <p className="mt-0.5 truncate font-mono text-[11.5px]">{cell.value}</p>
          </div>
        ))}
      </div>

      <CollapsibleContent>
        <div className="border-t border-border px-3 py-2.5">
          <KeyValue label="Chunks" value={formatCount(index.chunks)} />
          <KeyValue
            label="Created"
            value={index.createdAt ? formatDateTime(index.createdAt) : undefined}
          />
          <KeyValue
            label="Built"
            value={index.builtAt ? formatDateTime(index.builtAt) : "not built"}
          />
          <KeyValue
            label="Validated"
            value={index.validated ? "yes" : "no"}
            tone={index.validated ? "ok" : "warn"}
          />
          <KeyValue
            label="Evaluated"
            value={
              index.evaluated
                ? `yes · evidence score ${formatPercent(index.evaluationScore)}`
                : "no"
            }
          />
          <p className="term-dim mt-2 text-[10px] leading-4">
            Index builds are versioned separately from document versions. The
            active build is what dense retrieval reads from.
          </p>
        </div>
      </CollapsibleContent>
    </Collapsible>
  );
}

function IndexesWorkspace() {
  const { indexes, loading, error, refresh, busy, runIndexAction } = useTelemetry();

  return (
    <Workspace>
      <PageHeader
        title="Indexes"
        description="Build, validate, activate and roll back RAG index builds."
      >
        <Button
          size="sm"
          variant="outline"
          className="h-7 text-[11px]"
          onClick={refresh}
        >
          <RefreshCw className="size-3.5" />
          Refresh
        </Button>
        <Button
          size="sm"
          className="h-7 text-[11px]"
          disabled={busy !== null}
          onClick={() => runIndexAction(indexes[0]?.id ?? "", "create")}
        >
          <Plus className="size-3.5" />
          Create index
        </Button>
      </PageHeader>

      <PageBody>
        <Panel
          title="Lifecycle"
          description="Index lifecycle status and actions"
        >
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[10.5px]">
            {LIFECYCLE.map((step, stepIndex) => (
              <span key={step} className="flex items-center gap-2">
                {stepIndex > 0 ? <span className="term-dim">→</span> : null}
                <span
                  className={cn(
                    "rounded-md border px-2 py-0.5",
                    step === "evaluate"
                      ? "border-border text-muted-foreground"
                      : "border-border text-foreground/80",
                  )}
                >
                  {step}
                </span>
              </span>
            ))}
          </div>
          <p className="term-dim mt-2 text-[10px] leading-4">
            Build and validate a candidate before activation. The active revision
            remains isolated so rollback does not interrupt queries.
          </p>
        </Panel>

        {loading && indexes.length === 0 ? (
          <div className="flex items-center gap-2 py-6 text-[12px] text-muted-foreground">
            <Loader2 className="size-3.5 animate-spin" />
            Loading indexes…
          </div>
        ) : error && indexes.length === 0 ? (
          <Callout tone="bad" title="Could not load indexes">
            {error}
          </Callout>
        ) : indexes.length === 0 ? (
          <EmptyNote>
            No index builds are available.
          </EmptyNote>
        ) : (
          <div className="space-y-2.5">
            {indexes.map((index) => (
              <IndexCard
                key={index.id}
                index={index}
                busy={busy === index.id}
                onAction={runIndexAction}
              />
            ))}
          </div>
        )}

        <Panel title="What an index holds">
          <ul className="space-y-1.5 text-[11.5px] text-foreground/90">
            <li className="flex gap-2">
              <Blocks className="mt-0.5 size-3.5 shrink-0 text-muted-foreground" />
              Embedding identity (model and dimensions), so a build is never read
              with the wrong vectors.
            </li>
            <li className="flex gap-2">
              <Blocks className="mt-0.5 size-3.5 shrink-0 text-muted-foreground" />
              A revision counter and the document/chunk counts it covers.
            </li>
            <li className="flex gap-2">
              <Blocks className="mt-0.5 size-3.5 shrink-0 text-muted-foreground" />
              Validation and evaluation results used before activation.
            </li>
          </ul>
        </Panel>
      </PageBody>
    </Workspace>
  );
}

export default function Indexes() {
  return (
    <AppShell>
      {() => <IndexesWorkspace />}
    </AppShell>
  );
}
