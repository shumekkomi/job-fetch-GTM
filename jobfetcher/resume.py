"""Score jobs against a resume.

This is the entry point for resume-based matching. The resume is never
hardcoded — you point to a file (plain text or Markdown) via config.yaml
or the --resume CLI flag, and the scorer reads it fresh on every run.

Scoring is keyword-based: we extract meaningful terms from both the resume
and the job description, then ask what share of the JD's terms the resume
covers. The result is a 0-100 score where 100 means every meaningful term in
the JD also appears in the resume. In practice scores land between about 15
and 45, so treat them as a ranking, not a percentage fit.

Why keyword matching and not embeddings: zero dependencies, runs offline,
and for a job search the terms themselves (tools, titles, frameworks)
matter more than semantic similarity.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Set

from .models import Job

# Words too common to be useful signals.
_STOP_WORDS = {
    "a", "an", "the", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "by", "from", "is", "are", "was", "were", "be", "been",
    "being", "have", "has", "had", "do", "does", "did", "will", "would",
    "could", "should", "may", "might", "shall", "can", "need", "must",
    "not", "no", "nor", "so", "if", "then", "than", "too", "very",
    "just", "about", "above", "after", "before", "between", "into",
    "through", "during", "each", "few", "more", "most", "other", "some",
    "such", "only", "own", "same", "that", "this", "these", "those",
    "what", "which", "who", "whom", "how", "all", "both", "any", "here",
    "there", "when", "where", "why", "we", "us", "our", "you", "your",
    "i", "me", "my", "he", "him", "his", "she", "her", "it", "its",
    "they", "them", "their", "also", "as", "up", "out", "over", "well",
    "work", "working", "new", "using",
    "used", "use", "including", "across", "within", "ensure", "based",
    "key", "high", "level", "part", "time", "etc", "per", "via",
    # Resume/CV filler — action verbs, structure words, generic terms.
    "managed", "handling", "handle", "handled", "ran", "run", "running",
    "built", "build", "building", "made", "making", "make", "worked",
    "focused", "looking", "created", "turned", "took", "spent", "gave",
    "wrote", "written", "write", "started", "set", "got", "put",
    "brought", "first", "one", "two", "three", "four", "back", "full",
    "every", "always", "never", "still", "right", "thing", "things",
    "way", "place", "people", "person", "end", "get", "take", "keep",
    "let", "say", "see", "know", "come", "going", "want", "tell",
    "show", "much", "even", "top", "best", "around", "since",
    "long", "next", "last", "real", "live", "done", "enough",
    "actually", "directly", "currently", "alongside", "without", "below",
    "under", "present", "block", "entry", "variant", "fixed", "notes",
    "section", "instructions", "assembly", "pick", "start", "target",
    "matching", "tagged", "compact", "parked", "link", "links", "repo",
    "line", "page", "pages", "site", "input", "fill", "plain",
    "already", "often", "while", "later", "once", "early", "closer",
    "rest", "felt", "tried", "left", "went", "pushed",
    "applied", "applying", "moved", "moving", "turning",
    "helped", "helping", "found", "finding", "learned", "learning",
    "tested", "testing", "tracked", "tracking", "changed", "changing",
    "identified", "reported", "reporting", "delivered", "delivering",
    "prepared", "preparing", "planned", "planning", "coordinated",
    "recommended", "encouraged", "explored", "exploring", "reviewed",
    "diagnosed", "flagged", "resolved",
    "adjusted", "adjusting", "monitored", "monitoring", "achieved",
    "drove", "driving", "growing", "grown", "knew", "knowing",
    "observed", "sitting", "stood",
    # Generic job/resume terms.
    "role", "roles", "team", "teams", "company", "companies", "client",
    "clients", "project", "projects", "position", "positions",
    "industry", "industries", "service", "services", "business",
    "account", "accounts", "management", "manager", "specialist",
    "coordinator", "executive", "consultant", "intern", "senior",
    "junior", "lead", "head", "director", "officer", "associate",
    "experience", "responsible", "responsibility", "responsibilities",
    "able", "ability", "strong", "excellent", "good", "great",
    "various", "multiple", "different", "specific", "relevant",
    "professional", "personal", "internal", "external",
    # Place/time/structure words.
    "year", "years", "month", "months", "week", "weeks", "day", "days",
    "apr", "jun", "jul", "aug", "sep", "oct", "nov", "dec", "jan",
    "feb", "mar", "london", "hong", "kong", "europe",
    # Markdown/document terms.
    "master", "modular", "reference", "document", "lane", "tags",
    "summary", "ordering", "bullets", "tailored", "header",
    "education", "languages", "skills", "trim",
}

# Minimum word length to keep (after lowering). Filters out "ai", "uk", etc.
# unless they're in the explicit keep list below.
_MIN_WORD_LENGTH = 3

# Short terms that ARE meaningful in a job context.
_SHORT_KEEPS = {
    "ai", "ml", "bi", "ci", "cd", "ab", "uk", "eu", "us", "qa", "ux",
    "ui", "js", "ts", "go", "r", "sql", "api", "aws", "gcp", "crm",
    "cro", "gtm", "sem", "seo", "ppc", "kpi", "roi", "b2b", "b2c",
    "saas", "llm", "nlp", "etl", "dbt",
}


def load_resume(path: str) -> str:
    """Read a resume file. Supports .txt and .md (plain text formats).

    Raises FileNotFoundError if the path doesn't exist, ValueError if
    the format isn't supported.
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError("Resume file not found: {}".format(path))

    suffix = p.suffix.lower()
    if suffix in (".txt", ".md", ".markdown", ""):
        return p.read_text(encoding="utf-8")

    raise ValueError(
        "Unsupported resume format '{}'. Use .txt or .md".format(suffix)
    )


