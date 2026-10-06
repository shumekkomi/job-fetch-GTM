"""The main pipeline: fetch -> filter -> dedup -> write.

This is the file that `run.py` calls. It orchestrates each step in order:
  1. Load the config.
  2. Fetch existing Airtable records (for dedup).
  3. For each active company: fetch, filter, dedup, write.
  4. Write the run log.

Each company runs independently: one failing does not stop the others.
The exception is Airtable itself: if the existing records cannot be read, the
run stops before writing anything, because writing blind creates duplicates.
"""
from __future__ import annotations

import logging
import sys
from typing import List, Optional, Set, Tuple

from .adapters import ADAPTERS
from .airtable import fetch_existing_jobs, insert_jobs, insert_run_log
from .apply_lookup import ApplyUrlFinder
from .config import Company, Config
from .dedup import dedup
from .filters import filter_jobs
from .models import CompanyResult, Job
from .resume import extract_keywords, load_resume, score_job

logger = logging.getLogger("jobfetcher")


def _setup_logging() -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s", "%H:%M:%S"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)


def run(config: Config, dry_run: bool = False, resume_path: Optional[str] = None) -> dict:
    """Run the full pipeline. Returns a summary dict for testing/inspection.

    If dry_run is True, fetches and filters but writes nothing to Airtable.
    resume_path overrides config.resume_path (CLI flag wins over config file).
    """
    _setup_logging()

    summary = {
        "companies_processed": 0,
        "total_new_jobs": 0,
        "results": [],    # one dict per company
        "dry_run": dry_run,
        "aborted": False,
        "airtable_errors": 0,
    }

    # -- Load resume keywords if a resume was provided --
    resume_file = resume_path or config.resume_path
    resume_keywords = None
    if resume_file:
        try:
            text = load_resume(resume_file)
            resume_keywords = extract_keywords(text)
            logger.info("Loaded resume: %d keywords extracted from %s", len(resume_keywords), resume_file)
        except (FileNotFoundError, ValueError) as exc:
            logger.warning("Could not load resume: %s (scoring disabled)", exc)

    # -- Step 1: fetch existing Airtable records for dedup --
    existing_urls: Set[str] = set()
    existing_company_titles: Set[str] = set()
    if not dry_run:
        missing = [name for name, value in (
            ("AIRTABLE_BASE_ID", config.airtable_base_id),
            ("AIRTABLE_JOBS_TABLE_ID", config.airtable_jobs_table_id),
            ("AIRTABLE_RUNLOG_TABLE_ID", config.airtable_runlog_table_id),
        ) if not value]
        if missing:
            logger.error("Stopping: environment variables not set: %s", ", ".join(missing))
            summary["aborted"] = True
            return summary
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
            logger.error("Stopping: without dedup every job would be written again.")
            summary["aborted"] = True
            return summary

    # -- Step 2: process each company --
    active_companies = [c for c in config.companies if c.status == "active"]
    skipped_companies = [c for c in config.companies if c.status in ("broken", "unsupported", "paused")]

    logger.info(
        "Processing %d active companies (%d skipped: %s)",
        len(active_companies),
        len(skipped_companies),
        ", ".join(c.name for c in skipped_companies) if skipped_companies else "none",
    )

    apply_finder = ApplyUrlFinder()  # shared so each company's board is looked up once per run
    for company in active_companies:
        result = _process_company(
            company, config, existing_urls, existing_company_titles, dry_run,
            resume_keywords, apply_finder,
        )
        summary["results"].append(result)
        summary["total_new_jobs"] += result.get("new_count", 0)
        summary["companies_processed"] += 1

    # -- Step 3: log skipped companies --
    for company in skipped_companies:
        result = {
            "company": company.name, "outcome": "Skipped",
            "note": "Status: {}".format(company.status), "new_count": 0,
        }
        _log_run(config, company, result, dry_run)
        summary["results"].append(result)

    summary["airtable_errors"] = sum(1 for r in summary["results"] if r.get("airtable_error"))
    if summary["airtable_errors"]:
        logger.error("%d Airtable writes failed. See the errors above.", summary["airtable_errors"])

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
    resume_keywords: Optional[Set[str]] = None,
    apply_finder: Optional[ApplyUrlFinder] = None,
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

    # -- LinkedIn jobs: look for the same role on the company's own board --
    found_on_board = 0
    already_saved: List[str] = []
    if apply_finder and company.ats == "linkedin" and new_jobs:
        new_jobs, already_saved = _attach_apply_urls(new_jobs, apply_finder, existing_urls)
        found_on_board = sum(1 for j in new_jobs if j.apply_url)
        logger.info(
            "%s: found the company's own posting for %d of %d new jobs",
            company.name, found_on_board + len(already_saved), len(new_jobs) + len(already_saved),
        )
        if already_saved:
            logger.info(
                "%s: %d already saved from the company's own board: %s",
                company.name, len(already_saved), "; ".join(already_saved),
            )

    # -- Score against resume --
    if resume_keywords and new_jobs:
        for job in new_jobs:
            job.match_score = score_job(job, resume_keywords)
        scored = sorted(new_jobs, key=lambda j: j.match_score or 0, reverse=True)
        new_jobs = scored

    # Build the note for the run log.
    note_parts = [stats.summary()]
    if dedup_result.skipped_url:
        note_parts.append("dedup (URL): {} skipped".format(len(dedup_result.skipped_url)))
    if dedup_result.skipped_title:
        note_parts.append("dedup (title repost): {} skipped".format(len(dedup_result.skipped_title)))
    if already_saved:
        note_parts.append("dedup (company board): {} skipped".format(len(already_saved)))
    if found_on_board:
        note_parts.append("company posting found: {}".format(found_on_board))
    result["note"] = "; ".join(note_parts)

    # -- Write --
    if new_jobs:
        if dry_run:
            logger.info("%s: DRY RUN -- would insert %d jobs:", company.name, len(new_jobs))
            for j in new_jobs:
                score_label = " score:{}".format(j.match_score) if j.match_score is not None else ""
                apply_label = " -> {}".format(j.apply_url) if j.apply_url else ""
                logger.info("  [%s%s] %s -- %s (%s)%s", j.lane, score_label, j.company, j.title, j.location, apply_label)
        else:
            try:
                created = insert_jobs(
                    config.airtable_base_id, config.airtable_jobs_table_id, new_jobs,
                    source="LinkedIn" if company.ats == "linkedin" else "Direct",
                )
                logger.info("%s: inserted %d new jobs", company.name, created)
                result["new_count"] = created

                # Add the new jobs to the dedup sets so later companies don't
                # insert the same job (unlikely, but possible across boards).
                for j in new_jobs:
                    existing_urls.add(j.url.strip().lower())
                    if j.apply_url:
                        existing_urls.add(j.apply_url.strip().lower())
                    existing_company_titles.add(
                        "{}|{}".format(j.company.strip().lower(), j.title.strip().lower())
                    )
            except Exception as exc:
                result["outcome"] = "Failed"
                result["airtable_error"] = True
                result["note"] += "; Airtable write failed: {}".format(exc)
                logger.error("%s: Airtable write failed: %s", company.name, exc)
    else:
        logger.info("%s: no new jobs to insert", company.name)

    if dry_run:
        result["new_count"] = len(new_jobs)

    _log_run(config, company, result, dry_run)
    return result


