"""The main pipeline: fetch -> filter -> dedup -> write.

This is the file that `run.py` calls. It orchestrates each step in order:
  1. Load the config.
  2. Fetch existing Airtable records (for dedup).
  3. For each active company: fetch, filter, dedup, write.
  4. Write the run log.

Each company runs independently: one failing does not stop the others.
"""
from __future__ import annotations

import logging
import sys
from typing import List, Set, Tuple

from .adapters import ADAPTERS
from .airtable import fetch_existing_jobs, insert_jobs, insert_run_log
from .config import Company, Config
from .dedup import DedupResult, dedup
from .filters import FilterStats, filter_jobs
from .models import CompanyResult, Job

logger = logging.getLogger("jobfetcher")


def _setup_logging() -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s", "%H:%M:%S"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)


def run(config: Config, dry_run: bool = False) -> dict:
    """Run the full pipeline. Returns a summary dict for testing/inspection.

    If dry_run is True, fetches and filters but writes nothing to Airtable.
    """
    _setup_logging()

    summary = {
        "companies_processed": 0,
        "total_new_jobs": 0,
        "results": [],    # one dict per company
        "dry_run": dry_run,
    }

    # -- Step 1: fetch existing Airtable records for dedup --
    existing_urls: Set[str] = set()
    existing_company_titles: Set[str] = set()
    if not dry_run:
        try:
            logger.info("Fetching existing Airtable records for dedup...")
            existing_urls, existing_company_titles = fetch_existing_jobs(
                config.airtable_base_id, config.airtable_jobs_table_id
            )
            logger.info(
                "Found %d existing URLs and %d company+title pairs",
                len(existing_urls), len(existing_company_titles),
            )
        except Exception as exc:
            logger.error("Could not fetch existing records: %s", exc)
            logger.info("Continuing without dedup (all jobs will be treated as new)")

    # -- Step 2: process each company --
    active_companies = [c for c in config.companies if c.status == "active"]
    skipped_companies = [c for c in config.companies if c.status in ("broken", "unsupported", "paused")]

    logger.info(
        "Processing %d active companies (%d skipped: %s)",
        len(active_companies),
        len(skipped_companies),
        ", ".join(c.name for c in skipped_companies) if skipped_companies else "none",
    )

    for company in active_companies:
        result = _process_company(
            company, config, existing_urls, existing_company_titles, dry_run
        )
        summary["results"].append(result)
        summary["total_new_jobs"] += result.get("new_count", 0)
        summary["companies_processed"] += 1

    # -- Step 3: log skipped companies --
    for company in skipped_companies:
        if not dry_run:
            try:
                insert_run_log(
                    config.airtable_base_id, config.airtable_runlog_table_id,
                    company=company.name, ats=company.ats,
                    outcome="Skipped", new_count=0,
                    note="Status: {}".format(company.status),
                )
            except Exception as exc:
                logger.error("Could not write run log for %s: %s", company.name, exc)

        summary["results"].append({
            "company": company.name, "outcome": "Skipped",
            "note": "Status: {}".format(company.status), "new_count": 0,
        })

    logger.info(
        "Done. %d companies processed, %d new jobs %s.",
        summary["companies_processed"], summary["total_new_jobs"],
        "would be inserted (dry run)" if dry_run else "inserted",
    )
    return summary


def _process_company(
    company: Company,
    config: Config,
    existing_urls: Set[str],
    existing_company_titles: Set[str],
    dry_run: bool,
) -> dict:
    """Fetch, filter, dedup, and write for one company. Never raises."""
    result = {"company": company.name, "outcome": "OK", "new_count": 0, "note": ""}

    # -- Fetch --
    adapter = ADAPTERS.get(company.ats)
    if not adapter:
        result["outcome"] = "Failed"
        result["note"] = "Unknown ATS type: {}".format(company.ats)
        logger.error("%s: %s", company.name, result["note"])
        _log_run(config, company, result, dry_run)
        return result

    logger.info("Fetching %s (%s/%s)...", company.name, company.ats, company.slug)
    try:
        fetch_result: CompanyResult = adapter(company.slug, company.name)
    except Exception as exc:
        result["outcome"] = "Failed"
        result["note"] = "Adapter crashed: {}".format(exc)
        logger.error("%s: %s", company.name, result["note"])
        _log_run(config, company, result, dry_run)
        return result

    # Non-OK outcomes (Empty, Failed, Skipped) come from the adapter itself.
    if fetch_result.outcome != "OK":
        result["outcome"] = fetch_result.outcome
        result["note"] = fetch_result.note or fetch_result.error or ""
        logger.warning("%s: %s -- %s", company.name, result["outcome"], result["note"])
        _log_run(config, company, result, dry_run)
        return result

    all_jobs = fetch_result.jobs
    logger.info("%s: fetched %d jobs", company.name, len(all_jobs))

    # -- Filter --
    passed, stats = filter_jobs(all_jobs, company, config)
    logger.info(
        "%s: %s", company.name, stats.summary(),
    )

    # -- Dedup --
    dedup_result = dedup(passed, existing_urls, existing_company_titles)
    new_jobs = dedup_result.new_jobs

    if dedup_result.skipped_url:
        logger.info(
            "%s: %d URL-matched duplicates skipped", company.name, len(dedup_result.skipped_url)
        )
    if dedup_result.skipped_title:
        logger.info(
            "%s: %d title-matched reposts skipped: %s",
            company.name, len(dedup_result.skipped_title),
            "; ".join(dedup_result.skipped_title),
        )

    # Build the note for the run log.
    note_parts = [stats.summary()]
    if dedup_result.skipped_url:
        note_parts.append("dedup (URL): {} skipped".format(len(dedup_result.skipped_url)))
    if dedup_result.skipped_title:
        note_parts.append("dedup (title repost): {} skipped".format(len(dedup_result.skipped_title)))
    result["note"] = "; ".join(note_parts)

    # -- Write --
    if new_jobs:
        if dry_run:
            logger.info("%s: DRY RUN -- would insert %d jobs:", company.name, len(new_jobs))
            for j in new_jobs:
                logger.info("  [%s] %s -- %s (%s)", j.lane, j.company, j.title, j.location)
        else:
            try:
                created = insert_jobs(
                    config.airtable_base_id, config.airtable_jobs_table_id, new_jobs
                )
                logger.info("%s: inserted %d new jobs", company.name, created)
                result["new_count"] = created

                # Add the new jobs to the dedup sets so later companies don't
                # insert the same job (unlikely, but possible across boards).
                for j in new_jobs:
                    existing_urls.add(j.url.strip().lower())
                    existing_company_titles.add(
                        "{}|{}".format(j.company.strip().lower(), j.title.strip().lower())
                    )
            except Exception as exc:
                result["outcome"] = "Failed"
                result["note"] += "; Airtable write failed: {}".format(exc)
                logger.error("%s: Airtable write failed: %s", company.name, exc)
    else:
        logger.info("%s: no new jobs to insert", company.name)

    if dry_run:
        result["new_count"] = len(new_jobs)

    _log_run(config, company, result, dry_run)
    return result


def _log_run(config: Config, company: Company, result: dict, dry_run: bool) -> None:
    """Write one run log record to Airtable (unless it's a dry run)."""
    if dry_run:
        return
    try:
        insert_run_log(
            config.airtable_base_id, config.airtable_runlog_table_id,
            company=company.name, ats=company.ats,
            outcome=result["outcome"], new_count=result.get("new_count", 0),
            note=result.get("note", ""),
        )
    except Exception as exc:
        logger.error("Could not write run log for %s: %s", company.name, exc)
