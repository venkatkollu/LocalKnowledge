import { cn } from "@/lib/utils";
import { Moon, Sun } from "lucide-react";
import { useTheme } from "next-themes";

export function ThemeToggle({ className }: { className?: string }) {
  const { resolvedTheme, setTheme } = useTheme();

  const isDark = resolvedTheme !== "light";
  const label = isDark ? "Switch to light mode" : "Switch to dark mode";

  return (
    <button
      type="button"
      className={cn("kos-icon-btn", className)}
      onClick={() => setTheme(isDark ? "light" : "dark")}
      aria-label={label}
      title={label}
    >
      {isDark ? <Sun /> : <Moon />}
    </button>
  );
}
