"""Test whether Workable's cross-employer job search can be read by this script.

This is a probe, not a fetcher: it saves nothing and touches no database. It
answers one question before anything is built: does jobs.workable.com return
usable search results to a plain script running on GitHub's servers?

Why: Workable's per-company feed (adapters/workable.py) has returned empty
lists since Sep 2026, and 15 of the 80 roles you acted on or held between
Sep and Nov 2026 were Workable postings the pipeline never saw. jobs.workable.com
searches every Workable employer at once by keyword, which is how Grokbot finds them.

The probe tries two ways in, for each search term:
  1. The JSON endpoint the jobs.workable.com search page appears to use
     (/api/v1/jobs). Not documented by Workable, so the shape is checked, not assumed.
  2. The search page itself, looking for job data embedded in the HTML.

It identifies itself honestly (the same user agent as the fetcher) and waits
between requests. If Workable blocks that, the answer is "no", and we stop.

Run it from the Actions tab ("Probe Workable search") or locally:
    python probe_workable.py
    python probe_workable.py --terms "CRM" "revenue operations" --pages 2
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from typing import Any, Dict, List, Optional, Tuple

from jobfetcher import http
from jobfetcher.config import load_config
from jobfetcher.fit import title_passes
from jobfetcher.models import FetchError

API_URL = "https://jobs.workable.com/api/v1/jobs"
SEARCH_URL = "https://jobs.workable.com/search"
DEFAULT_LOCATION = "London, United Kingdom"
DEFAULT_TERMS = [
    "CRM", "lifecycle marketing", "retention marketing", "email marketing",
    "marketing operations", "marketing automation", "revenue operations",
    "GTM engineer", "growth marketing", "HubSpot",
]
PAUSE_SECONDS = 1.5


# ---------------------------------------------------------------------------
# Reading whatever comes back
# ---------------------------------------------------------------------------

def _text(value: Any) -> str:
    """A readable string from a field that may be a string, a dict or a list."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        for key in ("title", "name", "city", "location"):
            if isinstance(value.get(key), str) and value[key]:
                parts = [value[key]]
                if key == "city" and isinstance(value.get("country"), str):
                    parts.append(value["country"])
                return ", ".join(parts)
        return json.dumps(value)[:80]
    if isinstance(value, list):
        return "; ".join(_text(v) for v in value[:3])
    return str(value)


def parse_job(item: Dict[str, Any]) -> Dict[str, str]:
    """Pull the fields we'd need from one search result, whatever the exact shape."""
    return {
        "title": _text(item.get("title")),
        "company": _text(item.get("company")),
        "location": _text(item.get("location") or item.get("locations")),
        "created": _text(item.get("created") or item.get("published") or item.get("publishedAt")),
        "url": _text(item.get("url") or item.get("shortlink") or item.get("applyUrl")),
        "has_description": "yes" if item.get("description") else "no",
    }


def find_jobs(payload: Any) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    """Return (job items, next page token) from an API response of unknown shape."""
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)], None
    if not isinstance(payload, dict):
        return [], None
    token = payload.get("nextPageToken") or payload.get("next_page_token") or payload.get("nextPage")
    for key in ("jobs", "results", "data", "items"):
        if isinstance(payload.get(key), list):
            return [x for x in payload[key] if isinstance(x, dict)], token
    return [], token


_EMBEDDED = [
    re.compile(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S),
    re.compile(r"window\.__INITIAL_STATE__\s*=\s*(\{.*?\});?\s*</script>", re.S),
    re.compile(r"window\.__APOLLO_STATE__\s*=\s*(\{.*?\});?\s*</script>", re.S),
]


def embedded_jobs(html: str) -> int:
    """Count objects that look like jobs in JSON embedded in the search page."""
    for pattern in _EMBEDDED:
        m = pattern.search(html)
        if not m:
            continue
        try:
            data = json.loads(m.group(1))
        except ValueError:
            continue
        found = 0

        def walk(node):
            nonlocal found
            if isinstance(node, dict):
                if "title" in node and ("company" in node or "shortcode" in node):
                    found += 1
                for v in node.values():
                    walk(v)
            elif isinstance(node, list):
                for v in node:
                    walk(v)

        walk(data)
        return found
    return 0


# ---------------------------------------------------------------------------
# The probe
# ---------------------------------------------------------------------------

