"""Workable adapter -- currently non-functional.

Workable's public widget API (GET /api/v1/widget/accounts/{slug}) was tested on
20 Sep 2026 and returns empty jobs arrays for every company, even known active boards
(Typeform, Zapier, Front, Intercom). Their v3 API requires authentication.

This adapter exists so that "workable" is a valid ATS type in the config. Any company
configured with ats: workable will get a clear "Skipped" result explaining why, rather
than a confusing error.

When Workable's public API starts working again (or if we get API keys), the fetch
function below just needs to be filled in.
"""
from __future__ import annotations

from ..models import CompanyResult


def fetch(slug: str, company: str) -> CompanyResult:
    return CompanyResult(
        company=company, ats="workable", outcome="Skipped",
        note=(
            "Workable's public widget API returns empty results as of Sep 2026. "
            "Their v3 API requires authentication. Skipping until we have API keys "
            "or the public endpoint is restored."
        ),
    )
