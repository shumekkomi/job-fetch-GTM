# Job Fetcher

A scheduled pipeline that pulls job listings straight from company ATS APIs, filters them, deduplicates them against what is already tracked, and saves new matches to a Postgres database on Supabase with the full job description captured at fetch time. It also writes a run log row for every source on every run, including the ones that fail.

It runs once a day on GitHub Actions. It makes no LLM calls: the job text stored is exactly what the company published.

**Status:** running daily since 21 September 2026. An audit on 6 October found two bugs that the green ticks on GitHub had hidden: the first week of runs wrote nothing, and later runs wrote the same jobs again every day. Both are fixed and covered by tests (see the last two failure modes below).

## Why it exists, and why there is no AI in the fetch layer

The first version was a Claude skill that fetched, cleaned and wrote records through Airtable's MCP server. It worked, but it was the wrong tool for the job. Fetching and filtering are the same steps every day, and an LLM doing them costs tokens on every record, can paraphrase a job description instead of storing it word for word, and cannot be covered by tests. So the fetching, filtering and deduplication moved into this Python script, which is deterministic, testable and free to run. Judgement work, like deciding whether a role is worth applying for, stays with me and with Claude outside this repo.

## Where results are saved

Until 6 November 2026 results went to Airtable. The free plan's record cap was about to stop the daily writes, and a spreadsheet tool was the wrong place for the analysis that comes next (salary bands, requirement counts, how long roles stay open). So results now go to a `jobhunt` schema in a Supabase Postgres database, alongside the applications and CV versions they get compared against. The 266 jobs and 1,816 run log rows already in Airtable were copied across first, so dedup still sees everything saved before the switch.

The script connects straight to the database rather than through Supabase's web API, so the schema never has to be exposed publicly. Airtable still works: set `storage: airtable` in `config.yaml`.

## What it covers

| | Count |
|---|---|
| Active sources | 34 (13 Greenhouse boards, 8 Ashby boards, 2 Teamtailor sites, 1 SmartRecruiters board, 10 LinkedIn title searches) |
| Companies checked and logged as having no public ATS | 10 |
| ATS adapters | Greenhouse, Ashby, Lever, SmartRecruiters, Personio, Teamtailor (RSS), generic schema.org JSON-LD, LinkedIn guest search |
| Tests | 170, run before every scheduled fetch |

## How it works

