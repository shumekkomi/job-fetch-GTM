#!/usr/bin/env python3
"""Entry point for the job fetcher.

Usage:
    python run.py                  # full run: fetch, filter, dedup, write to Airtable
    python run.py --dry-run        # fetch and filter, but don't write anything
    python run.py --config other.yaml   # use a different config file

The --dry-run flag is your safety net: run it first to see what would happen,
then do a real run once you're happy with the output.
"""
import argparse
import sys

from jobfetcher.config import load_config
from jobfetcher.runner import run


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fetch job listings from ATS APIs and write them to Airtable."
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Fetch and filter, but don't write to Airtable. Shows what would be inserted.",
    )
    parser.add_argument(
        "--config", default="config.yaml",
        help="Path to the config file (default: config.yaml).",
    )
    args = parser.parse_args()

    try:
        config = load_config(args.config)
    except (FileNotFoundError, ValueError) as exc:
        print("Config error: {}".format(exc), file=sys.stderr)
        sys.exit(1)

    summary = run(config, dry_run=args.dry_run)

    # Exit with code 1 if every company failed (something is probably wrong).
    all_failed = all(r.get("outcome") in ("Failed",) for r in summary["results"])
    if all_failed and summary["companies_processed"] > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
