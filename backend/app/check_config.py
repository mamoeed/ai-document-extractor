"""Fail fast before migrations/uvicorn: `python -m app.check_config` exits 1 with a clear message."""

from __future__ import annotations

import sys

from pydantic import ValidationError

from po_extractor import ConfigError, Settings

from .config import AppSettings


def main() -> int:
    problems: list[str] = []
    try:
        Settings().require_llm()
    except ConfigError as exc:
        problems.append(str(exc))
    try:
        AppSettings()  # type: ignore[call-arg]
    except ValidationError as exc:
        for err in exc.errors():
            name = str(err["loc"][0]).upper() if err["loc"] else "?"
            problems.append(f"{name}: {err['msg']} (set it in .env)")

    if problems:
        print("\n" + "=" * 72, file=sys.stderr)
        print("CONFIGURATION ERROR - the backend cannot start:", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        print("=" * 72 + "\n", file=sys.stderr)
        return 1
    print("Configuration OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
