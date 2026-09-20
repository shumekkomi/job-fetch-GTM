"""Tests for HTML-to-text conversion and date parsing."""
from jobfetcher.text import html_to_text, iso_to_date, epoch_ms_to_date


class TestHtmlToText:
    def test_strips_tags(self):
        assert html_to_text("<p>Hello <b>world</b></p>") == "Hello world"

    def test_preserves_list_items(self):
        result = html_to_text("<ul><li>One</li><li>Two</li></ul>")
        assert "- One" in result
        assert "- Two" in result

    def test_handles_entities(self):
        assert "£" in html_to_text("Salary: &pound;50,000")

    def test_strips_script_and_style(self):
        html = "<p>Keep</p><script>alert('hi')</script><style>.x{}</style><p>Also keep</p>"
        result = html_to_text(html)
        assert "Keep" in result
        assert "Also keep" in result
        assert "alert" not in result
        assert ".x{}" not in result

    def test_blank_input(self):
        assert html_to_text("") == ""
        assert html_to_text(None) == ""

    def test_no_excessive_whitespace(self):
        result = html_to_text("<p>A</p><p></p><p></p><p>B</p>")
        # At most one blank line between paragraphs.
        assert "\n\n\n" not in result


class TestIsoToDate:
    def test_standard_iso(self):
        assert iso_to_date("2026-09-15T10:12:25-04:00") == "2026-09-15"

    def test_date_only(self):
        assert iso_to_date("2026-09-15") == "2026-09-15"

    def test_invalid_date(self):
        assert iso_to_date("2026-13-01") is None  # month 13

    def test_none(self):
        assert iso_to_date(None) is None

    def test_empty(self):
        assert iso_to_date("") is None

    def test_garbage(self):
        assert iso_to_date("not a date") is None


class TestEpochMsToDate:
    def test_lever_date(self):
        # 1725235200000 ms = 2024-09-02 (UTC)
        assert epoch_ms_to_date(1725235200000) == "2024-09-02"

    def test_zero(self):
        assert epoch_ms_to_date(0) is None

    def test_negative(self):
        assert epoch_ms_to_date(-1) is None

    def test_none(self):
        assert epoch_ms_to_date(None) is None
