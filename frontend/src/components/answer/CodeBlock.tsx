import { cn } from "@/lib/utils";
import { Check, Copy } from "lucide-react";
import { useEffect, useState } from "react";

const ALIASES: Record<string, string> = {
  c: "c",
  "c++": "cpp",
  "c#": "csharp",
  cs: "csharp",
  objc: "objective-c",
  "objective-c": "objective-c",
  sh: "bash",
  shell: "bash",
  zsh: "bash",
  console: "bash",
  ps1: "powershell",
  py: "python",
  rb: "ruby",
  rs: "rust",
  yml: "yaml",
  md: "markdown",
  js: "javascript",
  ts: "typescript",
  jsonc: "json",
  plaintext: "text",
  plain: "text",
  txt: "text",
};

function resolveLanguage(language: string): string {
  const value = language.trim().toLowerCase();
  return ALIASES[value] ?? value ?? "text";
}

function displayLanguage(language: string): string {
  return resolveLanguage(language);
}

export function CodeBlock({
  code,
  language,
  streaming = false,
}: {
  code: string;
  language: string;
  streaming?: boolean;
}) {
  const [highlighted, setHighlighted] = useState<{
    code: string;
    html: string;
  } | null>(null);
  const [copied, setCopied] = useState(false);
  const resolved = resolveLanguage(language);
  const html =
    !streaming && highlighted?.code === code ? highlighted.html : null;

  useEffect(() => {
    let cancelled = false;
    if (streaming || !code.trim()) return;

    void (async () => {
      try {
        const { highlightCode } = await import("./highlight");
        const result = await highlightCode(code, resolved);
        if (!cancelled) setHighlighted({ code, html: result });
      } catch {
        // A missing grammar should never break the answer. Fall back to the
        // plain <pre> that is already on screen.
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [code, resolved, streaming]);

  const copy = () => {
    void navigator.clipboard
      ?.writeText(code)
      .then(() => {
        setCopied(true);
        window.setTimeout(() => setCopied(false), 1600);
      })
      .catch(() => undefined);
  };

  return (
    <div className="answer-code">
      <div className="answer-code-head">
        <span className="answer-code-lang">{displayLanguage(language)}</span>
        <button
          type="button"
          onClick={copy}
          className="answer-code-copy"
          aria-label={`Copy ${displayLanguage(language)} code`}
        >
          {copied ? <Check className="size-3" /> : <Copy className="size-3" />}
          <span>{copied ? "Copied" : "Copy"}</span>
        </button>
      </div>
      {html ? (
        <div
          className="answer-code-body"
          dangerouslySetInnerHTML={{ __html: html }}
        />
      ) : (
        <pre className={cn("answer-code-body", "answer-code-plain")}>
          <code>{code}</code>
        </pre>
      )}
    </div>
  );
}
