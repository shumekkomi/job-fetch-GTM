"""Load and validate the YAML config file.

The config holds everything you'd want to change without touching code:
  - which companies to fetch from (the watchlist)
  - which job titles to match (the title lanes)
  - location rules, salary floor, Airtable IDs

It's designed so a second "profile" (e.g. signal mode for the portfolio project)
can be added later without a rewrite: each profile would be a separate YAML file
with its own targets, titles, and destination table.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import yaml


@dataclass
class Company:
    """One entry on the watchlist."""
    name: str
    ats: str                # greenhouse, ashby, lever, etc.
    slug: str               # the board identifier or URL (for jsonld)
    careers_url: str = ""   # the public careers page, for reference
    tier: int = 1           # priority tier (1 = most important)
    status: str = "active"  # active, paused, unsupported, broken
    # Per-company location overrides. If set, these strings also count as "London".
    location_aliases: List[str] = field(default_factory=list)
    # If True, keep remote roles with no region stated and mark them.
    keep_unqualified_remote: bool = False


@dataclass
class Config:
    """Everything the script needs to run."""
    companies: List[Company]
    title_lanes: Dict[str, List[str]]    # lane name -> list of title substrings
    default_location: str = "London"     # the default location to filter for
    salary_floor_gbp: float = 35000.0    # drop jobs with salary explicitly below this
    airtable_base_id: str = ""
    airtable_jobs_table_id: str = ""
    airtable_runlog_table_id: str = ""
    resume_path: Optional[str] = None  # path to a .txt/.md resume for scoring


def load_config(path: str = "config.yaml") -> Config:
    """Read and validate the config file. Raises on anything missing or wrong."""
    if not os.path.exists(path):
        raise FileNotFoundError("Config file not found: {}".format(path))

    with open(path, "r") as f:
        raw = yaml.safe_load(f)

    if not isinstance(raw, dict):
        raise ValueError("Config file must be a YAML mapping, got {}".format(type(raw).__name__))

    # -- Companies --
    companies = []
    for entry in raw.get("companies", []):
        companies.append(Company(
            name=entry["name"],
            ats=entry["ats"],
            slug=entry["slug"],
            careers_url=entry.get("careers_url", ""),
            tier=entry.get("tier", 1),
            status=entry.get("status", "active"),
            location_aliases=entry.get("location_aliases", []),
            keep_unqualified_remote=entry.get("keep_unqualified_remote", False),
        ))

    if not companies:
        raise ValueError("Config must have at least one company in the 'companies' list")

    # -- Title lanes --
    title_lanes = raw.get("title_lanes", {})
    if not title_lanes:
        raise ValueError("Config must have at least one entry in 'title_lanes'")

    # -- Airtable --
    airtable = raw.get("airtable", {})

    return Config(
        companies=companies,
        title_lanes=title_lanes,
        default_location=raw.get("default_location", "London"),
        salary_floor_gbp=float(raw.get("salary_floor_gbp", 35000)),
        airtable_base_id=airtable.get("base_id", ""),
        airtable_jobs_table_id=airtable.get("jobs_table_id", ""),
        airtable_runlog_table_id=airtable.get("runlog_table_id", ""),
        resume_path=raw.get("resume_path"),
    )
