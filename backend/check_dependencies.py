"""Check that the backend runtime dependencies are importable.

Run this with the same Python interpreter that will start uvicorn:
    python3 backend/check_dependencies.py
"""

from __future__ import annotations

import importlib
import importlib.metadata
import sys


REQUIRED = {
    "fastapi": "fastapi",
    "uvicorn": "uvicorn",
    "python-multipart": "multipart",
    "cryptography": "cryptography",
    "pypdf": "pypdf",
}


def main() -> int:
    missing: list[str] = []
    for distribution, module in REQUIRED.items():
        try:
            importlib.import_module(module)
            try:
                version = importlib.metadata.version(distribution)
            except importlib.metadata.PackageNotFoundError:
                version = "installed"
            print(f"OK      {distribution} ({version})")
        except ModuleNotFoundError:
            missing.append(distribution)
            print(f"MISSING {distribution}")
    if missing:
        print("\nInstall missing packages with:")
        print(f"  {sys.executable} -m pip install -r backend/requirements.txt")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
