"""Tests for the description knock-outs and flags in fit.py.

The example sentences are modelled on real job ads from Sep to Nov 2026, with
the outcome each one should get: kept if the role was applied to, dropped if
it was hard-skipped for that reason.
"""
import pytest

from jobfetcher.config import load_config
from jobfetcher.fit import DescriptionChecks, find_phrase, load_description_checks, normalise


@pytest.fixture
def checks():
    return load_config("config.yaml").description_checks


def _ko(checks, description, title="CRM Executive"):
    return checks.knock_out(title, description)


class TestMustHaveTools:
    def test_tool_next_to_alternatives_is_kept(self, checks):
        # Applied: Beauty Pie, Whitbread, Boden list SFMC beside other platforms.
        for line in [
            "- Have experience using CRM platforms such as Iterable, Braze, Klaviyo or Salesforce Marketing Cloud.",
            "- Experience using Braze or another leading platform, such as Salesforce Marketing Cloud, Adobe Campaign or Klaviyo",
            "- Experience using an Email Service Provider (ESP) platform, such as Ometria, Salesforce Marketing Cloud or similar.",
        ]:
            assert _ko(checks, line) is None, line

    def test_tool_as_ideally_is_kept(self, checks):
        # Applied: ITG for M&S Food.
        assert _ko(checks, "- Experience using an email marketing platform, ideally Salesforce Marketing Cloud.") is None

    def test_tool_used_in_the_job_but_not_required_is_kept(self, checks):
        # Applied: Warner Bros. Discovery (a duty, not a must-have).
        assert _ko(checks, "- Build, schedule and maintain email campaigns in Salesforce Marketing Cloud across three markets.") is None

    def test_hands_on_with_no_alternative_is_dropped(self, checks):
        # Hard skip: De Beers.
        assert _ko(checks, "- Hands-on experience with Salesforce Marketing Cloud and Service Cloud") == \
            "must-have salesforce marketing cloud"

    def test_certification_is_dropped(self, checks):
        # Hard skip: Station (recruiter).
        reason = _ko(checks, "- Proven hands-on experience and certification(s) in Salesforce Marketing Cloud and Sales Cloud.")
        assert reason.startswith("must-have")

    def test_tool_in_title_is_dropped(self, checks):
        assert _ko(checks, "", title="Salesforce Marketing Cloud Specialist") == "must-have salesforce marketing cloud"

    def test_pardot_is_not_marketing_cloud(self, checks):
        line = "Strong experience in Marketing Cloud Account Engagement (MCAE formerly known as Pardot) is required."
        assert _ko(checks, line) is None


class TestYears:
    def test_lower_number_of_a_range(self):
        assert DescriptionChecks.years_asked("You'll have somewhere between 2 and 5 years of work experience.") == 2
        assert DescriptionChecks.years_asked("3 to 5 years of experience in growth marketing") == 3
        assert DescriptionChecks.years_asked("5–7 years of experience in CRM, ideally in ecommerce") == 5

    def test_five_plus_is_dropped(self, checks):
        assert _ko(checks, "- 5+ years' experience within Revenue Operations.") == "5+ years"
        assert _ko(checks, "- A minimum of 5 years of experience in lifecycle.") == "5+ years"

    def test_under_five_is_kept(self, checks):
        assert _ko(checks, "- Have 1–3 years' experience in CRM or Lifecycle Marketing.") is None

    def test_years_outside_experience_sentences_ignored(self, checks):
        assert _ko(checks, "We have been growing for 10 years. 2+ years of CRM experience.") is None


class TestLanguageAndPaid:
    def test_fluent_language_dropped(self, checks):
        assert _ko(checks, "You must be fluent in French.") == "fluent in french"
        assert _ko(checks, "German speaking CRM role") == "german speaking"

    def test_language_for_another_office_is_kept(self, checks):
        # Applied: sunday GTM Engineer (Paris or London).
        line = "Languages: fluent French and professional English for Paris; professional English for London."
        assert _ko(checks, line, title="GTM Engineer") is None

    def test_language_as_nice_to_have_is_not_matched(self, checks):
        assert _ko(checks, "- German or French language skills") is None

    def test_paid_heavy_drop_and_flag(self, checks):
        heavy = "Google Ads, paid search, paid social, PPC, Meta Ads, PMax, bidding, SA360, Search Ads 360."
        assert _ko(checks, heavy, title="Growth Marketing Specialist") == "paid media heavy"
        some = "You run Google Ads and Meta Ads, paid search and paid social, with PPC reporting."
        assert _ko(checks, some, title="Growth Marketing Manager") is None
        assert "paid media mentioned 5 times" in checks.flags(some)

    def test_no_description_is_kept(self, checks):
        assert _ko(checks, "") is None


class TestFlags:
    def test_lists_tools_found(self, checks):
        note = checks.flags("You'll own HubSpot workflows, write SQL and automate hand-offs with Zapier.")
        assert note == "tools: HubSpot, Zapier/Make/n8n, SQL, AI/automation (4)"

    def test_tools_are_whole_words(self, checks):
        # "clay" inside "Barclays" and "ai" inside "maintain" must not count.
        assert checks.flags("Maintain reports for Barclays.") == "tools: none of the tracked tools (0)"

    def test_empty_description_gets_no_note(self, checks):
        assert checks.flags("") == ""


class TestHelpers:
    def test_normalise(self):
        assert normalise("Go-to-Market  Engineer (London)") == "go to market engineer london"

    def test_find_phrase_whole_words(self):
        assert find_phrase("Senior CRM Exec", ["senior"]) == "senior"
        assert find_phrase("Seniority", ["senior"]) is None

    def test_missing_block_means_no_checks(self):
        assert load_description_checks(None) is None

    def test_bad_tool_flags_rejected(self):
        with pytest.raises(ValueError):
            load_description_checks({"tool_flags": ["hubspot"]})
