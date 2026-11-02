import { Button } from "@/components/ui/button";
import { StatusDot } from "@/components/StatusDot";
import type { DocumentVersion } from "@/api/types";
import { formatCount, formatDateTime, formatRelative } from "@/lib/format";
import { cn } from "@/lib/utils";
import { useState } from "react";

export function VersionTimeline({ versions }: { versions: DocumentVersion[] }) {
  const [selected, setSelected] = useState<number | null>(null);
  const [comparing, setComparing] = useState(false);

  if (versions.length === 0) {
    return (
      <p className="term-dim text-[11.5px]">
        No versions recorded — this document has not been indexed yet.
      </p>
    );
  }

  const current = versions.find((version) => version.current) ?? versions[0];
  const selectedVersion = versions.find((version) => version.version === selected);

  return (
    <div className="space-y-3">
      <ol className="relative space-y-2 pl-4">
        <span
          aria-hidden
          className="absolute top-1 bottom-1 left-[5px] w-px bg-border"
        />
        {versions.map((version) => {
          const isSelected = version.version === selected;
          return (
            <li key={version.version} className="relative">
              <span
                aria-hidden
                className={cn(
                  "absolute top-[7px] -left-4 size-2 rounded-full border",
                  version.current
                    ? "border-[var(--term-ok)] bg-[var(--term-ok)]"
                    : "border-border bg-background",
                )}
              />
              <div
                className={cn(
                  "rounded-md border px-3 py-2",
                  isSelected
                    ? "border-[var(--term-ok)]/50 bg-accent/30"
                    : "border-border bg-card",
                )}
              >
                <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                  <span className="text-[12px] font-semibold tabular-nums">
                    v{version.version}
                  </span>
                  {version.current ? (
                    <span className="rounded-full border border-[var(--term-ok)]/35 px-2 py-0.5 text-[9.5px] tracking-wide text-[var(--term-ok)] uppercase">
                      Current
                    </span>
                  ) : null}
                  <span className="term-dim ml-auto text-[10.5px]">
                    {formatDateTime(version.createdAt)}
                  </span>
                </div>

                <p className="term-dim mt-1 text-[10.5px]">
                  {formatCount(version.chunks)} chunks ·{" "}
                  {formatRelative(version.createdAt)}
                </p>

                <div className="mt-1.5 flex items-center gap-1.5">
                  <Button
                    size="sm"
                    variant="outline"
                    className="h-6 px-2 text-[10.5px]"
                    onClick={() =>
                      setSelected(isSelected ? null : version.version)
                    }
                  >
                    View
                  </Button>
                  <Button
                    size="sm"
                    variant="outline"
                    className="h-6 px-2 text-[10.5px]"
                    disabled={version.current}
                    onClick={() => setComparing((value) => !value)}
                  >
                    Compare
                  </Button>
                  <Button
                    size="sm"
                    variant="ghost"
                    className="h-6 px-2 text-[10.5px]"
                    disabled
                    title="Historical restore is not available; re-upload the desired file version."
                  >
                    Restore
                  </Button>
                </div>

                {isSelected ? (
                  <dl className="mt-2 space-y-1 border-t border-dashed border-border pt-2 text-[10.5px]">
                    <div className="flex gap-2">
                      <dt className="term-dim w-24 shrink-0">Content hash</dt>
                      <dd className="truncate font-mono">
                        {version.contentHash
                          ? `SHA-256: ${version.contentHash.slice(0, 12)}…${version.contentHash.slice(-4)}`
                          : "not reported"}
                      </dd>
                    </div>
                    <div className="flex gap-2">
                      <dt className="term-dim w-24 shrink-0">Embeddings</dt>
                      <dd>
                        {version.reused !== undefined
                          ? `${formatCount(version.reused)} reused · ${formatCount(version.newlyEmbedded ?? 0)} newly embedded`
                          : "not reported"}
                      </dd>
                    </div>
                  </dl>
                ) : null}

                {comparing && !version.current ? (
                  <div className="mt-2 space-y-1 border-t border-dashed border-border pt-2 text-[10.5px]">
                    <p className="term-dim pb-0.5 tracking-[0.1em] uppercase">
                      v{version.version} → v{current.version}
                    </p>
                    <p className="flex justify-between gap-2">
                      <span className="term-dim">Chunks</span>
                      <span className="tabular-nums">
                        {formatCount(version.chunks)} →{" "}
                        {formatCount(current.chunks)}
                        <span
                          className={
                            current.chunks >= version.chunks
                              ? "term-ok ml-1"
                              : "term-warn ml-1"
                          }
                        >
                          ({current.chunks - version.chunks >= 0 ? "+" : ""}
                          {current.chunks - version.chunks})
                        </span>
                      </span>
                    </p>
                    <p className="flex justify-between gap-2">
                      <span className="term-dim">Indexed</span>
                      <span>{formatRelative(version.createdAt)}</span>
                    </p>
                    <p className="term-dim pt-0.5 leading-4">
                      Comparison is computed from version metadata. Historical
                      chunk text is not stored by the index.
                    </p>
                  </div>
                ) : null}
              </div>
            </li>
          );
        })}
      </ol>

      {selectedVersion ? (
        <p className="term-dim flex items-start gap-1.5 text-[10px] leading-4">
          <StatusDot tone="idle" className="mt-1" />
          Preview always shows the current content on disk. These are document
          versions — RAG index versions (e.g. index-v7) are managed separately.
        </p>
      ) : null}
    </div>
  );
}
