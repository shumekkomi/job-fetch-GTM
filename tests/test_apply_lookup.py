"""Tests for finding a LinkedIn job's posting on the company's own board."""
from jobfetcher import apply_lookup
from jobfetcher.apply_lookup import ApplyUrlFinder, candidate_slugs, normalise_title
from jobfetcher.models import FetchError, Job
from jobfetcher.runner import _attach_apply_urls

HARRYS_POSTING = ("Growth Marketing Manager", "https://job-boards.greenhouse.io/harrys/jobs/1")


class TestCandidateSlugs:
    def test_punctuation_is_dropped(self):
        assert candidate_slugs("Harry's")[0] == "harrys"

    def test_joined_and_hyphenated(self):
        assert candidate_slugs("Mammoth Brands") == ["mammothbrands", "mammoth-brands"]

    def test_suffix_words_are_also_tried_without(self):
        assert "synthflow" in candidate_slugs("Synthflow AI")
        assert "globaldata" in candidate_slugs("GlobalData Plc")


class TestNormaliseTitle:
    def test_ignores_case_and_punctuation(self):
        assert normalise_title("GTM Engineer - Hybrid (UK)") == "gtm engineer hybrid uk"


def _fake_boards(monkeypatch, postings_by_slug):
    calls = []

    def fake_fetch(slug):
        calls.append(slug)
        if slug in postings_by_slug:
            return postings_by_slug[slug]
        raise FetchError("HTTP 404")

    monkeypatch.setattr(apply_lookup, "BOARDS", [("fake", fake_fetch)])
    return calls


class TestApplyUrlFinder:
    def test_finds_same_title(self, monkeypatch):
        _fake_boards(monkeypatch, {"harrys": [HARRYS_POSTING]})
        assert ApplyUrlFinder().find("Harry's", "Growth Marketing Manager") == HARRYS_POSTING[1]

    def test_different_title_gets_no_link(self, monkeypatch):
        # Guards against a different company that happens to use the same board name.
        _fake_boards(monkeypatch, {"harrys": [HARRYS_POSTING]})
        assert ApplyUrlFinder().find("Harry's", "Performance Marketing Manager") is None

    def test_no_board_gets_no_link(self, monkeypatch):
        _fake_boards(monkeypatch, {})
        assert ApplyUrlFinder().find("Referment", "Growth Marketing Manager") is None

    def test_each_company_is_looked_up_once(self, monkeypatch):
        calls = _fake_boards(monkeypatch, {})
        finder = ApplyUrlFinder()
        finder.find("Referment", "Growth Marketing Manager")
        first = len(calls)
        finder.find("Referment", "Paid Media Manager")
        assert len(calls) == first


class TestAttachApplyUrls:
    def test_sets_link_and_drops_jobs_already_saved_from_the_board(self, monkeypatch):
        _fake_boards(monkeypatch, {
            "harrys": [HARRYS_POSTING],
            "jackjill": [("GTM Engineer", "https://jobs.ashbyhq.com/jack-jill/1")],
        })
        harrys = Job(title="Growth Marketing Manager", company="Harry's", url="https://uk.linkedin.com/jobs/view/1")
        jack = Job(title="GTM Engineer", company="Jack & Jill", url="https://uk.linkedin.com/jobs/view/2")
        existing = {"https://jobs.ashbyhq.com/jack-jill/1"}  # saved earlier from Ashby directly

        kept, already_saved = _attach_apply_urls([harrys, jack], ApplyUrlFinder(), existing)

        assert kept == [harrys]
        assert harrys.apply_url == HARRYS_POSTING[1]
        assert already_saved == ["Jack & Jill -- GTM Engineer"]
