"""Tests for the Workable search probe, with the network faked out."""
import probe_workable as probe
from jobfetcher.models import FetchError

LANES = {"CRM & Lifecycle": ["crm"], "RevOps & Systems": ["revenue operations"]}
EXCLUDE = ["senior"]


def _item(title, company="Acme", created="2026-11-10T09:00:00Z", **extra):
    item = {"title": title, "company": {"title": company, "website": "acme.com"},
            "location": {"city": "London", "country": "United Kingdom"},
            "created": created, "url": "https://jobs.workable.com/view/abc", "description": "<p>x</p>"}
    item.update(extra)
    return item


def test_parse_job_reads_nested_fields():
    job = probe.parse_job(_item("CRM Executive"))
    assert job == {"title": "CRM Executive", "company": "Acme", "location": "London, United Kingdom",
                   "created": "2026-11-10T09:00:00Z", "url": "https://jobs.workable.com/view/abc",
                   "has_description": "yes"}


def test_find_jobs_handles_shapes():
    assert probe.find_jobs({"jobs": [_item("A")], "nextPageToken": "t"})[1] == "t"
    assert len(probe.find_jobs({"results": [_item("A"), _item("B")]})[0]) == 2
    assert probe.find_jobs("not json") == ([], None)


def test_probe_api_follows_pages_and_applies_title_rules(monkeypatch):
    pages = [
        {"jobs": [_item("CRM Executive"), _item("Senior CRM Manager")], "nextPageToken": "p2"},
        {"jobs": [_item("Account Executive")]},
    ]
    calls = []

    def fake_get_json(url, params=None):
        calls.append(dict(params))
        return pages[len(calls) - 1]

    monkeypatch.setattr(probe.http, "get_json", fake_get_json)
    monkeypatch.setattr(probe, "PAUSE_SECONDS", 0)
    out = probe.probe_api("CRM", "London", 3, LANES, EXCLUDE)
    assert out["ok"] and out["pages"] == 2
    assert calls[1]["pageToken"] == "p2"
    assert [j["passes"] for j in out["jobs"]] == [True, False, False]


def test_blocked_request_is_reported_not_raised(monkeypatch):
    def blocked(url, params=None):
        raise FetchError("HTTP 403 from " + url)

    monkeypatch.setattr(probe.http, "get_json", blocked)
    out = probe.probe_api("CRM", "London", 3, LANES, EXCLUDE)
    assert out["ok"] is False and "403" in out["error"]
    summary = probe.report([out], ["search page: HTTP 403"], "London")
    assert "returned no jobs" in summary and "HTTP 403" in summary


def test_report_lists_unique_passing_roles():
    a = {"term": "CRM", "ok": True, "pages": 1, "error": "", "shape": "keys",
         "jobs": [dict(probe.parse_job(_item("CRM Executive")), passes=True)]}
    b = dict(a, term="crm executive")
    summary = probe.report([a, b], [], "London")
    assert "returned jobs for 2 of 2 terms" in summary
    assert "(1 unique)" in summary


def test_embedded_jobs_counts_job_like_objects():
    html = ('<script id="__NEXT_DATA__" type="application/json">'
            '{"props": {"jobs": [{"title": "CRM Executive", "company": {"title": "Acme"}}]}}</script>')
    assert probe.embedded_jobs(html) == 1
    assert probe.embedded_jobs("<html></html>") == 0
