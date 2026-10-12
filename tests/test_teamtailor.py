"""Tests for the Teamtailor RSS adapter."""
import os
from unittest.mock import MagicMock, patch

from jobfetcher.adapters.teamtailor import fetch, feed_url

SAMPLE = os.path.join(os.path.dirname(__file__), "samples", "teamtailor.rss")


def _mock_get(text):
    response = MagicMock()
    response.text = text
    response.content = text.encode("utf-8")
    return patch("jobfetcher.adapters.teamtailor.get", return_value=response)


def _sample():
    with open(SAMPLE, encoding="utf-8") as f:
        return f.read()


def test_feed_url_from_subdomain_slug():
    assert feed_url("chip") == "https://chip.teamtailor.com/jobs.rss"


def test_feed_url_from_custom_careers_domain():
    assert feed_url("https://careers.example.com") == "https://careers.example.com/jobs.rss"
    assert feed_url("https://careers.example.com/") == "https://careers.example.com/jobs.rss"


def test_parses_jobs():
    with _mock_get(_sample()):
        result = fetch("chip", "Chip")
    assert result.outcome == "OK"
    assert len(result.jobs) == 2
    job = result.jobs[0]
    assert job.title == "CRM Strategist"
    assert job.url == "https://chip.teamtailor.com/jobs/8523124-crm-strategist"
    assert job.location == "Shoreditch, London, United Kingdom"
    assert "CRM Strategist" in job.description and "<" not in job.description
    assert job.posted_date == "2026-10-09"


def test_fully_remote_is_flagged_for_the_remote_filter():
    with _mock_get(_sample()):
        result = fetch("chip", "Chip")
    job = result.jobs[1]
    assert job.location == "Remote"
    assert job.raw.get("workplaceType") == "Remote"


def test_empty_feed_is_empty_not_ok():
    empty = '<?xml version="1.0"?><rss version="2.0"><channel><title>X</title></channel></rss>'
    with _mock_get(empty):
        result = fetch("x", "X")
    assert result.outcome == "Empty"


def test_non_xml_is_a_failure():
    with _mock_get("<html>not a feed</html"):
        result = fetch("x", "X")
    assert result.outcome == "Failed"