def probe_api(term: str, location: str, pages: int, lanes, exclude) -> Dict[str, Any]:
    out: Dict[str, Any] = {"term": term, "ok": False, "pages": 0, "jobs": [], "error": "", "shape": ""}
    token = None
    for page in range(pages):
        params = {"query": term, "location": location}
        if token:
            params["pageToken"] = token
        try:
            payload = http.get_json(API_URL, params=params)
        except FetchError as exc:
            out["error"] = str(exc)
            break
        items, token = find_jobs(payload)
        if page == 0:
            keys = sorted(payload.keys()) if isinstance(payload, dict) else type(payload).__name__
            first = sorted(items[0].keys()) if items else []
            out["shape"] = "top-level keys: {}; job keys: {}".format(keys, first)
        out["ok"] = True
        out["pages"] += 1
        out["jobs"].extend(parse_job(i) for i in items)
        if not token or not items:
            break
        time.sleep(PAUSE_SECONDS)
    for job in out["jobs"]:
        job["passes"] = title_passes(job["title"], lanes, exclude)
    return out


def probe_page(term: str, location: str) -> str:
    try:
        response = http.get(SEARCH_URL, params={"query": term, "location": location})
    except FetchError as exc:
        return "search page: {}".format(exc)
    n = embedded_jobs(response.text)
    return "search page: HTTP {}, {} bytes, {} jobs found in embedded data".format(
        response.status_code, len(response.text), n)


def report(results: List[Dict[str, Any]], page_notes: List[str], location: str) -> str:
    """Markdown summary: did it work, how many results, how many pass the title rules."""
    lines = ["# Workable search probe", "", "Location: {}".format(location), ""]
    worked = [r for r in results if r["ok"] and r["jobs"]]
    if worked:
        lines.append("**Result: the JSON search returned jobs for {} of {} terms.**".format(len(worked), len(results)))
    else:
        lines.append("**Result: the JSON search returned no jobs. See errors below.**")
    lines += ["", "| Term | Pages | Results | Pass title rules | Note |", "|---|---|---|---|---|"]
    for r in results:
        passing = sum(1 for j in r["jobs"] if j["passes"])
        note = r["error"] or ("" if r["jobs"] else "no jobs in response")
        lines.append("| {} | {} | {} | {} | {} |".format(r["term"], r["pages"], len(r["jobs"]), passing, note))
    if results and results[0]["shape"]:
        lines += ["", "Response shape: {}".format(results[0]["shape"])]
    lines += ["", "## Search page check", ""] + ["- {}".format(n) for n in page_notes]

    seen = set()
    rows = []
    for r in results:
        for j in r["jobs"]:
            key = (j["company"].lower(), j["title"].lower())
            if j["passes"] and key not in seen:
                seen.add(key)
                rows.append(j)
    lines += ["", "## Roles that pass the title rules ({} unique)".format(len(rows)), ""]
    if rows:
        lines += ["| Title | Company | Location | Created | Description in result | URL |", "|---|---|---|---|---|---|"]
        for j in sorted(rows, key=lambda x: x["created"], reverse=True)[:60]:
            lines.append("| {title} | {company} | {location} | {created} | {has_description} | {url} |".format(**{
                k: str(v).replace("|", "/") for k, v in j.items()}))
    return "\n".join(lines) + "\n"


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Probe Workable's cross-employer search. Saves nothing.")
    parser.add_argument("--terms", nargs="+", default=DEFAULT_TERMS)
    parser.add_argument("--location", default=DEFAULT_LOCATION)
    parser.add_argument("--pages", type=int, default=3, help="pages per term (default 3)")
    parser.add_argument("--config", default="config.yaml")
    args = parser.parse_args(argv)

    config = load_config(args.config)
    results, page_notes = [], []
    for i, term in enumerate(args.terms):
        if i:
            time.sleep(PAUSE_SECONDS)
        results.append(probe_api(term, args.location, args.pages, config.title_lanes, config.title_exclude))
    # One check of the HTML page is enough to see whether it carries data.
    page_notes.append(probe_page(args.terms[0], args.location))

    summary = report(results, page_notes, args.location)
    print(summary)
    step_summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if step_summary:
        with open(step_summary, "a") as f:
            f.write(summary)
    # A probe that learns "no" has still done its job: exit 0 either way.
    return 0


if __name__ == "__main__":
    sys.exit(main())
