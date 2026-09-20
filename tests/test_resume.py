"""Tests for the resume scorer."""
from jobfetcher.models import Job
from jobfetcher.resume import extract_keywords, score_job


def _job(title="Engineer", description=""):
    return Job(title=title, company="TestCo", url="https://example.com", description=description)


class TestExtractKeywords:
    def test_filters_stop_words(self):
        kw = extract_keywords("I have experience with Python and JavaScript")
        assert "python" in kw
        assert "javascript" in kw
        assert "have" not in kw
        assert "with" not in kw

    def test_keeps_short_technical_terms(self):
        kw = extract_keywords("Skills: SQL, AI, ML, GTM, CRO, PPC")
        assert "sql" in kw
        assert "ai" in kw
        assert "gtm" in kw
        assert "ppc" in kw

    def test_strips_punctuation(self):
        kw = extract_keywords("Python. JavaScript, HubSpot!")
        assert "python" in kw
        assert "javascript" in kw
        assert "hubspot" in kw


class TestScoreJob:
    def test_perfect_overlap(self):
        kw = {"python", "marketing", "analytics"}
        job = _job(description="We need python marketing analytics expertise")
        assert score_job(job, kw) == 100

    def test_partial_overlap(self):
        kw = {"python", "marketing", "analytics", "hubspot"}
        job = _job(description="We need python and marketing skills")
        score = score_job(job, kw)
        assert 40 <= score <= 60

    def test_no_overlap(self):
        kw = {"python", "marketing"}
        job = _job(description="Looking for a chef with culinary experience")
        assert score_job(job, kw) == 0

    def test_empty_keywords(self):
        assert score_job(_job(), set()) == 0

    def test_title_counts(self):
        kw = {"gtm", "engineer"}
        job = _job(title="GTM Engineer", description="")
        assert score_job(job, kw) == 100