1. **Fetch.** Each company in `config.yaml` is fetched with the adapter for its ATS. LinkedIn entries are title searches rather than company boards, so they find employers that are not on the watchlist.
2. **Filter.** Location (London by default, with per-company aliases; with `include_remote` on, remote roles from any region are kept too, and labelled in Location when they're listed for another region or don't say), title (whole-word match into four lanes: GTM Engineering, RevOps & Systems, CRM & Lifecycle, Growth, minus an exclude list for senior, regional and paid media titles), description checks (drops roles that require a tool I don't use, 5+ years, a second language, or are mostly paid media; flags the useful tools named in the Notes column) and a salary floor that only drops roles explicitly paying below it.
3. **Deduplicate.** Against every job already saved, first by URL, then by company plus title, so the same role found through two sources is only written once.
4. **Find the original posting (LinkedIn jobs only).** LinkedIn hides where "Apply" leads from logged-out visitors, so for each new LinkedIn job the pipeline guesses the company's board name and looks on Greenhouse, Ashby, Lever and SmartRecruiters. If a posting with exactly the same title is there, its link goes in **Apply URL**. If that posting was already saved straight from the company's board, the LinkedIn copy is skipped as a duplicate.
5. **Save.** New jobs go to the jobs table with the full description and, where the source gives one, the structured salary range. Every source gets a run log row with its outcome (OK, Empty, Failed, Skipped) and a note.

## Failure modes it handles

These came from real runs, not from planning.

- **A successful response with nothing in it.** Greenhouse returns HTTP 200 with an empty jobs array when a slug is wrong. Read naively, that looks like "this company has no open roles". The pipeline logs it as **Empty**, a probable slug failure, rather than as a genuine zero. HubSpot's board is currently in this state and is marked broken in config.
- **Locations labelled by country instead of city.** Bloomreach lists UK roles as "United Kingdom", so a London filter silently dropped them. Config now supports per-company location aliases.
- **Companies with no public ATS.** Ten watchlist companies (proprietary systems, Workday, Jobvite) cannot be polled. They stay in config with status `unsupported` and a dated note on what was checked, so they are not silently missing.
- **Partial failures.** One source timing out or 404ing does not stop the run. It gets a Failed row in the Run Log and the rest carry on.
- **Runs that pass while writing nothing.** For the first week the Airtable token was wrong, so every write got `403 Forbidden`. The script logged the errors and exited normally, so GitHub showed every run as passed. Now the run stops if it cannot read its storage, and exits with an error if any write fails, which turns the run red and sends an email.
- **A duplicate check that never matched.** Airtable returns record fields keyed by field name unless the request asks for field IDs. The code looked fields up by ID, so it always saw an empty table and saved every job again each day: 476 of 556 rows were duplicates by the time it was caught. The code now uses field names everywhere (which also lets anyone run it against their own base), a test fakes Airtable's behaviour so a names-versus-IDs mismatch fails the build, and the duplicates were removed.

## Known limitations

- Resume scoring (a 0 to 100 keyword overlap between a job and my CV) only runs where the CV file exists. The CV lives in a git-ignored `private/` folder, so scheduled runs on GitHub Actions log a warning and skip scoring. Scores land between about 15 and 45, so they work as a ranking rather than a percentage fit.
- The LinkedIn adapter reads LinkedIn's public guest search pages, capped at three pages per query, and will break if LinkedIn changes its markup. After nine daily searches started hitting LinkedIn's rate limit (HTTP 429), it now waits 2 seconds between requests, skips the detail page for any result whose title no lane matches, has an exclude word or is already saved, and retries a 429 after the server's Retry-After (capped at 60 seconds).
- Apply URL is found for roughly 15% of LinkedIn jobs (12 of 80 when first run). Recruitment agency posts never match, nor do companies on Workday or their own careers sites, or boards whose name differs from the company name. Reading the real link from LinkedIn would need a logged-in session, which LinkedIn's terms don't allow for scraping.
- Workable and Recruitee adapters are stubs: their public endpoints were not usable when this was built. `probe_workable.py` (manual workflow "Probe Workable search") tests whether Workable's cross-employer search at jobs.workable.com can be read instead. It saves nothing.
- The title and description rules were tuned on 131 roles I applied to, shortlisted or skipped (Sep to Nov 2026). They kept 79 of the 80 I acted on or held and dropped 19 of the 24 I hard-skipped. Tested on the same roles they were written from, so expect them to do somewhat worse on new ones.
- The schedule asks for 06:00 UTC, but GitHub delays scheduled runs on busy days. In practice they have started between about 10:30 and 13:00 UTC, so new postings are saved around midday rather than first thing.

## File structure

```
run.py                          Entry point. --dry-run to test without writing.
probe_workable.py               One-off test of Workable's job search. Saves nothing.
config.yaml                     Watchlist, title lanes, salary floor.
requirements.txt                Exact versions of every dependency.
jobfetcher/
    config.py                   Loads and validates config.yaml.
    models.py                   Job and CompanyResult data shapes.
    text.py                     HTML-to-text conversion and date parsing.
    http.py                     HTTP requests with retries and error handling.
    filters.py                  Location, title, description and salary filters.
    fit.py                      Title word matching, description knock-outs and Notes flags.
    dedup.py                    Dedup against jobs already saved.
    resume.py                   Keyword-overlap scoring against a CV.
    apply_lookup.py             Finds a LinkedIn job's posting on the company's own board.
    supabase_store.py           Reads from and writes to Supabase (Postgres).
    airtable.py                 Reads from and writes to Airtable.
    runner.py                   Orchestrates the full pipeline.
    adapters/                   One module per ATS (see table above).
tests/
    samples/                    Saved API responses for offline tests.
    test_*.py                   Adapter, filter, dedup, text and scoring tests.
.github/workflows/
    fetch-jobs.yaml             Daily run plus a manual trigger.
    probe-workable.yaml         Manual run of probe_workable.py.
```

## Running it yourself

Python 3.12. A dry run needs nothing else: no database, no token, no CV.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

python -m pytest tests/ -v      # tests
python run.py --dry-run         # fetch and filter, print what would be saved
```

### Saving to your own Supabase

1. In a Supabase project, open the SQL editor and create the schema:

```sql
create schema jobhunt;
create table jobhunt.jobs (
  id bigint generated always as identity primary key,
  pipeline text, data_source text, job_label text,
  company text not null, role_title text not null, source text,
  jd_text text, raw_blob text, job_url text unique, apply_url text,
  salary_posted text, salary_min numeric, salary_max numeric,
  salary_currency text, salary_interval text, location text,
  date_posted date, posted_date_kind text, fingerprint text, lane text,
  status text, match_score numeric, notes text, first_seen timestamptz default now()
);
create table jobhunt.run_log (
  id bigint generated always as identity primary key,
  pipeline text, data_source text, target text, type text,
  last_polled date, polled_at timestamptz default now(),
  outcome text, listings_found integer, notes text
);
alter table jobhunt.jobs enable row level security;
alter table jobhunt.run_log enable row level security;
```

   Row level security with no policies keeps both tables closed to the public API. The script isn't affected, because it connects as the database owner.

2. Copy the **Session pooler** connection string from the project's Connect panel (GitHub's runners can't reach the direct connection, which is IPv6 only), put your database password in it, then:

```bash
export SUPABASE_DB_URL="postgresql://postgres.<project>:<password>@<region>.pooler.supabase.com:5432/postgres"
python run.py --dry-run   # checks the connection and dedup, saves nothing
python run.py
```

A real run stops straight away if `SUPABASE_DB_URL` is missing, and stops before saving anything if the database can't be read. A URL that is already saved is never overwritten.

### Saving to your own Airtable

Set `storage: airtable` in `config.yaml`, then:


1. In a base of your own, create the two tables below. Field names must match exactly (the code finds fields by name); the order doesn't matter, and extra fields are ignored.
2. Create a [personal access token](https://airtable.com/create/tokens) with `data.records:read` and `data.records:write`, limited to that base.
3. Copy the base ID (`app...`) and the two table IDs (`tbl...`) from the table URLs, then:

```bash
export AIRTABLE_TOKEN="pat..."
export AIRTABLE_BASE_ID="app..."
export AIRTABLE_JOBS_TABLE_ID="tbl..."
export AIRTABLE_RUNLOG_TABLE_ID="tbl..."
python run.py
```

A real run stops straight away if any of the four is missing. None of them are in this repo.

**Jobs table**

| Field | Type | Notes |
|---|---|---|
| Job | Single line text | Primary field. Written as "Company — Title" |
| Title, Company, Salary, Location, Fingerprint | Single line text | |
| JD Text, Raw Blob, Notes | Long text | |
| Original URL | URL | Used for deduplication |
| Apply URL | URL | LinkedIn jobs only: the company's own posting, when found |
| Posted Date | Date | |
| Source | Single select | Direct, LinkedIn |
| Lane | Single select | One option per lane in `config.yaml` |
| Status | Single select | New (add your own, e.g. Applied) |
| Match Score | Number (integer) | Only filled when a CV is present |

**Run Log table**

| Field | Type | Notes |
|---|---|---|
| Target | Single line text | Primary field |
| Type | Single select | ATS, Web search, Board |
| Last Polled | Date | |
| Outcome | Single select | OK, Empty, Failed, Skipped |
| Listings Found | Number (integer) | |
| Notes | Long text | |

Missing dropdown options are added automatically on the first save (the API's `typecast` option), so the lists above can start empty.

### Running it on a fork

Add `SUPABASE_DB_URL` (or the four Airtable values) as Actions secrets in your fork (Settings, then Secrets and variables, then Actions). GitHub switches off scheduled workflows on forks, so turn it on once from the Actions tab. "Run workflow" there starts a run straight away, and its dry run option checks the setup without saving anything.

### Resume scoring

Put your CV (as `.md` or `.txt`) at `private/cv.md`, or pass `--resume path/to/cv.md`. The `private/` folder is git-ignored. Without a CV, scoring is skipped.

### Adding a company

1. Click "Apply" on any of its jobs and check where the link goes: `job-boards.greenhouse.io` (Greenhouse), `jobs.ashbyhq.com` (Ashby), `jobs.lever.co` (Lever), `jobs.smartrecruiters.com` (SmartRecruiters), `*.jobs.personio.de` (Personio), `*.teamtailor.com` (Teamtailor; the slug is the subdomain, or the full careers URL on a custom domain).
2. The slug is the part after the domain, e.g. `braze` in `boards.greenhouse.io/braze/jobs/123`.
3. Check the board returns jobs:
   ```
   curl "https://boards-api.greenhouse.io/v1/boards/YOUR_SLUG/jobs" | python3 -c "import sys,json; print(len(json.load(sys.stdin).get('jobs',[])),'jobs')"
   ```
   Zero on a company that is visibly hiring means the slug is wrong.
4. Add it under `companies` in `config.yaml` and run `python run.py --dry-run`.

### Adding a title

Add a word or phrase to a lane under `title_lanes` in `config.yaml`. Matching is case-insensitive and on whole words, with hyphens read as spaces: "go to market" catches "Go-to-Market Engineer", and "crm" never matches inside another word. To stop a kind of title, add a word to `title_exclude`. The knock-outs and Notes flags live under `description_checks`.

### Reading a failed run

Check the Actions tab for the run's log (look for `WARNING` and `ERROR` lines), then the run log table, where every source has a row and failures carry the error in Notes. An **Empty** outcome usually means a wrong slug or a company that changed ATS.
