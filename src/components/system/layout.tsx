import { cn } from "@/lib/utils";
import type { ReactNode } from "react";

/** Standard page header: title, one-line description and right-aligned actions. */
export function PageHeader({
  title,
  description,
  children,
}: {
  title: string;
  description?: string;
  children?: ReactNode;
}) {
  return (
    <header className="shrink-0 border-b border-border px-4 py-3">
      <div className="mx-auto flex w-full max-w-5xl flex-wrap items-start gap-x-3 gap-y-2">
        <div className="min-w-0">
          <h1 className="text-[15px] font-bold tracking-tight">{title}</h1>
          {description ? (
            <p className="term-dim mt-0.5 text-[11px]">{description}</p>
          ) : null}
        </div>
        {children ? (
          <div className="ml-auto flex flex-wrap items-center gap-1.5">
            {children}
          </div>
        ) : null}
      </div>
    </header>
  );
}

/** Main column of a page, sized to sit beside the navigation rail. */
export function Workspace({ children }: { children: ReactNode }) {
  return <main className="flex min-w-0 flex-1 flex-col">{children}</main>;
}

/** Scrollable page body with the faint blueprint grid used across the app. */
export function PageBody({
  children,
  maxWidth = "max-w-5xl",
}: {
  children: ReactNode;
  maxWidth?: string;
}) {
  return (
    <div className="term-grid min-h-0 flex-1 overflow-y-auto px-4 py-4">
      <div className={cn("mx-auto w-full space-y-3", maxWidth)}>{children}</div>
    </div>
  );
}
