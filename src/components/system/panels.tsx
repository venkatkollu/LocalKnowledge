import { StatusDot, TONE_TEXT, type Tone } from "@/components/StatusDot";
import { cn } from "@/lib/utils";
import type { ReactNode } from "react";

/** Bordered section with an optional header and actions. */
export function Panel({
  title,
  description,
  actions,
  children,
  className,
}: {
  title?: string;
  description?: string;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={cn("rounded-lg border border-border bg-card", className)}>
      {title || actions ? (
        <header className="flex flex-wrap items-center gap-x-3 gap-y-1 border-b border-border px-3 py-2">
          <div className="min-w-0">
            {title ? (
              <h2 className="text-[12px] font-semibold tracking-tight">{title}</h2>
            ) : null}
            {description ? (
              <p className="term-dim text-[10.5px]">{description}</p>
            ) : null}
          </div>
          {actions ? (
            <div className="ml-auto flex flex-wrap items-center gap-1.5">
              {actions}
            </div>
          ) : null}
        </header>
      ) : null}
      <div className="px-3 py-3">{children}</div>
    </section>
  );
}

/** Compact metric tile: label, big value, optional hint. */
export function Stat({
  label,
  value,
  hint,
  tone = "idle",
}: {
  label: string;
  value: string;
  hint?: string;
  tone?: Tone;
}) {
  return (
    <div className="rounded-md border border-border bg-background px-3 py-2.5">
      <p className="term-dim text-[10px] tracking-[0.1em] uppercase">{label}</p>
      <p
        className={cn(
          "mt-1 text-[18px] font-semibold tracking-tight tabular-nums",
          tone === "idle" ? "text-foreground" : TONE_TEXT[tone],
        )}
      >
        {value}
      </p>
      {hint ? <p className="term-dim mt-0.5 text-[10px]">{hint}</p> : null}
    </div>
  );
}

/** Label/value row used across the metadata and configuration panels. */
export function KeyValue({
  label,
  value,
  mono = true,
  tone,
}: {
  label: string;
  value: ReactNode;
  mono?: boolean;
  tone?: Tone;
}) {
  return (
    <div className="flex items-start gap-3 border-b border-border/60 py-1.5 last:border-0">
      <span className="term-dim w-40 shrink-0 text-[10.5px] tracking-wide uppercase">
        {label}
      </span>
      <span
        className={cn(
          "min-w-0 flex-1 break-words text-[11.5px]",
          mono && "font-mono",
          tone && tone !== "idle" ? TONE_TEXT[tone] : "text-foreground/90",
        )}
      >
        {value}
      </span>
    </div>
  );
}

/** Horizontal proportion bar used for stage and outcome breakdowns. */
export function Bar({
  fraction,
  tone = "ok",
  className,
}: {
  fraction: number;
  tone?: Tone;
  className?: string;
}) {
  const clamped = Math.max(0, Math.min(1, fraction));
  return (
    <div className={cn("h-1 overflow-hidden rounded-full bg-muted", className)}>
      <div
        className={cn(
          "h-full rounded-full transition-[width] duration-300",
          tone === "ok" && "bg-[var(--term-ok)]",
          tone === "warn" && "bg-[var(--term-warn)]",
          tone === "info" && "bg-[var(--term-info)]",
          tone === "bad" && "bg-[var(--term-bad)]",
          tone === "idle" && "bg-[var(--term-dim)]",
        )}
        style={{ width: `${Math.round(clamped * 100)}%` }}
      />
    </div>
  );
}

export function EmptyNote({ children }: { children: ReactNode }) {
  return (
    <p className="term-dim text-[11.5px] leading-5">{children}</p>
  );
}

/** Neutral notice used to state a limitation or unavailable state. */
export function Callout({
  tone = "idle",
  title,
  children,
}: {
  tone?: Tone;
  title: string;
  children: ReactNode;
}) {
  const border =
    tone === "warn"
      ? "border-[var(--term-warn)]/35 bg-[var(--term-warn)]/10"
      : tone === "info"
        ? "border-[var(--term-info)]/35 bg-[var(--term-info)]/5"
        : "border-border bg-background";

  return (
    <div className={cn("rounded-md border px-3 py-2.5", border)}>
      <p className="flex items-center gap-1.5 text-[11.5px] font-semibold tracking-tight">
        <StatusDot tone={tone} />
        {title}
      </p>
      <div className="term-dim mt-1 text-[11px] leading-5">{children}</div>
    </div>
  );
}

/** Rows of a definition list rendered from a record. */
export function KeyValueList({ entries }: { entries: Record<string, string> }) {
  return (
    <div className="rounded-md border border-border bg-background px-3 py-2">
      {Object.entries(entries).map(([label, value]) => (
        <KeyValue key={label} label={label} value={value} />
      ))}
    </div>
  );
}
