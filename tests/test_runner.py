"""Tests for when a run stops early and when it reports failure."""
from jobfetcher import runner
from jobfetcher.config import Company, Config
from jobfetcher.runner import exit_code, run


def _config(**airtable_ids):
    ids = {
        "airtable_base_id": "appTEST",
        "airtable_jobs_table_id": "tblJOBS",
        "airtable_runlog_table_id": "tblLOG",
    }
    ids.update(airtable_ids)
    return Config(
        companies=[Company(name="TestCo", ats="greenhouse", slug="testco")],
        title_lanes={"Growth": ["Growth Marketing Manager"]},
        **ids,
    )


def _block_airtable(monkeypatch):
    def must_not_call(*args, **kwargs):
        raise AssertionError("Airtable should not be called")

    for name in ("fetch_existing_jobs", "insert_jobs", "insert_run_log"):
        monkeypatch.setattr(runner, name, must_not_call)


class TestRunStopsWithoutAirtableIds:
    def test_missing_base_id_stops_before_any_request(self, monkeypatch):
        _block_airtable(monkeypatch)
        summary = run(_config(airtable_base_id=""))
        assert summary["aborted"] is True
        assert exit_code(summary) == 1

    def test_dry_run_does_not_need_ids(self, monkeypatch):
        _block_airtable(monkeypatch)
        monkeypatch.setattr(runner, "ADAPTERS", {})  # no network: company fails as unknown ATS
        summary = run(_config(airtable_base_id=""), dry_run=True)
        assert summary["aborted"] is False


class TestRunStopsWhenAirtableUnreadable:
    def test_writes_nothing_and_fails(self, monkeypatch):
        # Regression: a bad token used to log an error and carry on, so the
        # run wrote nothing (or duplicates) and still showed green.
        def broken_read(*args, **kwargs):
            raise RuntimeError("403 Forbidden")

        def must_not_write(*args, **kwargs):
            raise AssertionError("nothing should be written after a failed read")

        monkeypatch.setattr(runner, "fetch_existing_jobs", broken_read)
        monkeypatch.setattr(runner, "insert_jobs", must_not_write)
        monkeypatch.setattr(runner, "insert_run_log", must_not_write)

        summary = run(_config())

        assert summary["aborted"] is True
        assert exit_code(summary) == 1


class TestExitCode:
    def _summary(self, outcomes, airtable_errors=0):
        return {
            "aborted": False,
            "airtable_errors": airtable_errors,
            "results": [{"outcome": o} for o in outcomes],
        }

    def test_normal_run_passes(self):
        assert exit_code(self._summary(["OK", "Empty", "Skipped"])) == 0

    def test_skipped_sources_do_not_hide_a_total_outage(self):
        assert exit_code(self._summary(["Failed", "Failed", "Skipped"])) == 1

    def test_one_failed_source_is_not_a_failed_run(self):
        assert exit_code(self._summary(["OK", "Failed"])) == 0

    def test_any_airtable_error_fails_the_run(self):
        assert exit_code(self._summary(["OK"], airtable_errors=1)) == 1


def test_linkedin_skip_card_drops_unmatched_titles_and_saved_jobs():
    from jobfetcher.config import Config
    from jobfetcher.runner import _linkedin_skip_card
    cfg = Config(companies=[], title_lanes={"CRM & Lifecycle": ["CRM Executive"]})
    skip = _linkedin_skip_card(cfg, {"https://uk.linkedin.com/jobs/view/9"}, {"acme|crm executive"})
    assert skip({"title": "Account Executive", "url": "https://uk.linkedin.com/jobs/view/1", "company": "X"})
    assert skip({"title": "CRM Executive", "url": "https://uk.linkedin.com/jobs/view/9?trk=abc", "company": "X"})
    assert skip({"title": "CRM Executive", "url": "https://uk.linkedin.com/jobs/view/2", "company": "Acme"})
    assert not skip({"title": "Senior CRM Executive", "url": "https://uk.linkedin.com/jobs/view/3", "company": "New Co"})


