"""Tests for which scraped LinkedIn links the adapter is willing to fetch."""
import pytest

from jobfetcher.adapters.linkedin import _is_linkedin_url


@pytest.mark.parametrize("url", [
    "https://www.linkedin.com/jobs/view/123",
    "https://uk.linkedin.com/jobs/view/growth-marketing-manager-at-x-123",
    "https://linkedin.com/jobs/view/123",
])
def test_follows_real_linkedin_links(url):
    assert _is_linkedin_url(url)


@pytest.mark.parametrize("url", [
    "",
    "http://www.linkedin.com/jobs/view/123",          # not https
    "https://linkedin.com.evil.example/jobs/view/1",  # lookalike domain
    "https://notlinkedin.com/jobs/view/1",            # suffix without the dot
    "https://evil.example/?next=linkedin.com",        # linkedin only in the query
    "https://169.254.169.254/latest/meta-data/",      # cloud metadata address
    "file:///etc/passwd",
])
def test_refuses_everything_else(url):
    assert not _is_linkedin_url(url)


def test_skip_card_avoids_fetching_detail_pages():
    # Cards the runner already knows it will drop (wrong title, already saved)
    # should not cost a detail-page request.
    from unittest.mock import patch
    from jobfetcher.adapters import linkedin

    cards = [
        {"title": "CRM Executive", "company": "A", "url": "https://uk.linkedin.com/jobs/view/1", "location": "London"},
        {"title": "Account Executive", "company": "B", "url": "https://uk.linkedin.com/jobs/view/2", "location": "London"},
    ]
    with patch.object(linkedin, "_search_page", return_value=cards), \
         patch.object(linkedin, "_fetch_job_detail", return_value=None) as detail, \
         patch.object(linkedin.time, "sleep"):
        result = linkedin.fetch("CRM", "LinkedIn: CRM", skip_card=lambda c: c["title"] == "Account Executive")
    assert detail.call_count == 1
    assert [j.title for j in result.jobs] == ["CRM Executive"]
    assert "1 skipped before detail fetch" in result.note


def test_escaped_description_is_unescaped_with_line_breaks():
    # LinkedIn's JSON-LD sends the description as escaped HTML. Saved as-is,
    # it kept "&lt;br&gt;" in the text and had no line breaks for the
    # description checks to split on.
    from unittest.mock import patch
    from jobfetcher.adapters import linkedin

    card = {"title": "CRM Specialist", "company": "A", "url": "https://uk.linkedin.com/jobs/view/1", "location": "London"}
    detail = {"description": "&lt;strong&gt;About&lt;br&gt;&lt;/strong&gt;Brands like The Press &amp;amp; Journal."
                             "&lt;ul&gt;&lt;li&gt;3+ years of CRM experience&lt;/li&gt;&lt;li&gt;HubSpot&lt;/li&gt;&lt;/ul&gt;"}
    with patch.object(linkedin, "_search_page", return_value=[card]), \
         patch.object(linkedin, "_fetch_job_detail", return_value=detail), \
         patch.object(linkedin.time, "sleep"):
        result = linkedin.fetch("CRM", "LinkedIn: CRM")
    text = result.jobs[0].description
    assert "&lt;" not in text and "<" not in text
    assert "The Press & Journal." in text
    assert "\n- 3+ years of CRM experience\n" in text and "\n- HubSpot" in text
