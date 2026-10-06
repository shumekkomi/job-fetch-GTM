"""Find a LinkedIn job's original posting on the company's own job board.

Logged-out LinkedIn pages hide where the "Apply" button leads, so we can't read
the link from LinkedIn. Instead we guess the company's board name from the
company name, look on the boards this repo already knows how to read, and keep
a link only when that board has a posting with exactly the same title. A wrong
guess (say, a different company that happens to use the same board name) is
caught by the title check; a role that isn't there simply gets no link.
"""
from __future__ import annotations

import re
from typing import Callable, Dict, List, Optional, Tuple

from .adapters.smartrecruiters import _fetch_all_postings
from .http import get_json
from .models import FetchError

Posting = Tuple[str, str]  # (title, url)

_GREENHOUSE = "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs"
_ASHBY = "https://api.ashbyhq.com/posting-api/job-board/{slug}"
_LEVER = "https://api.lever.co/v0/postings/{slug}"


def _greenhouse(slug: str) -> List[Posting]:
    jobs = get_json(_GREENHOUSE.format(slug=slug)).get("jobs", [])
    return [(j.get("title", ""), j.get("absolute_url", "")) for j in jobs]


def _ashby(slug: str) -> List[Posting]:
    jobs = get_json(_ASHBY.format(slug=slug)).get("jobs", [])
    return [(j.get("title", ""), j.get("jobUrl", "")) for j in jobs]


def _lever(slug: str) -> List[Posting]:
    jobs = get_json(_LEVER.format(slug=slug), params={"mode": "json"})
    return [(j.get("text", ""), j.get("hostedUrl", "")) for j in jobs]


def _smartrecruiters(slug: str) -> List[Posting]:
    return [
        (p.get("name", ""), "https://jobs.smartrecruiters.com/{}/{}".format(slug, p.get("id", "")))
        for p in _fetch_all_postings(slug)
    ]


BOARDS: List[Tuple[str, Callable[[str], List[Posting]]]] = [
    ("greenhouse", _greenhouse),
    ("ashby", _ashby),
    ("lever", _lever),
    ("smartrecruiters", _smartrecruiters),
]

# Words companies often drop from their board name ("Synthflow AI" -> "synthflow").
_DROPPABLE_WORDS = {"ltd", "limited", "plc", "inc", "llc", "group", "ai", "uk", "the", "co"}


def candidate_slugs(company: str) -> List[str]:
    """Board names to try, most likely first: "Mammoth Brands" -> mammothbrands, mammoth-brands."""
    words = re.sub(r"[^a-z0-9 ]", "", company.lower()).split()
    core = [w for w in words if w not in _DROPPABLE_WORDS] or words
    slugs: List[str] = []
    for parts in (words, core):
        for slug in ("".join(parts), "-".join(parts)):
            if len(slug) >= 2 and slug not in slugs:
                slugs.append(slug)
    return slugs


def normalise_title(title: str) -> str:
    """Lowercase, punctuation to spaces, single spaces: "GTM Engineer - Hybrid" -> "gtm engineer hybrid"."""
    return " ".join(re.sub(r"[^a-z0-9]+", " ", title.lower()).split())


class ApplyUrlFinder:
    """Looks up each company's board once per run, then matches titles against it."""

    def __init__(self) -> None:
        self._boards: Dict[str, List[Posting]] = {}

    def find(self, company: str, title: str) -> Optional[str]:
        wanted = normalise_title(title)
        for posting_title, url in self._board_for(company):
            if url and normalise_title(posting_title) == wanted:
                return url
        return None

    def _board_for(self, company: str) -> List[Posting]:
        key = company.strip().lower()
        if key not in self._boards:
            self._boards[key] = self._search(company)
        return self._boards[key]

    @staticmethod
    def _search(company: str) -> List[Posting]:
        for slug in candidate_slugs(company):
            for _name, fetch in BOARDS:
                try:
                    postings = fetch(slug)
                except (FetchError, ValueError, AttributeError, TypeError):
                    continue  # no board under this name, or an unexpected response
                if postings:
                    return postings
        return []
