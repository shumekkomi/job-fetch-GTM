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

    def test_phrase_inside_longer_title(self):
        lanes = {"GTM Engineering": ["GTM Engineer"]}
        job = _make_job(title="Senior GTM Engineer, London")
        assert _match_title(job, lanes) == "GTM Engineering"

    def test_hyphens_read_as_spaces(self):
        lanes = {"GTM Engineering": ["go to market"]}
        assert _match_title(_make_job(title="Go-to-Market Engineer"), lanes) == "GTM Engineering"
        assert _match_title(_make_job(title="Go To Market Engineer"), lanes) == "GTM Engineering"

    def test_whole_words_only(self):
        lanes = {"CRM & Lifecycle": ["crm"]}
        assert _match_title(_make_job(title="Scrum Master"), lanes) is None

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

    def test_exclude_word_drops_and_is_logged(self):
        config = _make_config(title_exclude=["senior"])
        jobs = [_make_job(title="Senior Growth Marketing Manager"), _make_job(title="Growth Marketing Manager")]
        passed, stats = filter_jobs(jobs, _make_company(), config)
        assert [j.title for j in passed] == ["Growth Marketing Manager"]
        assert stats.dropped_title_exclude == ["Senior Growth Marketing Manager (senior)"]
        assert "dropped by title: Senior Growth Marketing Manager (senior)" in stats.summary()

    def test_description_check_drops_and_flags(self):
        from jobfetcher.fit import DescriptionChecks
        checks = DescriptionChecks(max_years=5, tool_flags={"HubSpot": ["hubspot"]})
        config = _make_config(description_checks=checks)
        jobs = [
            _make_job(title="Growth Marketing Manager", url="u1",
                      description="You have 6+ years of experience in growth."),
            _make_job(title="Growth Marketing Manager", url="u2",
                      description="2 to 5 years of experience. You use HubSpot daily."),
        ]
        passed, stats = filter_jobs(jobs, _make_company(), config)
        assert [j.url for j in passed] == ["u2"]
        assert passed[0].notes == "tools: HubSpot (1)"
        assert stats.after_title == 2 and stats.after_description == 1
        assert stats.dropped_description == ["Growth Marketing Manager (6+ years)"]

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
    """Check the lanes and excludes in config.yaml itself, so an edit there can't
    quietly stop matching the titles the search is aimed at. The titles are
    real ones from roles applied to, shortlisted or skipped (Sep to Nov 2026)."""

    def _cfg(self):
        from jobfetcher.config import load_config
        return load_config("config.yaml")

    def _lane(self, title):
        return _match_title(_make_job(title=title), self._cfg().title_lanes)

    def _passes(self, title):
        from jobfetcher.fit import title_passes
        cfg = self._cfg()
        return title_passes(title, cfg.title_lanes, cfg.title_exclude)

    def test_lanes(self):
        expected = {
            "GTM Engineer": "GTM Engineering",
            "Go To Market Engineer": "GTM Engineering",
            "Go-to-Market Engineer": "GTM Engineering",
            "Go to Market Systems Admin (HubSpot)": "GTM Engineering",
            "Growth Marketing Manager (GTM Engineer)": "GTM Engineering",
            "Marketing AI Engineer": "GTM Engineering",
            "AI Growth Ops": "GTM Engineering",
            "Revenue Operations Associate": "RevOps & Systems",
            "RevOps Analyst": "RevOps & Systems",
            "Sales Operations Analyst": "RevOps & Systems",
            "HubSpot Administrator": "RevOps & Systems",
            "Salesforce Administrator - 12 Month FTC": "RevOps & Systems",
            "Junior CRM Developer (FTC)": "RevOps & Systems",
            "Martech Specialist, AI Deployment": "RevOps & Systems",
            "Marketing Ops & Automation Specialist": "RevOps & Systems",
            "Marketing Automation Manager": "RevOps & Systems",
            "CRM Executive": "CRM & Lifecycle",
            "CRM (Braze) Specialist (Part-Time) - Remote": "CRM & Lifecycle",
            "CRM Campaign Specialist - 9 Month FTC": "CRM & Lifecycle",
            "Lifecycle Marketing Manager - London": "CRM & Lifecycle",
            "Retention Marketing Executive": "CRM & Lifecycle",
            "Loyalty Executive | LOOKFANTASTIC": "CRM & Lifecycle",
            "Customer Marketing Executive": "CRM & Lifecycle",
            "Email Marketing Executive": "CRM & Lifecycle",
            "Growth Marketing Executive, SME (REF1828M)": "Growth",
            "Growth Marketer": "Growth",
            "Growth Manager": "Growth",
        }
        for title, lane in expected.items():
            assert self._lane(title) == lane, title

    def test_excluded_titles(self):
        for title in [
            "Senior CRM Executive", "Sr CRM Marketing Specialist", "Head of CRM",
            "Regional CRM Manager", "Performance Marketing Manager, Paid Search",
            "Growth Performance Marketing Manager", "Paid Media Manager",
            "Principal Technical Marketing Engineer",
        ]:
            assert not self._passes(title), title

    def test_unrelated_titles_do_not_match(self):
        for title in ["Account Executive", "Customer Success Manager",
                      "Digital Marketing Manager", "Forward Deployed Engineer",
                      "Conversion Rate Optimisation (CRO) Specialist"]:
            assert self._lane(title) is None, title

    def test_crm_is_a_whole_word(self):
        assert self._lane("Scrum Master") is None


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
