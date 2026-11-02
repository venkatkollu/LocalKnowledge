import type { JobStage } from "@/api/types";

/**
 * Document processing stages in order. `completed` and `failed` are terminal.
 */
export const JOB_STAGES: { key: JobStage; label: string }[] = [
  { key: "parsing", label: "Parsing" },
  { key: "structure", label: "Structure extraction" },
  { key: "chunking", label: "Chunking" },
  { key: "contextualizing", label: "Contextualizing" },
  { key: "embedding", label: "Embedding" },
  { key: "indexing", label: "Indexing" },
  { key: "validating", label: "Validating" },
];

export function stageIndex(stage: JobStage): number {
  const index = JOB_STAGES.findIndex((entry) => entry.key === stage);
  return index === -1 ? JOB_STAGES.length : index;
}

export function stageLabel(stage: JobStage): string {
  if (stage === "completed") return "Completed";
  if (stage === "failed") return "Failed";
  return JOB_STAGES.find((entry) => entry.key === stage)?.label ?? stage;
}

export type StageState = "done" | "active" | "pending" | "failed" | "cancelled";

export function stageStateFor(
  stage: JobStage,
  jobStage: JobStage,
  jobStatus: "queued" | "running" | "completed" | "failed" | "cancelled",
): StageState {
  const target = stageIndex(stage);
  if (jobStatus === "completed") return "done";

  // `completed` / `failed` carry no stage information of their own.
  const current =
    jobStage === "completed" || jobStage === "failed" ? -1 : stageIndex(jobStage);
  if (current === -1) return "pending";

  if (target < current) return "done";
  if (target === current) return jobStatus === "failed" ? "failed" : "active";
  return "pending";
}
