"""Tests for the dedup logic."""
from jobfetcher.dedup import dedup
from jobfetcher.models import Job


def _make_job(**overrides):
    defaults = {
        "title": "Growth Marketing Manager",
        "company": "TestCo",
        "url": "https://example.com/job/1",
        "location": "London",
    }
    defaults.update(overrides)
    return Job(**defaults)


class TestDedup:
    def test_new_job_passes(self):
        jobs = [_make_job()]
        result = dedup(jobs, existing_urls=set(), existing_company_titles=set())
        assert len(result.new_jobs) == 1

    def test_url_match_skips(self):
        jobs = [_make_job(url="https://example.com/job/1")]
        result = dedup(
            jobs,
            existing_urls={"https://example.com/job/1"},
            existing_company_titles=set(),
        )
        assert len(result.new_jobs) == 0
        assert len(result.skipped_url) == 1

    def test_url_match_case_insensitive(self):
        jobs = [_make_job(url="https://Example.com/Job/1")]
        result = dedup(
            jobs,
            existing_urls={"https://example.com/job/1"},
            existing_company_titles=set(),
        )
        assert len(result.new_jobs) == 0

    def test_title_repost_skips(self):
        jobs = [_make_job(url="https://example.com/job/NEW")]
        result = dedup(
            jobs,
            existing_urls=set(),
            existing_company_titles={"testco|growth marketing manager"},
        )
        assert len(result.new_jobs) == 0
        assert len(result.skipped_title) == 1

    def test_different_job_passes(self):
        jobs = [_make_job(title="Different Role", url="https://example.com/job/2")]
        result = dedup(
            jobs,
            existing_urls={"https://example.com/job/1"},
            existing_company_titles={"testco|growth marketing manager"},
        )
        assert len(result.new_jobs) == 1

    def test_same_run_dedup(self):
        """Two jobs with the same URL in the same batch: only one passes."""
        jobs = [
            _make_job(url="https://example.com/job/1"),
            _make_job(url="https://example.com/job/1"),
        ]
        result = dedup(jobs, existing_urls=set(), existing_company_titles=set())
        assert len(result.new_jobs) == 1
        assert len(result.skipped_url) == 1
