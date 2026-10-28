import type { LucideIcon } from "lucide-react";
import {
  Braces,
  Database,
  FileCode2,
  FileText,
  File as FileIcon,
  Palette,
  Table,
} from "lucide-react";
import { extensionOf, languageFor } from "@/lib/file-kind";

const BY_EXTENSION: Record<string, LucideIcon> = {
  md: FileText,
  markdown: FileText,
  txt: FileText,
  pdf: FileText,
  py: FileCode2,
  js: FileCode2,
  jsx: FileCode2,
  ts: FileCode2,
  tsx: FileCode2,
  java: FileCode2,
  c: FileCode2,
  h: FileCode2,
  cpp: FileCode2,
  hpp: FileCode2,
  go: FileCode2,
  rs: FileCode2,
  json: Braces,
  yaml: Braces,
  yml: Braces,
  toml: Braces,
  csv: Table,
  html: FileCode2,
  css: Palette,
  scss: Palette,
  sql: Database,
  sh: FileCode2,
};

export function fileIconFor(filename: string): LucideIcon {
  return BY_EXTENSION[extensionOf(filename)] ?? FileIcon;
}

/** Re-exported for the inspector; the map lives in `file-kind.ts`. */
export { extensionOf, languageFor };
