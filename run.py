#!/usr/bin/env python3
"""Entry point for the job fetcher.

Usage:
    python run.py                  # full run: fetch, filter, dedup, save
    python run.py --dry-run        # fetch and filter, but don't write anything
    python run.py --config other.yaml   # use a different config file
    python run.py --resume cv.md        # score jobs against a different CV
    python run.py --catch-up            # LinkedIn searches without date windows (one-off backlog sweep)

The --dry-run flag is your safety net: run it first to see what would happen,
then do a real run once you're happy with the output.
"""
import argparse
import sys

from jobfetcher.config import load_config
from jobfetcher.runner import exit_code, run


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fetch job listings from ATS APIs and save them to Supabase or Airtable."
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Fetch and filter, but save nothing. Shows what would be inserted.",
    )
    parser.add_argument(
        "--config", default="config.yaml",
        help="Path to the config file (default: config.yaml).",
    )
    parser.add_argument(
        "--resume",
        help="Path to your resume (.txt or .md). Scores each job 0-100 by keyword match. "
             "Overrides resume_path in config.yaml.",
    )
    parser.add_argument(
        "--catch-up", action="store_true",
        help="Run each LinkedIn search once, ranked by relevance with no date limit, "
             "instead of the linkedin_windows in config.yaml. For a one-off sweep of older roles.",
    )
    args = parser.parse_args()

    try:
        config = load_config(args.config)
    except (FileNotFoundError, ValueError) as exc:
        print("Config error: {}".format(exc), file=sys.stderr)
        sys.exit(1)

    if args.catch_up:
        config.linkedin_windows = []
        print("Catch-up run: LinkedIn searches ranked by relevance, no date limit.", file=sys.stderr)

    summary = run(config, dry_run=args.dry_run, resume_path=args.resume)

    # A non-zero exit turns the GitHub Actions run red, which sends an email.
    sys.exit(exit_code(summary))


if __name__ == "__main__":
    main()
