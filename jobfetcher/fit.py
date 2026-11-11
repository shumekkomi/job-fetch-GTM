"""Title and description rules: is this role worth saving, and what should it be flagged with?

Three jobs, all driven by config.yaml so the word lists can change without code:

  1. Title lanes and excludes. A title is matched on whole words, with hyphens
     treated as spaces, so "Go-to-Market Engineer" and "Go to Market Engineer"
     both match "go to market", and "crm" never matches inside another word.
  2. Description knock-outs: a must-have tool you don't use (Salesforce
     Marketing Cloud, Adobe, Marketo), too many years asked, a second language
     required, or a description that is mostly paid search and paid social.
  3. Flags for the roles that pass: which useful tools the description names,
     and whether it leans on paid media. These go into the Notes column.

The rules were tested on 131 roles you applied to, shortlisted or skipped
(Nov 2026). The two lessons from that test are built in here:
  - A tool only knocks a role out when it is in the title, or named as a must
    with no alternative offered. Most CRM ads list Salesforce Marketing Cloud
    next to Braze or Klaviyo, and you apply to those.
  - Years are read as the lower number of a range: "2 to 5 years" is 2.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional

# ---------------------------------------------------------------------------
# Whole-word phrase matching
# ---------------------------------------------------------------------------

_SPACERS = re.compile(r"[-–—/_|,()\[\]:]+")


def normalise(text: str) -> str:
    """Lowercase, hyphens and similar punctuation to spaces, single spaces."""
    return " ".join(_SPACERS.sub(" ", (text or "").lower()).split())


def _phrase_pattern(phrase: str) -> "re.Pattern":
    words = normalise(phrase)
    return re.compile(r"(?<![a-z0-9])" + re.escape(words) + r"(?![a-z0-9])")


def find_phrase(text: str, phrases: List[str]) -> Optional[str]:
    """Return the first phrase found in text as whole words, or None."""
    norm = normalise(text)
    for phrase in phrases:
        if _phrase_pattern(phrase).search(norm):
            return phrase
    return None


def match_lane(title: str, title_lanes: Dict[str, List[str]]) -> Optional[str]:
    """The first lane with a phrase found in the title, or None. Order matters."""
    for lane, phrases in title_lanes.items():
        if find_phrase(title, phrases):
            return lane
    return None


def title_passes(title: str, title_lanes: Dict[str, List[str]], title_exclude: List[str]) -> bool:
    """A lane matches and no exclude word is in the title."""
    return match_lane(title, title_lanes) is not None and find_phrase(title, title_exclude) is None


# ---------------------------------------------------------------------------
# Description checks
# ---------------------------------------------------------------------------

# Words that make a tool a nice-to-have rather than a must.
_SOFT = re.compile(
    r"desirable|nice to have|nice-to-have|bonus|a plus|ideally|preferred|advantage|"
    r"beneficial|familiarity|exposure", re.I)
# Words that make a tool a must.
_MUST = re.compile(
    r"hands-on|certif|proven|expert|essential|\bmust\b|\brequired\b|is a requirement|"
    r"\bstrong\b|\bdeep\b|advanced|administration", re.I)
# Words that offer an alternative, so the tool isn't the only way in.
_ALTERNATIVE = re.compile(
    r"or similar|such as|\blike\b|e\.g\.|for example|equivalent|another|any (major|leading)|either|"
    r"braze|klaviyo|iterable|hubspot|dotdigital|bloomreach|ometria|customer\.io|emarsys", re.I)
# "Marketing Cloud Account Engagement" is Pardot, not Salesforce Marketing Cloud.
_NOT_THE_TOOL = re.compile(r"account engagement|pardot|\bmcae\b", re.I)
# "5+ years", "3 to 5 years", "between 2 and 5 years": group 1 is the lower number.
_YEARS = re.compile(
    r"(?:between\s+)?(\d{1,2})\s*\+?\s*(?:(?:-|–|to|and)\s*\d{1,2}\s*)?\+?\s*years?", re.I)
_PAID_TERMS = re.compile(
    r"google ads|paid search|paid social|\bppc\b|meta ads|performance max|\bpmax\b|"
    r"search ads 360|\bsa360\b|bidding", re.I)


def sentences(text: str) -> List[str]:
    """Split a description into lines and sentences (bullets count as lines)."""
    parts = re.split(r"\n+|(?<=[.!?])\s+|\s[•·]\s", text or "")
    return [p for p in parts if p.strip()]


def _word_regex(words: List[str]) -> Optional["re.Pattern"]:
    if not words:
        return None
    return re.compile(r"(?<![a-z0-9])(" + "|".join(re.escape(w.lower()) for w in words) + r")(?![a-z0-9])", re.I)


@dataclass
class DescriptionChecks:
    """Settings for the description knock-outs and flags (config: description_checks)."""
    must_have_tools: List[str] = field(default_factory=list)
    max_years: Optional[int] = None          # drop if the ad asks for this many years or more
    languages: List[str] = field(default_factory=list)
    paid_heavy_mentions: Optional[int] = None  # drop at this many paid-media mentions
    paid_flag_mentions: Optional[int] = None   # flag (but keep) at this many
    tool_flags: Dict[str, List[str]] = field(default_factory=dict)  # label -> words

    # -- knock-outs --

    def must_have_tool(self, title: str, description: str) -> Optional[str]:
        """A listed tool in the title, or named as a must with no alternative."""
        tools = _word_regex(self.must_have_tools)
        if tools is None:
            return None
        m = tools.search(title or "")
        if m:
            return m.group(0).lower()
        for s in sentences(description):
            m = tools.search(s)
            if not m or _NOT_THE_TOOL.search(s):
                continue
            if _MUST.search(s) and not _SOFT.search(s) and not _ALTERNATIVE.search(s):
                return m.group(0).lower()
        return None

    @staticmethod
    def years_asked(description: str) -> int:
        """The highest minimum years figure in any sentence about experience."""
        best = 0
        for s in sentences(description):
            if not re.search(r"experience|years of work", s, re.I):
                continue
            for m in _YEARS.finditer(s):
                n = int(m.group(1))
                if n <= 15:
                    best = max(best, n)
        return best

    def language_required(self, description: str) -> Optional[str]:
        if not self.languages:
            return None
        langs = "|".join(re.escape(l.lower()) for l in self.languages)
        pattern = re.compile(
            r"(fluent|fluency|native|business[- ]level|professional[- ]level)\s+(in\s+)?(" + langs + r")"
            r"|(" + langs + r")[- ](speaking|speaker)", re.I)
        for s in sentences(description):
            m = pattern.search(s)
            # "Fluent French for Paris; professional English for London" ties
            # the language to another office, so a London hire doesn't need it.
            if m and not re.search(r"\blondon\b", s, re.I):
                return m.group(0)
        return None

    @staticmethod
    def paid_mentions(description: str) -> int:
        return len(_PAID_TERMS.findall(description or ""))

    def knock_out(self, title: str, description: str) -> Optional[str]:
        """The reason to drop this role, or None to keep it.

        A role with no description is kept: there's nothing to check.
        """
        tool = self.must_have_tool(title, description)
        if tool:
            return "must-have {}".format(tool)
        if not description:
            return None
        if self.max_years:
            years = self.years_asked(description)
            if years >= self.max_years:
                return "{}+ years".format(years)
        lang = self.language_required(description)
        if lang:
            return lang.lower()
        if self.paid_heavy_mentions and self.paid_mentions(description) >= self.paid_heavy_mentions:
            return "paid media heavy"
        return None

    # -- flags --

    def flags(self, description: str) -> str:
        """One line for the Notes column, e.g. 'tools: HubSpot, SQL (2); paid media mentioned 6 times'."""
        parts = []
        found = [label for label, words in self.tool_flags.items()
                 if _word_regex(words) and _word_regex(words).search(description or "")]
        if found:
            parts.append("tools: {} ({})".format(", ".join(found), len(found)))
        elif description:
            parts.append("tools: none of the tracked tools (0)")
        if self.paid_flag_mentions:
            n = self.paid_mentions(description)
            if n >= self.paid_flag_mentions:
                parts.append("paid media mentioned {} times: check it isn't a paid role".format(n))
        return "; ".join(parts)


def load_description_checks(raw: Optional[dict]) -> Optional[DescriptionChecks]:
    """Build DescriptionChecks from the config block, or None if it's absent."""
    if not raw:
        return None
    if not isinstance(raw, dict):
        raise ValueError("Config 'description_checks' must be a mapping")

    def _int(key):
        value = raw.get(key)
        return int(value) if value is not None else None

    tool_flags = raw.get("tool_flags") or {}
    if not isinstance(tool_flags, dict):
        raise ValueError("Config 'description_checks.tool_flags' must map a label to a list of words")
    return DescriptionChecks(
        must_have_tools=list(raw.get("must_have_tools") or []),
        max_years=_int("max_years"),
        languages=list(raw.get("languages") or []),
        paid_heavy_mentions=_int("paid_heavy_mentions"),
        paid_flag_mentions=_int("paid_flag_mentions"),
        tool_flags={str(k): list(v or []) for k, v in tool_flags.items()},
    )
