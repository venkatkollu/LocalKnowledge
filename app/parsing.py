from __future__ import annotations

import ast
from io import BytesIO
from pathlib import Path
import re

SUPPORTED = {".txt", ".md", ".markdown", ".py", ".js", ".jsx", ".ts", ".tsx", ".json", ".yaml", ".yml", ".csv", ".html", ".css", ".sql", ".java", ".go", ".rs", ".c", ".cpp", ".h", ".pdf"}
PARSER_VERSION = "structure-2.0"


class PythonParser:
    version = "python-ast-2.0"

    def parse(self, path: Path, raw: bytes) -> list[dict]:
        text = raw.decode("utf-8")
        tree = ast.parse(text, filename=str(path))
        lines = text.splitlines(keepends=True)
        imports = [ast.get_source_segment(text, node) for node in ast.walk(tree)
                   if isinstance(node, (ast.Import, ast.ImportFrom))]
        base = {"title": path.name, "language": "python", "file": str(path),
                "module": path.with_suffix("").name, "imports": imports}
        result = []
        covered = set()
        def add(node, symbol, cls=None):
            start = min([node.lineno] + [d.lineno for d in getattr(node, "decorator_list", [])])
            end = node.end_lineno
            covered.update(range(start, end + 1))
            result.append({**base, "content": "".join(lines[start - 1:end]), "section": symbol,
                           "symbol": symbol, "class": cls, "start_line": start, "end_line": end,
                           "kind": "class" if isinstance(node, ast.ClassDef) else "function"})
        for node in tree.body:
            if isinstance(node, ast.ClassDef):
                methods = [child for child in node.body if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))]
                if not methods:
                    add(node, node.name, node.name)
                else:
                    # A class header/docstring/fields is its own structure; methods
                    # retain qualified symbols and don't duplicate the whole class.
                    first = min(child.lineno for child in methods)
                    result.append({**base, "content": "".join(lines[node.lineno - 1:first - 1]),
                                   "section": node.name, "symbol": node.name, "class": node.name,
                                   "start_line": node.lineno, "end_line": first - 1, "kind": "class"})
                    covered.update(range(node.lineno, first))
                    for child in methods:
                        add(child, f"{node.name}.{child.name}", node.name)
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                add(node, node.name)
        # Keep imports, module documentation and executable module statements.
        start = None
        for number in range(1, len(lines) + 2):
            available = number <= len(lines) and number not in covered
            if available and start is None:
                start = number
            if not available and start is not None:
                content = "".join(lines[start - 1:number - 1])
                if content.strip():
                    result.append({**base, "content": content, "section": "Module", "kind": "module",
                                   "start_line": start, "end_line": number - 1})
                start = None
        return sorted(result, key=lambda item: item["start_line"])


class StructuredParser:
    version = PARSER_VERSION

    def __init__(self):
        self.code_parsers = {".py": PythonParser()}

    def parse(self, path: Path, raw: bytes) -> list[dict]:
        if path.suffix.lower() not in SUPPORTED:
            raise ValueError("Unsupported file extension")
        if path.suffix.lower() in self.code_parsers:
            return self.code_parsers[path.suffix.lower()].parse(path, raw)
        if path.suffix.lower() == ".pdf":
            from pypdf import PdfReader
            pages = PdfReader(BytesIO(raw)).pages
            return [{"title": path.stem, "section": f"Page {i}", "page": i, "content": page.extract_text() or ""}
                    for i, page in enumerate(pages, 1)]
        text = raw.decode("utf-8").replace("\x00", " ")
        title, section, subsection = path.stem, "Document", None
        lines = text.splitlines(keepends=True)
        result, start, fence = [], 1, False
        def emit(end):
            content = "".join(lines[start - 1:end])
            if content.strip():
                result.append({"title": title, "section": section, "subsection": subsection,
                               "content": content, "start_line": start, "end_line": end})
        for number, line in enumerate(lines, 1):
            if line.lstrip().startswith(("```", "~~~")):
                fence = not fence
            heading = re.match(r"^(#{1,6})\s+(.+?)\s*$", line) if not fence else None
            if heading:
                emit(number - 1)
                level, name = len(heading[1]), heading[2]
                if level == 1:
                    title, section, subsection = name, name, None
                elif level == 2:
                    section, subsection = name, None
                else:
                    subsection = name
                start = number
        emit(len(lines))
        return result
