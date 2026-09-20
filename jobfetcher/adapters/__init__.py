"""Registry of ATS adapters.

Each adapter turns one ATS's weird JSON shape into a list of our standard Job objects.
This file is the single place you look up which adapter handles which ATS type, so adding
a new ATS means: write the adapter file, then add one line here.
"""
from __future__ import annotations

from typing import Callable, Dict, List

from ..models import CompanyResult, Job

# Each adapter is a function: (slug, company_name) -> CompanyResult
# We import them lazily below and register them in ADAPTERS.
from .greenhouse import fetch as greenhouse_fetch
from .ashby import fetch as ashby_fetch
from .lever import fetch as lever_fetch
from .workable import fetch as workable_fetch
from .smartrecruiters import fetch as smartrecruiters_fetch
from .recruitee import fetch as recruitee_fetch
from .personio import fetch as personio_fetch
from .jsonld import fetch as jsonld_fetch
from .linkedin import fetch as linkedin_fetch

# Maps config "ats" value -> the function that fetches from that ATS.
ADAPTERS: Dict[str, Callable] = {
    "greenhouse": greenhouse_fetch,
    "ashby": ashby_fetch,
    "lever": lever_fetch,
    "workable": workable_fetch,
    "smartrecruiters": smartrecruiters_fetch,
    "recruitee": recruitee_fetch,
    "personio": personio_fetch,
    "jsonld": jsonld_fetch,
    "linkedin": linkedin_fetch,
}