def _attach_apply_urls(
    jobs: List[Job], finder: ApplyUrlFinder, existing_urls: Set[str],
) -> Tuple[List[Job], List[str]]:
    """Set apply_url where the company's board has the same role.

    A job whose company posting is already in Airtable (saved earlier straight
    from that board) is dropped as a duplicate and returned as a label instead.
    """
    kept: List[Job] = []
    already_saved: List[str] = []
    for job in jobs:
        url = finder.find(job.company, job.title)
        if url and url.strip().lower() in existing_urls:
            already_saved.append("{} -- {}".format(job.company, job.title))
            continue
        job.apply_url = url
        kept.append(job)
    return kept, already_saved


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
        result["airtable_error"] = True
        logger.error("Could not write run log for %s: %s", company.name, exc)


def exit_code(summary: dict) -> int:
    """1 if the run should show as failed on GitHub Actions, else 0.

    A run fails if it stopped early, if any Airtable write failed, or if every
    source it actually tried to fetch failed. Skipped sources don't count,
    otherwise a single skipped company would hide a total outage.
    """
    if summary.get("aborted") or summary.get("airtable_errors"):
        return 1
    attempted = [r for r in summary["results"] if r.get("outcome") != "Skipped"]
    if attempted and all(r.get("outcome") == "Failed" for r in attempted):
        return 1
    return 0
