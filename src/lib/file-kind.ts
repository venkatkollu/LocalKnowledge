/** Extension → language helpers. Kept free of React/icon imports so the API
 *  layer can use them when normalising document payloads. */

export function extensionOf(filename: string): string {
  const parts = filename.split(".");
  return parts.length > 1 ? parts.pop()!.toLowerCase() : "";
}

const LANGUAGE_BY_EXTENSION: Record<string, string> = {
  md: "Markdown",
  markdown: "Markdown",
  txt: "Plain text",
  pdf: "PDF",
  py: "Python",
  js: "JavaScript",
  jsx: "JavaScript",
  mjs: "JavaScript",
  ts: "TypeScript",
  tsx: "TypeScript",
  java: "Java",
  c: "C",
  h: "C header",
  cpp: "C++",
  hpp: "C++ header",
  go: "Go",
  rs: "Rust",
  json: "JSON",
  yaml: "YAML",
  yml: "YAML",
  toml: "TOML",
  csv: "CSV",
  html: "HTML",
  css: "CSS",
  scss: "CSS",
  sql: "SQL",
  sh: "Shell",
};

export function languageFor(filename: string): string {
  return LANGUAGE_BY_EXTENSION[extensionOf(filename)] ?? "Document";
}

/** Extensions the ingester currently supports, shown in the upload dialog. */
export const SUPPORTED_EXTENSIONS = [
  "md",
  "txt",
  "py",
  "js",
  "ts",
  "json",
  "yaml",
  "csv",
  "html",
  "css",
  "sql",
  "java",
  "c",
  "cpp",
  "go",
  "rs",
  "pdf",
] as const;

/** Best-effort programming language for the light syntax highlighter. */
export function codeLanguageFor(filename: string): string {
  const ext = extensionOf(filename);
  const map: Record<string, string> = {
    py: "python",
    js: "javascript",
    jsx: "javascript",
    mjs: "javascript",
    ts: "typescript",
    tsx: "typescript",
    java: "java",
    c: "c",
    h: "c",
    cpp: "cpp",
    hpp: "cpp",
    go: "go",
    rs: "rust",
    json: "json",
    yaml: "yaml",
    yml: "yaml",
    toml: "toml",
    sql: "sql",
    sh: "shell",
    css: "css",
    scss: "css",
    html: "html",
  };
  return map[ext] ?? "plain";
}
