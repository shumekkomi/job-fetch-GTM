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