def test_linkedin_skip_card_drops_excluded_titles():
    # An excluded title (e.g. Senior) would be dropped by the filter anyway,
    # so its detail page isn't fetched.
    from jobfetcher.runner import _linkedin_skip_card
    cfg = Config(companies=[], title_lanes={"CRM & Lifecycle": ["crm"]}, title_exclude=["senior"])
    skip = _linkedin_skip_card(cfg, set(), set())
    assert skip({"title": "Senior CRM Executive", "company": "Acme", "url": "u1"}) is True
    assert skip({"title": "CRM Executive", "company": "Acme", "url": "u2"}) is False


def test_linkedin_searches_run_once_per_window_narrowest_first():
    from jobfetcher.config import Company, LinkedInWindow
    from jobfetcher.runner import _expand_linkedin
    cfg = Config(companies=[], title_lanes={"CRM & Lifecycle": ["crm"]},
                 linkedin_windows=[LinkedInWindow("24h", 24), LinkedInWindow("3 days", 72)])
    companies = [Company(name="Braze", ats="greenhouse", slug="braze"),
                 Company(name="LinkedIn: CRM Executive", ats="linkedin", slug="CRM Executive")]
    out = _expand_linkedin(companies, cfg)
    assert [(c.name, c.posted_within) for c in out] == [
        ("Braze", None),
        ("LinkedIn: CRM Executive (24h)", 86400),
        ("LinkedIn: CRM Executive (3 days)", 259200),
    ]
    assert all(c.slug == "CRM Executive" for c in out[1:])


def test_no_windows_keeps_one_search():
    from jobfetcher.config import Company
    from jobfetcher.runner import _expand_linkedin
    cfg = Config(companies=[], title_lanes={"CRM & Lifecycle": ["crm"]})
    companies = [Company(name="LinkedIn: CRM Executive", ats="linkedin", slug="CRM Executive")]
    assert _expand_linkedin(companies, cfg) == companies


def test_windowed_search_passes_window_to_adapter(monkeypatch):
    from jobfetcher import runner
    from jobfetcher.config import Company
    from jobfetcher.models import CompanyResult
    seen = {}

    def fake_linkedin(slug, name, skip_card=None, posted_within=None):
        seen["posted_within"] = posted_within
        return CompanyResult(company=name, ats="linkedin", outcome="Empty", note="none")

    monkeypatch.setattr(runner, "ADAPTERS", {"linkedin": fake_linkedin})
    monkeypatch.setattr(runner, "_log_run", lambda *a, **k: None)
    cfg = Config(companies=[], title_lanes={"CRM & Lifecycle": ["crm"]})
    company = Company(name="LinkedIn: CRM (24h)", ats="linkedin", slug="CRM", posted_within=86400)
    runner._process_company(company, cfg, set(), set(), dry_run=True)
    assert seen["posted_within"] == 86400


def test_catch_up_flag_drops_linkedin_windows(monkeypatch, tmp_path):
    import run as entry
    path = tmp_path / "config.yaml"
    path.write_text(
        "companies:\n  - name: TestCo\n    ats: greenhouse\n    slug: testco\n"
        "title_lanes:\n  Growth: [Growth Marketing Manager]\n"
        "linkedin_windows:\n  - {label: 24h, hours: 24}\n")
    seen = {}

    def fake_run(config, dry_run=False, resume_path=None):
        seen["windows"] = config.linkedin_windows
        seen["dry_run"] = dry_run
        return {}

    monkeypatch.setattr(entry, "run", fake_run)
    monkeypatch.setattr(entry, "exit_code", lambda summary: 0)
    for argv, expected in ((["--catch-up"], []), ([], ["24h"])):
        monkeypatch.setattr("sys.argv", ["run.py", "--dry-run", "--config", str(path)] + argv)
        try:
            entry.main()
        except SystemExit:
            pass
        assert [w.label for w in seen["windows"]] == expected
        assert seen["dry_run"] is True
