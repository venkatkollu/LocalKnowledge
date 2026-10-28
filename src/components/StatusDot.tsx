import { cn } from "@/lib/utils";

export type Tone = "ok" | "warn" | "info" | "bad" | "idle";

const DOT: Record<Tone, string> = {
  ok: "bg-[var(--term-ok)]",
  warn: "bg-[var(--term-warn)]",
  info: "bg-[var(--term-info)]",
  bad: "bg-[var(--term-bad)]",
  idle: "bg-[var(--term-dim)]",
};

export const TONE_TEXT: Record<Tone, string> = {
  ok: "text-[var(--term-ok)]",
  warn: "text-[var(--term-warn)]",
  info: "text-[var(--term-info)]",
  bad: "text-[var(--term-bad)]",
  idle: "text-[var(--term-dim)]",
};

export function StatusDot({
  tone = "idle",
  pulse = false,
  className,
}: {
  tone?: Tone;
  pulse?: boolean;
  className?: string;
}) {
  return (
    <span
      aria-hidden
      className={cn(
        "inline-block size-1.5 shrink-0 rounded-full",
        DOT[tone],
        pulse && "animate-pulse",
        className,
      )}
    />
  );
}

/** A labelled indicator: `● Synced`. */
export function StatusLabel({
  tone = "idle",
  label,
  pulse = false,
  className,
}: {
  tone?: Tone;
  label: string;
  pulse?: boolean;
  className?: string;
}) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 text-xs font-medium",
        TONE_TEXT[tone],
        className,
      )}
    >
      <StatusDot tone={tone} pulse={pulse} />
      {label}
    </span>
  );
}
