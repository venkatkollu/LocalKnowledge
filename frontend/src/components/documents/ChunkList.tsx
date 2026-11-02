import type { DocumentChunk } from "@/api/types";
import { formatCount } from "@/lib/format";

export function ChunkList({
  chunks,
  total,
}: {
  chunks: DocumentChunk[];
  total: number;
}) {
  if (chunks.length === 0) {
    return (
      <p className="term-dim text-[11.5px]">
        No chunks stored — this document has not been indexed yet.
      </p>
    );
  }

  return (
    <div className="space-y-2">
      <p className="term-dim text-[10.5px]">
        Showing {chunks.length} of {formatCount(total)} chunks. Line ranges come
        from the chunker's structural boundaries.
      </p>

      <ul className="space-y-1.5">
        {chunks.map((chunk) => (
          <li
            key={chunk.id}
            className="rounded-md border border-border bg-card px-3 py-2"
          >
            <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[10.5px]">
              <span className="term-dim tabular-nums">
                #{String(chunk.index + 1).padStart(2, "0")}
              </span>
              <span className="font-medium tabular-nums">
                L{chunk.lineStart}–{chunk.lineEnd}
              </span>
              {chunk.section ? (
                <span className="term-dim truncate">{chunk.section}</span>
              ) : null}
              {chunk.tokens ? (
                <span className="term-dim ml-auto tabular-nums">
                  {formatCount(chunk.tokens)} tok
                </span>
              ) : null}
            </div>
            <p className="mt-1.5 line-clamp-3 text-[11px] leading-5 whitespace-pre-wrap text-muted-foreground">
              {chunk.excerpt}
            </p>
          </li>
        ))}
      </ul>
    </div>
  );
}
