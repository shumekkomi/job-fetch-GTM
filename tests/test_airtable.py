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
        ("fld" + key if by_id else names[key]): value for key, value in _ROW.items()
    }
    return _FakeResponse({"records": [{"id": "rec1", "fields": fields}]})


class TestFetchExistingJobs:
    def test_reads_existing_records(self, monkeypatch):
        # Regression: when the request and the lookups disagreed on names vs
        # IDs, every lookup missed and each daily run re-inserted every job.
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


class TestWritesAreForkFriendly:
    def test_uses_field_names_and_typecast(self, monkeypatch):
        # Field names (not one base's field IDs) and typecast are what let
        # someone else's base work without editing the code.
        sent = {}

        def fake_post(url, headers=None, json=None, timeout=None):
            sent.update(json)
            return _FakeResponse({"records": [{"id": "rec1"}]})

        monkeypatch.setenv("AIRTABLE_TOKEN", "test-token")
        monkeypatch.setattr(airtable.requests, "post", fake_post)
        monkeypatch.setattr(airtable, "REQUEST_DELAY", 0)

        job = Job(title="GTM Engineer", company="TestCo", url="https://example.com/1")
        airtable.insert_jobs("appTEST", "tblTEST", [job])

        assert sent["typecast"] is True
        fields = sent["records"][0]["fields"]
        assert fields["Original URL"] == "https://example.com/1"
        assert not any(key.startswith("fld") for key in fields)
