"""Tests for when a run stops early and when it reports failure."""
from jobfetcher import runner
from jobfetcher.config import Company, Config
from jobfetcher.runner import exit_code, run


def _config():
    return Config(
        companies=[Company(name="TestCo", ats="greenhouse", slug="testco")],
        title_lanes={"Growth": ["Growth Marketing Manager"]},
    )


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
