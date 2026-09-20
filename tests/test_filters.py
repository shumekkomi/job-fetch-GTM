"""Tests for location, title, and salary filters."""
import pytest

from jobfetcher.config import Company, Config
from jobfetcher.filters import filter_jobs, _matches_location, _match_title, _below_salary_floor
from jobfetcher.models import Job


def _make_config(**overrides):
    defaults = {
        "companies": [],
        "title_lanes": {
            "Growth": ["Growth Marketing Manager"],
            "Performance": ["Performance Marketing Manager"],
            "GTM Engineering": ["GTM Engineer", "Growth Engineer"],
        },
        "default_location": "London",
        "salary_floor_gbp": 35000,
    }
    defaults.update(overrides)
    return Config(**defaults)


def _make_company(**overrides):
    defaults = {
        "name": "TestCo",
        "ats": "greenhouse",
        "slug": "testco",
    }
    defaults.update(overrides)
    return Company(**defaults)


def _make_job(**overrides):
    defaults = {
        "title": "Growth Marketing Manager",
        "company": "TestCo",
        "url": "https://example.com/job/1",
        "location": "London",
    }
    defaults.update(overrides)
    return Job(**defaults)


# ---- Location ----

class TestLocationFilter:
    def test_london_matches(self):
        config = _make_config()
        company = _make_company()
        job = _make_job(location="London")
        assert _matches_location(job, company, config) is True

    def test_london_case_insensitive(self):
        config = _make_config()
        company = _make_company()
        job = _make_job(location="london, United Kingdom")
        assert _matches_location(job, company, config) is True

    def test_non_london_does_not_match(self):
        config = _make_config()
        company = _make_company()
        job = _make_job(location="New York")
        assert _matches_location(job, company, config) is False

    def test_location_alias_matches(self):
        config = _make_config()
        company = _make_company(location_aliases=["United Kingdom"])
        job = _make_job(location="United Kingdom")
        assert _matches_location(job, company, config) is True

    def test_location_alias_case_insensitive(self):
        config = _make_config()
        company = _make_company(location_aliases=["united kingdom"])
        job = _make_job(location="United Kingdom")
        assert _matches_location(job, company, config) is True


# ---- Title ----

class TestTitleFilter:
    def test_exact_match(self):
        lanes = {"Growth": ["Growth Marketing Manager"]}
        job = _make_job(title="Growth Marketing Manager")
        assert _match_title(job, lanes) == "Growth"

    def test_substring_match(self):
        lanes = {"GTM Engineering": ["GTM Engineer"]}
        job = _make_job(title="Senior GTM Engineer, London")
        assert _match_title(job, lanes) == "GTM Engineering"

    def test_case_insensitive(self):
        lanes = {"Performance": ["Performance Marketing Manager"]}
        job = _make_job(title="PERFORMANCE MARKETING MANAGER")
        assert _match_title(job, lanes) == "Performance"

    def test_no_match(self):
        lanes = {"Growth": ["Growth Marketing Manager"]}
        job = _make_job(title="Software Engineer")
        assert _match_title(job, lanes) is None

    def test_first_lane_wins(self):
        # "Growth Engineer" appears in GTM Engineering lane.
        lanes = {
            "Growth": ["Growth Marketing Manager"],
            "GTM Engineering": ["Growth Engineer"],
        }
        job = _make_job(title="Growth Engineer")
        assert _match_title(job, lanes) == "GTM Engineering"


# ---- Salary ----

class TestSalaryFloor:
    def test_no_salary_keeps_job(self):
        job = _make_job()
        assert _below_salary_floor(job, 35000) is False

    def test_gbp_above_floor_keeps_job(self):
        job = _make_job(salary_max=50000, salary_currency="GBP")
        assert _below_salary_floor(job, 35000) is False

    def test_gbp_at_floor_keeps_job(self):
        job = _make_job(salary_max=35000, salary_currency="GBP")
        assert _below_salary_floor(job, 35000) is False

    def test_gbp_below_floor_drops_job(self):
        job = _make_job(salary_max=30000, salary_currency="GBP")
        assert _below_salary_floor(job, 35000) is True

    def test_non_gbp_keeps_job(self):
        # USD salary below the GBP floor should still be kept.
        job = _make_job(salary_max=25000, salary_currency="USD")
        assert _below_salary_floor(job, 35000) is False

    def test_unknown_currency_keeps_job(self):
        job = _make_job(salary_max=20000, salary_currency=None)
        assert _below_salary_floor(job, 35000) is False


# ---- Full pipeline ----

class TestFilterPipeline:
    def test_full_pipeline(self):
        config = _make_config()
        company = _make_company()
        jobs = [
            _make_job(title="Growth Marketing Manager", location="London"),
            _make_job(title="Software Engineer", location="London"),
            _make_job(title="Growth Marketing Manager", location="New York"),
        ]
        passed, stats = filter_jobs(jobs, company, config)
        assert len(passed) == 1
        assert passed[0].title == "Growth Marketing Manager"
        assert passed[0].lane == "Growth"
        assert stats.total == 3
        assert stats.after_location == 2
        assert stats.after_title == 1

    def test_salary_floor_drops_low_salary(self):
        config = _make_config()
        company = _make_company()
        jobs = [
            _make_job(
                title="Growth Marketing Manager", location="London",
                salary_max=25000, salary_currency="GBP"
            ),
        ]
        passed, stats = filter_jobs(jobs, company, config)
        assert len(passed) == 0
        assert stats.dropped_salary == ["Growth Marketing Manager"]

    def test_remote_with_keep_unqualified(self):
        config = _make_config()
        company = _make_company(keep_unqualified_remote=True)
        jobs = [
            _make_job(title="GTM Engineer", location="Remote"),
            _make_job(title="GTM Engineer", location="Remote - US only"),
        ]
        passed, stats = filter_jobs(jobs, company, config)
        # "Remote" should be kept, "Remote - US only" should be dropped.
        assert len(passed) == 1
        assert "UK eligibility unconfirmed" in passed[0].location
