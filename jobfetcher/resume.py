"""Score jobs against a resume.

This is the entry point for resume-based matching. The resume is never
hardcoded — you point to a file (plain text or Markdown) via config.yaml
or the --resume CLI flag, and the scorer reads it fresh on every run.

Scoring is keyword-based: we extract meaningful terms from your resume,
then count how many appear in each job description. The result is a
0–100 score where 100 means every resume keyword appeared in the JD.

Why keyword matching and not embeddings: zero dependencies, runs offline,
and for a job search the terms themselves (tools, titles, frameworks)
matter more than semantic similarity.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import List, Optional, Set

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
    "work", "working", "worked", "team", "role", "company", "experience",
    "strong", "ability", "excellent", "good", "great", "new", "using",
    "used", "use", "including", "across", "within", "ensure", "based",
    "key", "high", "level", "part", "time", "year", "years", "day",
    "etc", "per", "via",
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
    # Normalise: lowercase, replace non-alphanumeric with spaces.
    normalised = re.sub(r"[^a-z0-9+#.\-]", " ", text.lower())
    tokens = normalised.split()

    keywords = set()
    for token in tokens:
        # Strip trailing dots/dashes (e.g. "python." -> "python").
        token = token.strip(".-")
        if not token:
            continue
        if token in _STOP_WORDS:
            continue
        if token in _SHORT_KEEPS:
            keywords.add(token)
        elif len(token) >= _MIN_WORD_LENGTH:
            keywords.add(token)

    return keywords


def score_job(job: Job, resume_keywords: Set[str]) -> int:
    """Score a job 0–100 based on keyword overlap with the resume.

    The score is: (keywords found in JD / total resume keywords) * 100.
    A higher score means the JD mentions more of your skills/experience.
    """
    if not resume_keywords:
        return 0

    # Build the JD text to search (title + description).
    jd_text = "{} {}".format(job.title, job.description).lower()
    jd_normalised = re.sub(r"[^a-z0-9+#.\-]", " ", jd_text)
    jd_tokens = set(t.strip(".-") for t in jd_normalised.split())

    matches = resume_keywords & jd_tokens
    return round(len(matches) / len(resume_keywords) * 100)


def score_jobs(jobs: List[Job], resume_path: str) -> List[int]:
    """Score a list of jobs against a resume file. Returns parallel list of scores."""
    text = load_resume(resume_path)
    keywords = extract_keywords(text)
    return [score_job(job, keywords) for job in jobs]
