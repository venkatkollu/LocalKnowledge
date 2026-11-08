import githubDark from "@shikijs/themes/github-dark";
import githubLight from "@shikijs/themes/github-light";
import { createHighlighterCore, type LanguageInput } from "shiki/core";
import { createJavaScriptRegexEngine } from "shiki/engine/javascript";

const LOADERS: Record<string, () => Promise<{ default: LanguageInput }>> = {
  c: () => import("@shikijs/langs/c"),
  cpp: () => import("@shikijs/langs/cpp"),
  csharp: () => import("@shikijs/langs/csharp"),
  css: () => import("@shikijs/langs/css"),
  diff: () => import("@shikijs/langs/diff"),
  docker: () => import("@shikijs/langs/docker"),
  go: () => import("@shikijs/langs/go"),
  html: () => import("@shikijs/langs/html"),
  ini: () => import("@shikijs/langs/ini"),
  java: () => import("@shikijs/langs/java"),
  javascript: () => import("@shikijs/langs/javascript"),
  json: () => import("@shikijs/langs/json"),
  jsx: () => import("@shikijs/langs/jsx"),
  kotlin: () => import("@shikijs/langs/kotlin"),
  lua: () => import("@shikijs/langs/lua"),
  make: () => import("@shikijs/langs/make"),
  markdown: () => import("@shikijs/langs/markdown"),
  php: () => import("@shikijs/langs/php"),
  powershell: () => import("@shikijs/langs/powershell"),
  python: () => import("@shikijs/langs/python"),
  r: () => import("@shikijs/langs/r"),
  ruby: () => import("@shikijs/langs/ruby"),
  rust: () => import("@shikijs/langs/rust"),
  shell: () => import("@shikijs/langs/shell"),
  sql: () => import("@shikijs/langs/sql"),
  swift: () => import("@shikijs/langs/swift"),
  toml: () => import("@shikijs/langs/toml"),
  tsx: () => import("@shikijs/langs/tsx"),
  typescript: () => import("@shikijs/langs/typescript"),
  xml: () => import("@shikijs/langs/xml"),
  yaml: () => import("@shikijs/langs/yaml"),
};

const ALIASES: Record<string, string> = {
  bash: "shell",
  cjs: "javascript",
  console: "shell",
  dockerfile: "docker",
  htm: "html",
  jsonl: "json",
  makefile: "make",
  md: "markdown",
  mjs: "javascript",
  ps1: "powershell",
  py: "python",
  rb: "ruby",
  rs: "rust",
  sh: "shell",
  ts: "typescript",
  yml: "yaml",
  zsh: "shell",
};

let highlighterPromise: ReturnType<typeof createHighlighterCore> | null = null;
const languageLoads = new Map<string, Promise<void>>();

function getHighlighter() {
  if (!highlighterPromise) {
    highlighterPromise = createHighlighterCore({
      themes: [githubLight, githubDark],
      langs: [],
      engine: createJavaScriptRegexEngine(),
    });
  }
  return highlighterPromise;
}

async function loadLanguage(language: string): Promise<string> {
  const id = ALIASES[language] ?? language;
  const loader = LOADERS[id];
  if (!loader) return "text";

  let load = languageLoads.get(id);
  if (!load) {
    const highlighter = await getHighlighter();
    load = loader()
      .then((module) => highlighter.loadLanguage(module.default))
      .catch((error: unknown) => {
        languageLoads.delete(id);
        throw error;
      });
    languageLoads.set(id, load);
  }
  await load;
  return id;
}

export async function highlightCode(
  code: string,
  language: string,
): Promise<string> {
  const highlighter = await getHighlighter();
  const lang = await loadLanguage(language);
  return highlighter.codeToHtml(code, {
    lang,
    themes: { light: "github-light", dark: "github-dark" },
  });
}
