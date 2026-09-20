# Job Fetcher

A Python script that fetches job listings from company career pages (via their ATS APIs), filters for relevant roles in London, deduplicates against your existing Airtable records, and writes new matches straight to your **Job Hunt** Airtable base.

Runs daily at 07:00 UK time via GitHub Actions. No AI calls, no headless browser, no paraphrasing. The job descriptions you get are the exact text the company published.

## What it does

1. **Fetches** jobs from each company on your watchlist, using the right adapter for their ATS (Greenhouse, Ashby, Lever, SmartRecruiters, Personio, or JSON-LD structured data).
2. **Filters** by location (London, plus per-company overrides), title (three lanes: Growth, Performance, GTM Engineering), and salary floor (drops anything explicitly below 35k GBP).
3. **Deduplicates** against existing Airtable records by URL and by company+title.
4. **Writes** new jobs to the Jobs table and a run log entry for every company (including failures) to the Run Log table.

## File structure

```
run.py                          Entry point. --dry-run to test without writing.
config.yaml                     Watchlist, title lanes, Airtable IDs. Edit this.
requirements.txt                Python dependencies (requests, pyyaml, pytest).
jobfetcher/
    __init__.py
    config.py                   Loads and validates config.yaml.
    models.py                   Job and CompanyResult data shapes.
    text.py                     HTML-to-text conversion and date parsing.
    http.py                     HTTP requests with retries and error handling.
    filters.py                  Location, title, and salary filters.
    dedup.py                    Dedup against existing Airtable records.
    airtable.py                 Reads from and writes to Airtable.
    runner.py                   Orchestrates the full pipeline.
    adapters/
        __init__.py             Registry of all ATS adapters.
        greenhouse.py           Greenhouse API adapter.
        ashby.py                Ashby API adapter.
        lever.py                Lever API adapter.
        smartrecruiters.py      SmartRecruiters API adapter (two-step fetch).
        personio.py             Personio XML feed adapter.
        workable.py             Stub: public API not working as of Sep 2026.
        recruitee.py            Stub: public API not working as of Sep 2026.
        jsonld.py               Generic JSON-LD schema.org/JobPosting adapter.
tests/
    samples/                    Saved API responses for offline testing.
    test_adapters.py            Adapter tests (mocked HTTP).
    test_filters.py             Filter logic tests.
    test_dedup.py               Dedup logic tests.
    test_text.py                HTML-to-text and date parsing tests.
.github/workflows/
    fetch-jobs.yaml             GitHub Actions: daily run + manual trigger.
```

## How to add a company

1. Find its ATS. Go to the company's careers page, click "Apply" on any job, and look at where the URL points:
   - `boards.greenhouse.io` or `job-boards.greenhouse.io` = Greenhouse
   - `jobs.ashbyhq.com` = Ashby
   - `jobs.lever.co` = Lever
   - `jobs.smartrecruiters.com` = SmartRecruiters
   - `*.jobs.personio.de` = Personio

2. Find its slug. That's the bit after the ATS domain. For example, `https://boards.greenhouse.io/braze/jobs/123` has slug `braze`.

3. Test it. Run this in your terminal (replace the ATS and slug):
   ```
   curl "https://boards-api.greenhouse.io/v1/boards/YOUR_SLUG/jobs" | python3 -c "import sys,json; print(len(json.load(sys.stdin).get('jobs',[])),'jobs')"
   ```
   If you get a number > 0, it works.

4. Add it to `config.yaml` under `companies`:
   ```yaml
   - name: "Company Name"
     ats: greenhouse       # or ashby, lever, smartrecruiters, personio, jsonld
     slug: "the-slug"
     careers_url: "https://company.com/careers"
     tier: 2
     status: active
   ```

5. Run a dry run to check: `python run.py --dry-run`

## How to add a job title

Add it to the right lane in `config.yaml` under `title_lanes`:

```yaml
title_lanes:
  Growth:
    - "Growth Marketing Manager"
    - "Your New Title Here"    # add it here
```

Titles are case-insensitive substring matches, so "Growth Marketing Manager" will also catch "Senior Growth Marketing Manager" and "Growth Marketing Manager, EMEA".

## How to read a failed run's log

1. Go to your GitHub repo, click the **Actions** tab.
2. Click on the failed run (it will have a red cross).
3. Click on the **fetch** job, then **Fetch jobs** step.
4. The log shows exactly what happened for each company. Look for lines starting with `WARNING` or `ERROR`.
5. Also check the **Run Log** table in Airtable. Every company gets an entry, even failures, with the error message in the Notes field.

Common problems:
- **"Empty"** outcome: the API returned 200 but no jobs. The slug is probably wrong, or the company moved ATS. Check their careers page again.
- **"Failed"** with HTTP 404: wrong slug or the board was removed.
- **"Failed"** with timeout: the API was slow. It will retry on the next run.
- **Airtable write failed**: check that your `AIRTABLE_TOKEN` secret is set and hasn't expired.

## Setup (do this yourself)

### 1. Create the GitHub repo

```bash
cd job-fetcher
git init
git add .
git commit -m "Initial commit: job fetcher pipeline"
```

Then create a repo on GitHub (private is fine) and push to it.

### 2. Set the Airtable token as a GitHub secret

1. Go to [airtable.com/create/tokens](https://airtable.com/create/tokens) and create a personal access token with these scopes:
   - `data.records:read` (for dedup)
   - `data.records:write` (for inserting jobs and run logs)
   - Access to the **Job Hunt** base.
2. In your GitHub repo, go to **Settings > Secrets and variables > Actions**.
3. Click **New repository secret**.
4. Name: `AIRTABLE_TOKEN`, Value: paste your token.

### 3. First run

Do a dry run first to see what would happen:

```bash
pip install -r requirements.txt
python run.py --dry-run
```

Then do a real run:

```bash
export AIRTABLE_TOKEN="your_token_here"
python run.py
```

### 4. Enable the schedule

Push to GitHub. The daily run will start automatically. You can also trigger it manually from the Actions tab with the "Run workflow" button.

## Running locally

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Run tests
python -m pytest tests/ -v

# Dry run (no Airtable writes)
python run.py --dry-run

# Real run (needs AIRTABLE_TOKEN)
export AIRTABLE_TOKEN="pat..."
python run.py
```
