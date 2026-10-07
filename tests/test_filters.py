"""Tests for location, title, and salary filters."""

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


class TestRealTitleLanes:
    """Check the lanes in config.yaml itself, so an edit there can't quietly
    stop matching the titles the search is actually aimed at."""

    def _lane(self, title):
        from jobfetcher.config import load_config
        cfg = load_config("config.yaml")
        return _match_title(_make_job(title=title), cfg.title_lanes)

    def test_crm_and_lifecycle_titles(self):
        for title in [
            "CRM Executive", "Senior CRM Specialist", "Technical CRM Specialist",
            "Lifecycle Marketing Executive", "Retention Marketing Executive",
            "Email Marketing Specialist", "Marketing Automation Executive",
            "Loyalty Executive", "Growth Marketing Specialist",
            "Senior Digital Marketing Executive", "Marketing Operations Specialist",
        ]:
            assert self._lane(title) == "CRM & Lifecycle", title

    def test_revops_titles(self):
        for title in ["Revenue Operations Associate", "RevOps Associate",
                      "Revenue Operations Specialist"]:
            assert self._lane(title) == "RevOps", title

    def test_existing_lanes_unchanged(self):
        assert self._lane("Performance Marketing Manager") == "Performance"
        assert self._lane("GTM Engineer") == "GTM Engineering"
        assert self._lane("Growth Marketing Manager") == "Growth"

    def test_unrelated_titles_do_not_match(self):
        for title in ["Account Executive", "Customer Success Manager",
                      "Revenue Operations Analyst"]:
            assert self._lane(title) is None, title


class TestIncludeRemote:
    """include_remote keeps remote roles from any region, labelled so the
    ones listed for another region can be checked or filtered out."""

    def _run(self, job, include_remote=True, company=None):
        config = _make_config(include_remote=include_remote)
        passed, _ = filter_jobs([job], company or _make_company(), config)
        return passed

    def test_remote_flag_in_raw_data_counts(self):
        # Zapier's Ashby posts say "NAMER" with isRemote true, never "remote".
        job = _make_job(location="NAMER", raw={"isRemote": True})
        passed = self._run(job)
        assert len(passed) == 1
        assert passed[0].location == "NAMER (Remote, listed for another region: check UK eligibility)"

    def test_workplace_type_remote_counts(self):
        job = _make_job(location="Toronto", raw={"workplaceType": "Remote"})
        assert len(self._run(job)) == 1

    def test_linkedin_telecommute_counts(self):
        job = _make_job(location="Anywhere", raw={"jobLocationType": "TELECOMMUTE"})
        passed = self._run(job)
        assert passed[0].location == "Anywhere (Remote, UK eligibility unconfirmed)"

    def test_plain_remote_is_unconfirmed(self):
        passed = self._run(_make_job(location="Remote"))
        assert passed[0].location == "Remote (Remote, UK eligibility unconfirmed)"

    def test_us_remote_is_labelled_another_region(self):
        passed = self._run(_make_job(location="Remote - United States"))
        assert "listed for another region" in passed[0].location

    def test_region_words_need_whole_word_match(self):
        # "us" inside another word must not count as the US.
        passed = self._run(_make_job(location="Remote, Belarus"))
        assert "UK eligibility unconfirmed" in passed[0].location

    def test_off_by_default(self):
        assert self._run(_make_job(location="Remote"), include_remote=False) == []

    def test_office_role_elsewhere_still_dropped(self):
        assert self._run(_make_job(location="New York")) == []

    def test_uk_match_is_not_relabelled(self):
        passed = self._run(_make_job(location="London (Remote)"))
        assert passed[0].location == "London (Remote)"
