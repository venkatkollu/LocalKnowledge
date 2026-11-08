#!/usr/bin/env python3
"""Verify the local graph database and report integrity problems."""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

DEFAULT_DB = Path(__file__).resolve().parent / "data" / "graphdb.sqlite3"


def verify(path: Path, top: int = 10) -> int:
    if not path.exists():
        print(f"Graph database not found: {path}", file=sys.stderr)
        print("Build it with: python3 data/build_graphdb.py", file=sys.stderr)
        return 1

    connection = sqlite3.connect(path)
    try:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        missing = {"nodes", "edges", "meta"} - tables
        if missing:
            print(f"Missing tables: {', '.join(sorted(missing))}", file=sys.stderr)
            return 1

        node_count = connection.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
        edge_count = connection.execute("SELECT COUNT(*) FROM edges").fetchone()[0]
        print(f"Graph: {path}")
        print(f"Nodes: {node_count}")
        print(f"Edges: {edge_count}")

        print("\nNodes by type:")
        for node_type, count in connection.execute(
            "SELECT type, COUNT(*) FROM nodes GROUP BY type ORDER BY 2 DESC"
        ):
            print(f"  {node_type:20} {count}")

        print("\nEdges by kind:")
        for kind, count in connection.execute(
            "SELECT kind, COUNT(*) FROM edges GROUP BY kind ORDER BY 2 DESC"
        ):
            print(f"  {kind:16} {count}")

        print(f"\nTop {top} documents by chunk count:")
        for name, chunks in connection.execute(
            """
            SELECT d.name, COUNT(e.dst) AS chunks
            FROM edges e
            JOIN nodes d ON d.id = e.src
            JOIN nodes c ON c.id = e.dst
            WHERE d.type='document' AND c.type='chunk' AND e.kind='HAS'
            GROUP BY d.name ORDER BY chunks DESC LIMIT ?
            """,
            (top,),
        ):
            print(f"  {name:30} {chunks} chunks")

        print("\nMeta:")
        for key, value in connection.execute("SELECT key, value FROM meta ORDER BY key"):
            print(f"  {key}: {value}")

        dangling_src = connection.execute(
            "SELECT COUNT(*) FROM edges e LEFT JOIN nodes n ON n.id=e.src WHERE n.id IS NULL"
        ).fetchone()[0]
        dangling_dst = connection.execute(
            "SELECT COUNT(*) FROM edges e LEFT JOIN nodes n ON n.id=e.dst WHERE n.id IS NULL"
        ).fetchone()[0]

        print("\nIntegrity:")
        print(f"  dangling edge sources:      {dangling_src}")
        print(f"  dangling edge destinations: {dangling_dst}")

        if dangling_src or dangling_dst:
            print(
                "\nFAIL: rebuild with `python3 data/build_graphdb.py`",
                file=sys.stderr,
            )
            return 2
        print("\nOK")
        return 0
    finally:
        connection.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify the local graph database")
    parser.add_argument(
        "path",
        nargs="?",
        type=Path,
        default=DEFAULT_DB,
        help=f"graph database (default: {DEFAULT_DB})",
    )
    parser.add_argument("--top", type=int, default=10, help="documents to show")
    args = parser.parse_args()
    return verify(args.path, max(1, args.top))


if __name__ == "__main__":
    raise SystemExit(main())
