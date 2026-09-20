"""One place that makes web requests, so timeouts and retries behave the same everywhere."""
from __future__ import annotations

import time
from typing import Any, Dict, Optional

import requests

from .models import FetchError

# Identify ourselves honestly. Some sites block the default "python-requests" agent.
USER_AGENT = "job-fetcher/1.0 (personal job search tool)"
TIMEOUT_SECONDS = 30
MAX_ATTEMPTS = 3


def get(url: str, params: Optional[Dict[str, Any]] = None) -> requests.Response:
    """GET a URL. Retries timeouts and 5xx errors; fails immediately on 4xx.

    A 404 is not retried because it is an answer, not a glitch (usually a wrong slug).
    Anything that still fails after the retries raises FetchError with a readable message.
    """
    last_problem = "unknown error"
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            response = requests.get(
                url, params=params, headers={"User-Agent": USER_AGENT}, timeout=TIMEOUT_SECONDS
            )
        except (requests.Timeout, requests.ConnectionError) as exc:
            last_problem = "{}: {}".format(type(exc).__name__, exc)
        else:
            if response.status_code < 400:
                return response
            if response.status_code < 500:
                raise FetchError("HTTP {} from {}".format(response.status_code, url))
            last_problem = "HTTP {} from {}".format(response.status_code, url)

        if attempt < MAX_ATTEMPTS:
            time.sleep(2 * attempt)  # wait 2s, then 4s, before trying again
    raise FetchError("{} (after {} attempts)".format(last_problem, MAX_ATTEMPTS))


def get_json(url: str, params: Optional[Dict[str, Any]] = None) -> Any:
    """GET a URL and parse the body as JSON. A non-JSON body is a failure, not an empty result."""
    response = get(url, params)
    try:
        return response.json()
    except ValueError:
        raise FetchError("Response from {} was not valid JSON".format(url))
