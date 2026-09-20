"""Turning HTML job descriptions into plain text.

We do this ourselves with Python's built-in HTML parser rather than asking an AI or a
generic "text extractor" to do it. The parser only removes tags and keeps every word
of the original, so the JD text we store is verbatim. That was the problem with the
first run: the extractor could paraphrase.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from html import unescape
from html.parser import HTMLParser
from typing import Optional

# Tags that should start a new line when we flatten HTML to text.
_BLOCK_TAGS = {
    "p", "div", "br", "li", "ul", "ol", "h1", "h2", "h3", "h4", "h5", "h6",
    "tr", "table", "section", "article", "header", "footer", "blockquote",
}
# Tags whose contents are never job text.
_SKIP_TAGS = {"script", "style"}


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)  # turns &amp; / &pound; etc. into real characters
        self.parts = []
        self._skip_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag in _SKIP_TAGS:
            self._skip_depth += 1
        elif tag in _BLOCK_TAGS:
            self.parts.append("\n")
            if tag == "li":
                self.parts.append("- ")

    def handle_endtag(self, tag):
        if tag in _SKIP_TAGS:
            self._skip_depth = max(0, self._skip_depth - 1)
        elif tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self._skip_depth:
            self.parts.append(data)


def html_to_text(html: Optional[str]) -> str:
    """Strip tags, keep the words. Blank input gives an empty string."""
    if not html:
        return ""
    extractor = _TextExtractor()
    extractor.feed(html)
    extractor.close()
    text = "".join(extractor.parts).replace("\xa0", " ")
    text = re.sub(r"[ \t]+", " ", text)          # collapse runs of spaces
    text = re.sub(r" *\n *", "\n", text)         # trim spaces around line breaks
    text = re.sub(r"\n{3,}", "\n\n", text)       # at most one blank line in a row
    return text.strip()


def unescape_html(escaped: Optional[str]) -> str:
    """Greenhouse sends its description HTML escaped (&lt;div&gt;), so undo that first."""
    return unescape(escaped or "")


def iso_to_date(value: Optional[str]) -> Optional[str]:
    """'2026-09-15T10:12:25-04:00' -> '2026-09-15'. Returns None if it isn't a usable date.

    We keep the date exactly as the source states it (no timezone conversion), because
    Airtable's Posted Date field only holds a date and the source's own day is the honest one.
    """
    if not value or not isinstance(value, str):
        return None
    match = re.match(r"^(\d{4})-(\d{2})-(\d{2})", value)
    if not match:
        return None
    try:
        datetime(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    except ValueError:
        return None
    return "-".join(match.groups())


def epoch_ms_to_date(value) -> Optional[str]:
    """Lever gives dates as milliseconds since 1970. Convert to 'YYYY-MM-DD' (UTC)."""
    if not isinstance(value, (int, float)) or value <= 0:
        return None
    return datetime.fromtimestamp(value / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
