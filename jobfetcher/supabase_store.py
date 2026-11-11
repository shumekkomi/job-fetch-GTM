"""Read from and write to Supabase (Postgres).

The same three jobs as airtable.py, against the jobhunt schema:
  1. Fetching existing records for dedup (URLs and company+title pairs).
  2. Inserting new job records into jobhunt.jobs.
  3. Inserting run log records into jobhunt.run_log.

The script talks to the database directly over a Postgres connection rather
than through Supabase's web API. That way the jobhunt schema never has to be
exposed on the public API, and nothing outside this script and the Supabase
dashboard can read or write it.

The connection string comes from the SUPABASE_DB_URL environment variable (set
as a GitHub secret, never committed to the repo). Use the Session pooler string
from Supabase's Connect panel: GitHub's runners can't reach the direct
connection, which is IPv6 only.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Set, Tuple

from .models import Job

# Rows this script writes are tagged so they can be told apart from rows
# imported from Airtable or written by other tools.
PIPELINE = "claude"
DATA_SOURCE = "job-fetch"

# One connection per run, opened on first use and closed by close().
_conn = None


def _get_url() -> str:
    url = os.environ.get("SUPABASE_DB_URL", "")
    if not url:
        raise RuntimeError(
            "SUPABASE_DB_URL environment variable is not set. "
            "Set it to the Session pooler connection string from Supabase."
        )
    return url


def _connect():
    """Open the run's connection, or return the one already open."""
    global _conn
    if _conn is not None and not _conn.closed:
        return _conn
    # Imported here so dry runs and the Airtable path don't need psycopg.
    import psycopg

    # autocommit: each insert is saved straight away, like an Airtable request,
    # so one failed company can't roll back the companies before it.
    # prepare_threshold=None: Supabase's pooler can't share prepared statements.
    _conn = psycopg.connect(_get_url(), autocommit=True, prepare_threshold=None, connect_timeout=30)
    return _conn


def close() -> None:
    """Close the run's connection, if one was opened."""
    global _conn
    if _conn is not None and not _conn.closed:
        _conn.close()
    _conn = None


# ---------------------------------------------------------------------------
# Reading existing records for dedup
# ---------------------------------------------------------------------------

def fetch_existing_jobs() -> Tuple[Set[str], Set[str]]:
    """Fetch every existing URL and company|title pair from jobhunt.jobs.

    Returns (existing_urls, existing_company_titles), both lowercased sets.
    Reads every row, whichever tool wrote it, so a role imported from Airtable
    or saved by an earlier run is never written again.
    """
    existing_urls: Set[str] = set()
    existing_company_titles: Set[str] = set()

    with _connect().cursor() as cur:
        cur.execute("select job_url, company, role_title from jobhunt.jobs")
        for job_url, company, title in cur.fetchall():
            url = (job_url or "").strip().lower()
            company = (company or "").strip().lower()
            title = (title or "").strip().lower()
            if url:
                existing_urls.add(url)
            if company and title:
                existing_company_titles.add("{}|{}".format(company, title))

    return existing_urls, existing_company_titles


# ---------------------------------------------------------------------------
# Writing new job records
# ---------------------------------------------------------------------------

_JOB_COLUMNS = (
    "pipeline", "data_source", "job_label", "company", "role_title", "source",
    "jd_text", "raw_blob", "job_url", "apply_url", "salary_posted",
    "salary_min", "salary_max", "salary_currency", "salary_interval",
    "location", "date_posted", "posted_date_kind", "fingerprint", "lane",
    "status", "match_score", "notes", "first_seen",
)

# A URL already in the table is skipped, never overwritten: dedup should have
# caught it, and this stops a dedup bug from ever writing a row twice.
_INSERT_JOB_SQL = (
    "insert into jobhunt.jobs ({cols}) values ({vals}) "
    "on conflict (job_url) do nothing returning id"
).format(cols=", ".join(_JOB_COLUMNS), vals=", ".join(["%s"] * len(_JOB_COLUMNS)))


def _job_to_row(job: Job, source: str, now: datetime) -> Dict[str, Any]:
    """Convert a Job into a jobhunt.jobs row keyed by column name."""
    return {
        "pipeline":         PIPELINE,
        "data_source":      DATA_SOURCE,
        "job_label":        "{} — {}".format(job.company, job.title),
        "company":          job.company,
        "role_title":       job.title,
        "source":           source,
        "jd_text":          job.description,
        "raw_blob":         json.dumps(job.raw, ensure_ascii=False, default=str),
        "job_url":          job.url,
        "apply_url":        job.apply_url,
        "salary_posted":    job.salary_text,
        "salary_min":       job.salary_min,
        "salary_max":       job.salary_max,
        "salary_currency":  job.salary_currency,
        "salary_interval":  job.salary_interval,
        "location":         job.location,
        "date_posted":      job.posted_date,
        "posted_date_kind": job.posted_date_kind or None,
        "fingerprint":      job.fingerprint,
        "lane":             job.lane,
        "status":           "New",
        "match_score":      job.match_score,
        "notes":            job.notes or None,
        "first_seen":       now,
    }


def insert_jobs(jobs: List[Job], source: str = "Direct") -> int:
    """Insert jobs into jobhunt.jobs. Returns the count actually created."""
    now = datetime.now(timezone.utc)
    created = 0
    with _connect().cursor() as cur:
        for job in jobs:
            row = _job_to_row(job, source, now)
            cur.execute(_INSERT_JOB_SQL, [row[c] for c in _JOB_COLUMNS])
            if cur.fetchone() is not None:
                created += 1
    return created


# ---------------------------------------------------------------------------
# Writing run log records
# ---------------------------------------------------------------------------

def insert_run_log(
    company: str,
    run_type: str,
    outcome: str,
    new_count: int,
    note: str = "",
) -> None:
    """Insert one row into jobhunt.run_log."""
    now = datetime.now(timezone.utc)
    with _connect().cursor() as cur:
        cur.execute(
            "insert into jobhunt.run_log "
            "(pipeline, data_source, target, type, last_polled, polled_at, outcome, listings_found, notes) "
            "values (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
            [PIPELINE, DATA_SOURCE, company, run_type, now.date(), now, outcome, new_count, note or None],
        )
