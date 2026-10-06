"""Tests for reading from and writing to Airtable, with the network faked out."""
from jobfetcher import airtable
from jobfetcher.airtable import JOB_FIELDS, _job_to_record, fetch_existing_jobs
from jobfetcher.models import Job

_ROW = {
    "original_url": "https://Example.com/job/1",
    "company": "TestCo",
    "title": "GTM Engineer",
}


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


def _fake_airtable_get(url, headers=None, params=None, timeout=None):
    """Behave like Airtable: fields come back keyed by name unless asked for IDs."""
    names = {"original_url": "Original URL", "company": "Company", "title": "Title"}
    by_id = (params or {}).get("returnFieldsByFieldId") == "true"
    fields = {
        (JOB_FIELDS[key] if by_id else names[key]): value for key, value in _ROW.items()
    }
    return _FakeResponse({"records": [{"id": "rec1", "fields": fields}]})


class TestFetchExistingJobs:
    def test_reads_existing_records(self, monkeypatch):
        # Regression: without returnFieldsByFieldId, every lookup missed and
        # each daily run re-inserted every job it had already saved.
        monkeypatch.setenv("AIRTABLE_TOKEN", "test-token")
        monkeypatch.setattr(airtable.requests, "get", _fake_airtable_get)

        urls, company_titles = fetch_existing_jobs("appTEST", "tblTEST")

        assert urls == {"https://example.com/job/1"}
        assert company_titles == {"testco|gtm engineer"}


class TestJobToRecord:
    def _job(self):
        return Job(title="GTM Engineer", company="TestCo", url="https://example.com/1")

    def test_source_defaults_to_direct(self):
        fields = _job_to_record(self._job())["fields"]
        assert fields[JOB_FIELDS["source"]] == "Direct"

    def test_source_can_be_linkedin(self):
        fields = _job_to_record(self._job(), source="LinkedIn")["fields"]
        assert fields[JOB_FIELDS["source"]] == "LinkedIn"
