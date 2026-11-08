/**
 * Many models emit LaTeX with `\(...\)` and `\[...\]` delimiters. Markdown
 * treats the backslash as an escape, so those delimiters disappear before
 * remark-math can see them. Normalise them to dollar math while leaving fenced
 * code blocks and inline code untouched.
 */
export function normalizeMathDelimiters(markdown: string): string {
  let output = "";
  let index = 0;
  let lineStart = true;
  let fence: { char: string; length: number } | null = null;

  while (index < markdown.length) {
    if (lineStart) {
      const line = markdown.slice(index);
      const fenceMatch = /^( {0,3})(`{3,}|~{3,})/.exec(line);
      if (fenceMatch) {
        const marker = fenceMatch[2];
        if (
          !fence ||
          (marker[0] === fence.char && marker.length >= fence.length)
        ) {
          fence = fence
            ? null
            : { char: marker[0], length: marker.length };
        }
        const end = nextLineEnd(markdown, index);
        output += markdown.slice(index, end);
        index = end;
        lineStart = true;
        continue;
      }
    }

    if (fence) {
      const end = nextLineEnd(markdown, index);
      output += markdown.slice(index, end);
      index = end;
      lineStart = true;
      continue;
    }

    const character = markdown[index];

    // Copy inline code spans verbatim.
    if (character === "`") {
      let run = 1;
      while (markdown[index + run] === "`") run += 1;
      const start = index;
      index += run;
      while (index < markdown.length) {
        if (markdown[index] === "`") {
          let closeRun = 1;
          while (markdown[index + closeRun] === "`") closeRun += 1;
          if (closeRun === run) {
            index += closeRun;
            break;
          }
          index += closeRun;
        } else {
          index += 1;
        }
      }
      output += markdown.slice(start, index);
      lineStart = false;
      continue;
    }

    if (character === "\\" && (markdown[index + 1] === "(" || markdown[index + 1] === "[")) {
      const block = markdown[index + 1] === "[";
      const closing = block ? "\\]" : "\\)";
      const end = markdown.indexOf(closing, index + 2);
      if (end !== -1) {
        const body = markdown.slice(index + 2, end);
        output += block ? `\n$$\n${body}\n$$\n` : `$${body}$`;
        index = end + 2;
        lineStart = false;
        continue;
      }
    }

    output += character;
    index += 1;
    lineStart = character === "\n";
  }

  return output;
}

function nextLineEnd(markdown: string, index: number): number {
  const newline = markdown.indexOf("\n", index);
  return newline === -1 ? markdown.length : newline + 1;
}