def extract_keywords(text: str) -> Set[str]:
    """Pull meaningful terms from resume text.

    Returns a set of lowercased keywords. Multi-word terms (like
    "google analytics") are split into individual words — the scorer
    checks each word independently, which is simpler and avoids
    n-gram complexity.
    """
    # Strip Markdown headings, bullets, and horizontal rules.
    text = re.sub(r"^#{1,6}\s+", " ", text, flags=re.MULTILINE)
    text = re.sub(r"^\s*[-*]\s+", " ", text, flags=re.MULTILINE)
    text = re.sub(r"^---+\s*$", " ", text, flags=re.MULTILINE)
    # Strip bold/italic markers.
    text = re.sub(r"\*{1,2}|\_{1,2}", " ", text)

    # Normalise: lowercase, replace non-alphanumeric with spaces.
    normalised = re.sub(r"[^a-z0-9+#.\-]", " ", text.lower())
    tokens = normalised.split()

    keywords = set()
    for token in tokens:
        # Strip trailing dots/dashes (e.g. "python." -> "python").
        token = token.strip(".-")
        if not token:
            continue
        # Skip pure numbers, dates, phone numbers.
        if re.match(r"^[\d\-+.]+$", token):
            continue
        if token in _STOP_WORDS:
            continue
        if token in _SHORT_KEEPS:
            keywords.add(token)
        elif len(token) >= _MIN_WORD_LENGTH:
            keywords.add(token)

    return keywords


def score_job(job: Job, resume_keywords: Set[str]) -> int:
    """Score a job 0–100 based on how much of the JD you cover.

    The score asks: "what fraction of this JD's meaningful terms appear
    in my resume?" A high score means you already have most of what
    the job asks for.
    """
    if not resume_keywords:
        return 0

    # Extract meaningful terms from the JD the same way we do from the resume.
    jd_text = "{} {}".format(job.title, job.description)
    jd_keywords = extract_keywords(jd_text)

    if not jd_keywords:
        return 0

    covered = jd_keywords & resume_keywords
    return round(len(covered) / len(jd_keywords) * 100)
