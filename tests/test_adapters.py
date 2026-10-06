"""Tests for the ATS adapters, using saved sample responses.

These tests don't hit the real APIs. Instead, they patch the HTTP layer to return
our saved JSON files, so the tests are fast and don't depend on the internet.
"""
import json
import os
from unittest.mock import patch


SAMPLES_DIR = os.path.join(os.path.dirname(__file__), "samples")


def _load_sample(filename: str):
    with open(os.path.join(SAMPLES_DIR, filename)) as f:
        return json.load(f)


def _mock_adapter_json(adapter_module: str, data):
    """Patch get_json at the adapter module level so the adapter sees the mock."""
    return patch("{}.get_json".format(adapter_module), return_value=data)


# ---- Greenhouse ----

class TestGreenhouse:
    MODULE = "jobfetcher.adapters.greenhouse"

    def test_parses_jobs(self):
        from jobfetcher.adapters.greenhouse import fetch
        data = _load_sample("greenhouse.json")
        with _mock_adapter_json(self.MODULE, data):
            result = fetch("testco", "TestCo")
        assert result.outcome == "OK"
        assert len(result.jobs) == 3

    def test_extracts_fields(self):
        from jobfetcher.adapters.greenhouse import fetch
        data = _load_sample("greenhouse.json")
        with _mock_adapter_json(self.MODULE, data):
            result = fetch("testco", "TestCo")
        job = result.jobs[0]
        assert job.title == "Growth Marketing Manager"
        assert job.company == "TestCo"
        assert job.location == "London"
        assert job.url == "https://boards.greenhouse.io/testco/jobs/1001"
        assert job.posted_date == "2026-09-01"
        assert "Growth Marketing Manager" in job.description

    def test_strips_html(self):
        from jobfetcher.adapters.greenhouse import fetch
        data = _load_sample("greenhouse.json")
        with _mock_adapter_json(self.MODULE, data):
            result = fetch("testco", "TestCo")
        # Description should be plain text, no <p> tags.
        assert "<p>" not in result.jobs[0].description

    def test_empty_board_returns_empty_outcome(self):
        from jobfetcher.adapters.greenhouse import fetch
        data = _load_sample("empty_greenhouse.json")
        with _mock_adapter_json(self.MODULE, data):
            result = fetch("testco", "TestCo")
        assert result.outcome == "Empty"
        assert len(result.jobs) == 0

    def test_404_returns_failed(self):
        from jobfetcher.adapters.greenhouse import fetch
        from jobfetcher.models import FetchError
        with patch("{}.get_json".format(self.MODULE), side_effect=FetchError("HTTP 404")):
            result = fetch("badslug", "TestCo")
        assert result.outcome == "Failed"
        assert "404" in result.error


# ---- Ashby ----

class TestAshby:
    MODULE = "jobfetcher.adapters.ashby"

    def test_parses_jobs(self):
        from jobfetcher.adapters.ashby import fetch
        data = _load_sample("ashby.json")
        with _mock_adapter_json(self.MODULE, data):
            result = fetch("testco", "TestCo")
        assert result.outcome == "OK"
        assert len(result.jobs) == 2

    def test_extracts_compensation(self):
        from jobfetcher.adapters.ashby import fetch
        data = _load_sample("ashby.json")
        with _mock_adapter_json(self.MODULE, data):
            result = fetch("testco", "TestCo")
        job = result.jobs[0]
        assert job.salary_min == 50000
        assert job.salary_max == 70000
        assert job.salary_currency == "GBP"
        assert job.salary_text == "GBP 50,000 - 70,000"

    def test_no_compensation_is_none(self):
        from jobfetcher.adapters.ashby import fetch
        data = _load_sample("ashby.json")
        with _mock_adapter_json(self.MODULE, data):
            result = fetch("testco", "TestCo")
        job = result.jobs[1]  # Berlin job with no compensation
        assert job.salary_text is None
        assert job.salary_min is None


# ---- Lever ----

class TestLever:
    MODULE = "jobfetcher.adapters.lever"

    def test_parses_jobs(self):
        from jobfetcher.adapters.lever import fetch
        data = _load_sample("lever.json")
        with _mock_adapter_json(self.MODULE, data):
            result = fetch("testco", "TestCo")
        assert result.outcome == "OK"
        assert len(result.jobs) == 2

    def test_extracts_salary_range(self):
        from jobfetcher.adapters.lever import fetch
        data = _load_sample("lever.json")
        with _mock_adapter_json(self.MODULE, data):
            result = fetch("testco", "TestCo")
        job = result.jobs[0]
        assert job.salary_min == 55000
        assert job.salary_max == 75000
        assert job.salary_currency == "GBP"

    def test_builds_description_from_parts(self):
        from jobfetcher.adapters.lever import fetch
        data = _load_sample("lever.json")
        with _mock_adapter_json(self.MODULE, data):
            result = fetch("testco", "TestCo")
        desc = result.jobs[0].description
        assert "About the role" in desc
        assert "3+ years experience" in desc
        assert "health insurance" in desc

    def test_location_from_categories(self):
        from jobfetcher.adapters.lever import fetch
        data = _load_sample("lever.json")
        with _mock_adapter_json(self.MODULE, data):
            result = fetch("testco", "TestCo")
        assert result.jobs[0].location == "London, United Kingdom"

    def test_404_returns_failed(self):
        from jobfetcher.adapters.lever import fetch
        from jobfetcher.models import FetchError
        with patch("{}.get_json".format(self.MODULE), side_effect=FetchError("HTTP 404")):
            result = fetch("badslug", "TestCo")
        assert result.outcome == "Failed"
