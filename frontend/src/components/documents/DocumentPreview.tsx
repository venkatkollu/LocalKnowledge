import { codeLanguageFor, extensionOf } from "@/lib/file-kind";
import { cn } from "@/lib/utils";
import type { ReactNode } from "react";

/* ------------------------------------------------------------------ *
 * Light syntax highlighting
 * ------------------------------------------------------------------ */

const BASE_KEYWORDS = [
  "true",
  "false",
  "null",
  "none",
  "and",
  "or",
  "not",
  "if",
  "else",
  "elif",
  "for",
  "while",
  "return",
  "class",
  "def",
  "import",
  "from",
  "as",
  "in",
  "is",
  "try",
  "except",
  "finally",
  "raise",
  "with",
  "yield",
  "lambda",
  "pass",
  "self",
  "await",
  "async",
  "break",
  "continue",
  "new",
  "const",
  "let",
  "var",
  "function",
  "export",
  "default",
  "extends",
  "interface",
  "type",
  "typeof",
  "public",
  "private",
  "static",
  "package",
  "void",
  "struct",
  "enum",
  "impl",
  "fn",
  "func",
  "match",
  "use",
  "mod",
  "mut",
  "pub",
  "select",
  "create",
  "table",
  "index",
  "primary",
  "key",
  "references",
  "not",
  "virtual",
  "using",
];

const KEYWORDS = new Set(BASE_KEYWORDS);

