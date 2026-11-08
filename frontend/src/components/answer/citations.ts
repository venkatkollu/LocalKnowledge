import type { Citation } from "@/api/types";
import type { PhrasingContent, Root, Text } from "mdast";
import { visit } from "unist-util-visit";

/**
 * Citation markers we accept from the model:
 *
 *   [1]                  numeric evidence id
 *   [1, 3]               several evidence ids
 *   [1-4]                an evidence id range
 *   [RLHF.pdf:12-14]     legacy filename/line reference
 *   [RLHF.pdf:2106]      legacy single-line reference
 *
 * Numeric ids are the contract with the answer prompt. The legacy forms keep
 * older cached answers and provider quirks rendering correctly.
 */
const BRACKET = /\[([^[\]\n]{1,240})\]/g;
const NUMERIC_LIST = /^\d{1,3}(?:\s*[,;]\s*\d{1,3}|\s*-\s*\d{1,3})*$/;
const LEGACY_LABEL =
  /([^\s,;[\]]+\.[a-z0-9]{1,12}):(\d+)(?:\s*[-–—]\s*(\d+))?/gi;

function normalise(value: string): string {
  return value
    .replace(/[–—]/g, "-")
    .replace(/\s+/g, " ")
    .trim()
    .toLowerCase();
}

function basename(value: string): string {
  const normalised = normalise(value);
  return normalised.split(/[\\/]/).pop() ?? normalised;
}

function matchesFilename(citation: Citation, name: string): boolean {
  const target = basename(name);
  if (!target) return false;
  if (basename(citation.filename) === target) return true;
  return citation.path ? basename(citation.path) === target : false;
}

function locationContains(citation: Citation, start: number, end: number): boolean {
  const lineStart = citation.lineStart;
  const lineEnd = citation.lineEnd;
  if (lineStart !== undefined && lineEnd !== undefined) {
    return start <= lineEnd && end >= lineStart;
  }
  if (citation.page !== undefined) {
    return citation.page >= start && citation.page <= end;
  }
  return true;
}

function findLegacyCitation(
  citations: Citation[],
  name: string,
  start: number,
  end: number,
): number {
  const exact = citations.findIndex(
    (citation) =>
      matchesFilename(citation, name) &&
      locationContains(citation, start, end),
  );
  if (exact >= 0) return exact;

  // A model may paraphrase the line range. If there is only one chunk from
  // that file, it is still the useful target.
  return citations.findIndex((citation) => matchesFilename(citation, name));
}

function parseNumericList(value: string): number[] | null {
  const cleaned = value.replace(/[–—]/g, "-").trim();
  if (!NUMERIC_LIST.test(cleaned)) return null;

  const ids: number[] = [];
  for (const part of cleaned.split(/\s*[,;]\s*/)) {
    const range = /^(\d{1,3})\s*-\s*(\d{1,3})$/.exec(part);
    if (range) {
      const start = Number(range[1]);
      const end = Number(range[2]);
      if (end < start || end - start > 25) return null;
      for (let id = start; id <= end; id += 1) ids.push(id);
      continue;
    }
    if (/^\d{1,3}$/.test(part)) {
      ids.push(Number(part));
      continue;
    }
    return null;
  }
  return ids;
}

/** Resolve one bracket label to 1-based citation ids, or null if it is prose. */
export function resolveCitationMarker(
  marker: string,
  citations: Citation[],
): number[] | null {
  if (!citations.length) return null;

  const numeric = parseNumericList(marker);
  if (numeric) {
    const valid = numeric.filter((id) => id >= 1 && id <= citations.length);
    return valid.length ? valid : null;
  }

  const legacy: number[] = [];
  for (const match of marker.matchAll(LEGACY_LABEL)) {
    const start = Number(match[2]);
    const end = Number(match[3] ?? match[2]);
    const index = findLegacyCitation(citations, match[1], start, end);
    if (index >= 0 && !legacy.includes(index + 1)) legacy.push(index + 1);
  }
  if (legacy.length) return legacy;

  const exact = citations.findIndex((citation) =>
    matchesFilename(citation, marker.trim()),
  );
  return exact >= 0 ? [exact + 1] : null;
}

function citationLink(id: number): PhrasingContent {
  return {
    type: "link",
    url: `#cite-${id}`,
    children: [{ type: "text", value: String(id) }],
    data: {
      hProperties: {
        "data-citation-index": String(id),
      },
    },
  };
}

function splitTextNode(
  value: string,
  citations: Citation[],
): PhrasingContent[] | null {
  const parts: PhrasingContent[] = [];
  let cursor = 0;

  for (const match of value.matchAll(BRACKET)) {
    const ids = resolveCitationMarker(match[1], citations);
    if (!ids?.length || match.index === undefined) continue;

    if (match.index > cursor) {
      parts.push({ type: "text", value: value.slice(cursor, match.index) });
    }
    for (const id of ids) parts.push(citationLink(id));
    cursor = match.index + match[0].length;
  }

  if (!parts.length) return null;
  if (cursor < value.length) {
    parts.push({ type: "text", value: value.slice(cursor) });
  }
  return parts;
}

/** Remark plugin that turns citation labels into clickable internal links. */
export function remarkCitations(citations: Citation[]) {
  return (tree: Root) => {
    visit(tree, "text", (node: Text, index, parent) => {
      if (!parent || index === undefined) return;
      // Never create a link inside an existing link.
      if (parent.type === "link" || parent.type === "linkReference") return;

      const parts = splitTextNode(node.value, citations);
      if (!parts) return;

      parent.children.splice(index, 1, ...parts);
      return index + parts.length;
    });
  };
}
