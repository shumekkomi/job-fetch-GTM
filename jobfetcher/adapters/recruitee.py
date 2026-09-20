"""Recruitee adapter -- currently non-functional.

Recruitee's public API (GET https://{slug}.recruitee.com/api/offers) was tested on
20 Sep 2026 and returns 404 for every slug tried (hotjar, pleo, wolt, factorial, padel).
They may have moved to a different URL structure or restricted the API.

Like the Workable adapter, this exists so that "recruitee" is a valid config type and
gives a clear skip message rather than a confusing error.
"""
from __future__ import annotations

from ..models import CompanyResult


def fetch(slug: str, company: str) -> CompanyResult:
    return CompanyResult(
        company=company, ats="recruitee", outcome="Skipped",
        note=(
            "Recruitee's public API returns 404 as of Sep 2026. "
            "They may have changed their URL structure or restricted access. "
            "Skipping until the endpoint is confirmed."
        ),
    )