const TOKEN_PATTERN =
  /(#[^\n]*|\/\/[^\n]*|--[^\n]*)|("(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*')|\b(\d+(?:\.\d+)?)\b|\b([A-Za-z_][A-Za-z0-9_]*)\b/g;

function tokenize(line: string): ReactNode[] {
  const nodes: ReactNode[] = [];
  let last = 0;
  let key = 0;
  let match: RegExpExecArray | null;
  TOKEN_PATTERN.lastIndex = 0;

  while ((match = TOKEN_PATTERN.exec(line)) !== null) {
    if (match.index > last) nodes.push(line.slice(last, match.index));
    const [full, comment, str, num, word] = match;

    if (comment) {
      nodes.push(
        <span key={key++} className="italic text-[var(--term-dim)]">
          {full}
        </span>,
      );
    } else if (str) {
      nodes.push(
        <span key={key++} className="text-[var(--term-ok)]">
          {full}
        </span>,
      );
    } else if (num) {
      nodes.push(
        <span key={key++} className="text-[var(--term-warn)]">
          {full}
        </span>,
      );
    } else if (word && KEYWORDS.has(word.toLowerCase())) {
      nodes.push(
        <span key={key++} className="font-medium text-[var(--term-info)]">
          {full}
        </span>,
      );
    } else {
      nodes.push(full);
    }
    last = match.index + full.length;
  }
  if (last < line.length) nodes.push(line.slice(last));
  return nodes;
}

/* ------------------------------------------------------------------ *
 * Renderers
 * ------------------------------------------------------------------ */

function CodeLines({
  text,
  startLine = 1,
  showNumbers = true,
}: {
  text: string;
  startLine?: number;
  showNumbers?: boolean;
}) {
  const lines = text.replace(/\s+$/, "").split("\n");
  const width = String(startLine + lines.length - 1).length;

  return (
    <div className="overflow-x-auto">
      <table className="w-full border-collapse">
        <tbody>
          {lines.map((line, index) => (
            <tr key={index} className="align-top">
              {showNumbers ? (
                <td className="w-px border-r border-border bg-muted/40 px-2 py-0.5 text-right text-[10.5px] leading-5 text-[var(--term-dim)] tabular-nums select-none">
                  {String(startLine + index).padStart(width, " ")}
                </td>
              ) : null}
              <td className="px-3 py-0.5 text-[11.5px] leading-5 whitespace-pre">
                {line ? tokenize(line) : " "}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Markdown({ content }: { content: string }) {
  const lines = content.split("\n");
  const blocks: ReactNode[] = [];
  let index = 0;
  let key = 0;

  while (index < lines.length) {
    const line = lines[index];

    if (line.trim() === "") {
      index += 1;
      continue;
    }

    // Fenced code block
    if (line.startsWith("```")) {
      const language = line.slice(3).trim();
      const body: string[] = [];
      index += 1;
      while (index < lines.length && !lines[index].startsWith("```")) {
        body.push(lines[index]);
        index += 1;
      }
      index += 1;
      blocks.push(
        <div key={key++} className="overflow-hidden rounded-md border border-border">
          <div className="flex items-center gap-2 border-b border-border bg-muted/40 px-3 py-1">
            <span className="term-dim text-[10px] tracking-[0.1em] uppercase">
              {language || "code"}
            </span>
          </div>
          <CodeLines text={body.join("\n")} showNumbers={false} />
        </div>,
      );
      continue;
    }

    // Headings
    const heading = line.match(/^(#{1,4})\s+(.*)$/);
    if (heading) {
      const level = heading[1].length;
      const text = heading[2];
      blocks.push(
        <p
          key={key++}
          className={cn(
            "font-semibold tracking-tight",
            level === 1 && "mt-1 text-[16px]",
            level === 2 && "mt-1 text-[14px]",
            level === 3 && "text-[12.5px]",
            level >= 4 && "text-[12px]",
          )}
        >
          {text}
        </p>,
      );
      index += 1;
      continue;
    }

    // Lists
    if (/^\s*([-*•]|\d+\.)\s+/.test(line)) {
      const items: string[] = [];
      while (index < lines.length && /^\s*([-*•]|\d+\.)\s+/.test(lines[index])) {
        items.push(lines[index].replace(/^\s*([-*•]|\d+\.)\s+/, ""));
        index += 1;
      }
      blocks.push(
        <ul key={key++} className="space-y-1">
          {items.map((item, itemIndex) => (
            <li key={itemIndex} className="flex gap-2 text-[12px] leading-6">
              <span className="term-ok shrink-0">•</span>
              <span className="text-foreground/90">{item}</span>
            </li>
          ))}
        </ul>,
      );
      continue;
    }

    // Paragraph
    const paragraph: string[] = [];
    while (
      index < lines.length &&
      lines[index].trim() !== "" &&
      !lines[index].startsWith("```") &&
      !/^#{1,4}\s/.test(lines[index]) &&
      !/^\s*([-*•]|\d+\.)\s+/.test(lines[index])
    ) {
      paragraph.push(lines[index]);
      index += 1;
    }
    blocks.push(
      <p key={key++} className="text-[12px] leading-6 text-foreground/90">
        {paragraph.join(" ")}
      </p>,
    );
  }

  return <div className="space-y-3">{blocks}</div>;
}

function PdfText({ content }: { content: string }) {
  const pages: { page: string; body: string[] }[] = [];
  const lines = content.split("\n");

  for (const line of lines) {
    const match = line.match(/^Page\s+(\d+)\s*$/);
    if (match) {
      pages.push({ page: match[1], body: [] });
      continue;
    }
    if (pages.length === 0) pages.push({ page: "1", body: [] });
    pages[pages.length - 1].body.push(line);
  }

  return (
    <div className="space-y-3">
      {pages.map((page, pageIndex) => (
        <div key={pageIndex} className="rounded-md border border-border">
          <div className="flex items-center gap-2 border-b border-border bg-muted/40 px-3 py-1">
            <span className="term-dim text-[10px] tracking-[0.1em] uppercase">
              Page {page.page}
            </span>
            <span className="term-dim ml-auto text-[10px]">extracted text</span>
          </div>
          <p className="px-3 py-2.5 text-[12px] leading-6 whitespace-pre-wrap text-foreground/90">
            {page.body.join("\n").trim()}
          </p>
        </div>
      ))}
    </div>
  );
}

export function DocumentPreview({
  filename,
  content,
}: {
  filename: string;
  content: string;
}) {
  const extension = extensionOf(filename);

  if (!content.trim()) {
    return (
      <p className="term-dim text-[11.5px]">
        No extracted text is available.
      </p>
    );
  }

  if (extension === "pdf") return <PdfText content={content} />;

  if (extension === "md" || extension === "markdown") {
    return <Markdown content={content} />;
  }

  return (
    <div className="overflow-hidden rounded-md border border-border">
      <div className="flex items-center gap-2 border-b border-border bg-muted/40 px-3 py-1">
        <span className="term-dim text-[10px] tracking-[0.1em] uppercase">
          {codeLanguageFor(filename)}
        </span>
        <span className="term-dim ml-auto text-[10px]">
          {content.split("\n").length} lines
        </span>
      </div>
      <CodeLines text={content} />
    </div>
  );
}
