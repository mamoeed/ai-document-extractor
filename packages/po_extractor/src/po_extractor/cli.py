"""Debug CLI: python -m po_extractor <file> --customer-master <path> --item-master <path> [--pretty]"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import Optional, Sequence

from .config import ConfigError, Settings
from .errors import MasterDataError
from .pipeline import process_file


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m po_extractor",
        description="Extract a purchase order and match it against the master data. Prints the ProcessingResult JSON.",
    )
    parser.add_argument("file", help="PDF, PNG/JPG or XLSX purchase order")
    parser.add_argument("--customer-master", required=True, help="path to the customer master .xlsx")
    parser.add_argument("--item-master", required=True, help="path to the item master .xlsx")
    parser.add_argument("--pretty", action="store_true", help="indent the JSON output")
    parser.add_argument(
        "--env-file",
        default=".env",
        help="read settings from this file if it exists (default: .env); real env vars take precedence",
    )
    parser.add_argument("--log-level", default="INFO", help="log level for stderr (default: INFO)")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=args.log_level.upper(),
        format="%(asctime)s %(levelname)-7s [%(name)s] %(message)s",
        stream=sys.stderr,
    )
    for noisy in ("openai", "httpx", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    env_file = Path(args.env_file)
    settings = Settings(_env_file=env_file) if env_file.is_file() else Settings()  # type: ignore[call-arg]

    try:
        result = process_file(args.file, args.customer_master, args.item_master, settings)
    except (ConfigError, MasterDataError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    print(result.model_dump_json(indent=2 if args.pretty else None))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
