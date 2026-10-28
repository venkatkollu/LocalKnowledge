import { JOB_STAGES, stageLabel, stageStateFor } from "@/lib/job-stages";
import type { IngestionJob } from "@/api/types";
import { cn } from "@/lib/utils";
import { Check, Loader2, Square, X } from "lucide-react";
import { motion } from "framer-motion";

function StageChips({ job }: { job: IngestionJob }) {
  return (
    <div className="mt-2 flex flex-wrap items-center gap-x-2.5 gap-y-1 text-[10.5px]">
      {JOB_STAGES.map((stage) => {
        const state = stageStateFor(stage.key, job.stage, job.status);
        return (
          <span
            key={stage.key}
            className={cn(
              "flex items-center gap-1",
              state === "done" && "text-[var(--term-ok)]",
              state === "active" && "text-[var(--term-info)]",
              state === "failed" && "text-[var(--term-bad)]",
              state === "pending" && "term-dim",
            )}
          >
            {state === "done" ? (
              <Check className="size-3" />
            ) : state === "active" ? (
              <Loader2 className="size-3 animate-spin" />
            ) : state === "failed" ? (
              <X className="size-3" />
            ) : (
              <span className="inline-block size-2 rounded-full border border-current" />
            )}
            {stage.label}
          </span>
        );
      })}
    </div>
  );
}

export function SyncProgress({ jobs, onCancel }: { jobs: IngestionJob[]; onCancel?: (jobId: string) => void }) {
  if (jobs.length === 0) return null;

  const running = jobs.filter((job) => job.status === "queued" || job.status === "running");
  const failed = jobs.filter((job) => job.status === "failed");
  const overall = jobs.length
    ? jobs.reduce((total, job) => total + job.progress, 0) / jobs.length
    : 0;

  return (
    <motion.section
      initial={{ opacity: 0, y: -6 }}
      animate={{ opacity: 1, y: 0 }}
      className="rounded-lg border border-[var(--term-info)]/35 bg-[var(--term-info)]/5 p-3"
    >
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <span className="flex items-center gap-1.5 text-[12px] font-semibold tracking-tight">
          <Loader2 className="size-3.5 animate-spin text-[var(--term-info)]" />
          Synchronizing Knowledge Base
        </span>
        <span className="term-dim text-[10.5px]">
          {running.length} running
          {failed.length ? ` · ${failed.length} failed` : ""}
        </span>
        <span className="term-dim ml-auto text-[11px] tabular-nums">
          {Math.round(overall * 100)}%
        </span>
      </div>

      <div className="mt-2 h-1 overflow-hidden rounded-full bg-muted">
        <div
          className="h-full rounded-full bg-[var(--term-info)] transition-[width] duration-300"
          style={{ width: `${Math.round(overall * 100)}%` }}
        />
      </div>

      <ul className="mt-3 space-y-3">
        {jobs.map((job) => {
          const canCancel = job.status === "queued" || job.status === "running";
          return (
            <li key={job.id} className="rounded-md border border-border bg-card px-3 py-2">
              <div className="flex items-center gap-2 text-[11.5px]">
                <span className="truncate font-medium">
                  {job.documentName ?? "knowledge base"}
                </span>
                <span className="term-dim text-[10.5px]">
                  {job.status === "queued"
                    ? "Queued"
                    : job.status === "running"
                    ? stageLabel(job.stage)
                    : job.status === "completed"
                      ? "Completed"
                      : "Failed"}
                </span>
                <span className="term-dim ml-auto tabular-nums">
                  {Math.round(job.progress * 100)}%
                </span>
                {canCancel && onCancel ? (
                  <button
                    type="button"
                    title="Cancel job"
                    className="rounded p-0.5 text-muted-foreground hover:bg-destructive/10 hover:text-destructive"
                    onClick={() => onCancel(job.id)}
                  >
                    <Square className="size-3" />
                  </button>
                ) : null}
              </div>
              <StageChips job={job} />
              {job.error ? (
                <p className="mt-1.5 text-[10.5px] text-[var(--term-bad)]">
                  {job.error}
                </p>
              ) : null}
            </li>
          );
        })}
      </ul>

      {failed.length ? (
        <p className="term-dim mt-2 text-[10.5px]">
          Failed jobs keep their stage information so you can retry just the
          affected document.
        </p>
      ) : null}
    </motion.section>
  );
}
