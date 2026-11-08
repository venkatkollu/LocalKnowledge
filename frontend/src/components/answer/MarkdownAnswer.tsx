import type { Citation } from "@/api/types";
import { citationLocation } from "./source-utils";
import { remarkCitations } from "./citations";
import { CodeBlock } from "./CodeBlock";
import { normalizeMathDelimiters } from "./math";
import { cn } from "@/lib/utils";
import { Children, isValidElement, useMemo } from "react";
import type { ReactNode } from "react";
import ReactMarkdown, { type Components } from "react-markdown";
import rehypeKatex from "rehype-katex";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import type { PluggableList } from "unified";

const REHYPE_PLUGINS: PluggableList = [
  [rehypeKatex, { throwOnError: false, strict: false }],
];

function safeUrl(url: string): string {
  if (url.startsWith("#") || url.startsWith("/")) return url;
  if (/^(https?:|mailto:)/i.test(url)) return url;
  return "";
}

function textContent(value: ReactNode): string {
  if (typeof value === "string" || typeof value === "number") {
    return String(value);
  }
  if (Array.isArray(value)) return value.map(textContent).join("");
  if (isValidElement(value)) {
    return textContent((value.props as { children?: ReactNode }).children);
  }
  return "";
}

function extractCode(children: ReactNode): {
  code: string;
  language: string;
} | null {
  const child = Children.toArray(children)[0];
  if (!isValidElement(child)) {
    const code = textContent(children);
    return code ? { code, language: "text" } : null;
  }

  const props = child.props as {
    className?: string;
    children?: ReactNode;
  };
  const language = /language-([^\s]+)/.exec(props.className ?? "")?.[1];
  const code = textContent(props.children).replace(/\n$/, "");
  return { code, language: language ?? "text" };
}

export function MarkdownAnswer({
  content,
  citations = [],
  streaming = false,
  onCitationClick,
  className,
}: {
  content: string;
  citations?: Citation[];
  streaming?: boolean;
  onCitationClick?: (index: number) => void;
  className?: string;
}) {
  const normalized = useMemo(() => normalizeMathDelimiters(content), [content]);
  const remarkPlugins = useMemo<PluggableList>(
    () => [remarkGfm, remarkMath, [remarkCitations, citations]],
    [citations],
  );

  const components = useMemo<Components>(
    () => ({
      h1: ({ children }) => <h1>{children}</h1>,
      h2: ({ children }) => <h2>{children}</h2>,
      h3: ({ children }) => <h3>{children}</h3>,
      h4: ({ children }) => <h4>{children}</h4>,
      h5: ({ children }) => <h5>{children}</h5>,
      h6: ({ children }) => <h6>{children}</h6>,
      p: ({ children }) => <p>{children}</p>,
      strong: ({ children }) => <strong>{children}</strong>,
      em: ({ children }) => <em>{children}</em>,
      del: ({ children }) => <del>{children}</del>,
      blockquote: ({ children }) => <blockquote>{children}</blockquote>,
      hr: () => <hr />,
      ul: ({ children }) => <ul>{children}</ul>,
      ol: ({ children }) => <ol>{children}</ol>,
      li: ({ children }) => <li>{children}</li>,
      table: ({ children }) => (
        <div className="answer-table-wrap">
          <table>{children}</table>
        </div>
      ),
      thead: ({ children }) => <thead>{children}</thead>,
      tbody: ({ children }) => <tbody>{children}</tbody>,
      tr: ({ children }) => <tr>{children}</tr>,
      th: ({ children }) => <th>{children}</th>,
      td: ({ children }) => <td>{children}</td>,
      a: ({ href, children, title }) => {
        const citation = href ? /^#cite-(\d+)$/.exec(href) : null;
        if (citation && href) {
          const index = Number(citation[1]);
          const source = citations[index - 1];
          const label = source
            ? `${source.filename} · ${citationLocation(source)}`
            : `Source ${index}`;
          if (!onCitationClick || !source) {
            return (
              <span className="answer-citation" title={label}>
                [{index}]
              </span>
            );
          }
          return (
            <button
              type="button"
              className="answer-citation"
              title={label}
              aria-label={`Open source ${index}: ${label}`}
              onClick={() => onCitationClick(index)}
            >
              [{index}]
            </button>
          );
        }

        if (!href) return <span>{children}</span>;
        return (
          <a
            href={href}
            title={title}
            target="_blank"
            rel="noreferrer noopener"
          >
            {children}
          </a>
        );
      },
      pre: ({ children }) => {
        const block = extractCode(children);
        if (!block) return <pre>{children}</pre>;
        return (
          <CodeBlock
            code={block.code}
            language={block.language}
            streaming={streaming}
          />
        );
      },
      img: ({ src, alt, title }) => (
        <img
          src={src}
          alt={alt ?? ""}
          title={title}
          loading="lazy"
          className="answer-image"
        />
      ),
      input: ({ type, checked, disabled }) =>
        type === "checkbox" ? (
          <input type="checkbox" checked={checked} disabled readOnly />
        ) : (
          <input type={type} disabled={disabled} readOnly />
        ),
    }),
    [citations, onCitationClick, streaming],
  );

  return (
    <div
      className={cn("answer-prose", className)}
      data-streaming={streaming ? "true" : undefined}
    >
      <ReactMarkdown
        remarkPlugins={remarkPlugins}
        rehypePlugins={REHYPE_PLUGINS}
        components={components}
        skipHtml
        urlTransform={safeUrl}
      >
        {normalized}
      </ReactMarkdown>
    </div>
  );
}
