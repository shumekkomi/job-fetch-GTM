# Job Fetcher

A scheduled pipeline that pulls job listings straight from company ATS APIs, filters them, deduplicates them against what is already tracked, and writes new matches to Airtable with the full job description captured at fetch time. It also writes a run log row for every source on every run, including the ones that fail.

It runs once a day on GitHub Actions. It makes no LLM calls: the job text stored is exactly what the company published.

**Status:** every scheduled run from 21 September to 5 October 2026 completed. Individual sources can still fail inside a run; those are recorded in the Run Log rather than stopping the job.

## Why it exists, and why there is no AI in the fetch layer

The first version was a Claude skill that fetched, cleaned and wrote records through Airtable's MCP server. It worked, but it was the wrong tool for the job. Fetching and filtering are the same steps every day, and an LLM doing them costs tokens on every record, can paraphrase a job description instead of storing it word for word, and cannot be covered by tests. So the fetching, filtering and deduplication moved into this Python script, which is deterministic, testable and free to run. Judgement work, like deciding whether a role is worth applying for, stays with me and with Claude outside this repo.

## What it covers

| | Count |
|---|---|
| Active sources | 26 (13 Greenhouse boards, 7 Ashby boards, 1 SmartRecruiters board, 5 LinkedIn title searches) |
| Companies checked and logged as having no public ATS | 10 |
| ATS adapters | Greenhouse, Ashby, Lever, SmartRecruiters, Personio, generic schema.org JSON-LD, LinkedIn guest search |
| Tests | 62, run before every scheduled fetch |

## How it works

1. **Fetch.** Each company in `config.yaml` is fetched with the adapter for its ATS. LinkedIn entries are title searches rather than company boards, so they find employers that are not on the watchlist.
2. **Filter.** Location (London by default, with per-company aliases), title (substring match into three lanes: Growth, Performance, GTM Engineering) and a salary floor that only drops roles explicitly paying below it.
3. **Deduplicate.** Against existing Airtable records, first by URL, then by company plus title, so the same role found through two sources is only written once.
4. **Write.** New jobs go to the Jobs table with the full description. Every source gets a Run Log row with its outcome (OK, Empty, Failed, Skipped) and a note.

## Failure modes it handles

These came from real runs, not from planning.

- **A successful response with nothing in it.** Greenhouse returns HTTP 200 with an empty jobs array when a slug is wrong. Read naively, that looks like "this company has no open roles". The pipeline logs it as **Empty**, a probable slug failure, rather than as a genuine zero. HubSpot's board is currently in this state and is marked broken in config.
- **Locations labelled by country instead of city.** Bloomreach lists UK roles as "United Kingdom", so a London filter silently dropped them. Config now supports per-company location aliases.
- **Companies with no public ATS.** Ten watchlist companies (proprietary systems, Workday, Jobvite) cannot be polled. They stay in config with status `unsupported` and a dated note on what was checked, so they are not silently missing.
- **Partial failures.** One source timing out or 404ing does not stop the run. It gets a Failed row in the Run Log and the rest carry on.

## Known limitations

- Resume scoring (a 0 to 100 keyword overlap between a job and my CV) only runs where the CV file exists. It is a local file, so scheduled runs on GitHub Actions log a warning and skip scoring.
- The LinkedIn adapter reads LinkedIn's public guest search pages. It is rate-limited and capped at three pages per query, and it will break if LinkedIn changes its markup.
- Workable and Recruitee adapters are stubs: their public endpoints were not usable when this was built.
- The schedule asks for 06:00 UTC, but GitHub delays scheduled runs on busy days. In practice they have started between about 10:30 and 13:00 UTC, so new postings land in Airtable around midday rather than first thing.

## File structure

```
run.py                          Entry point. --dry-run to test without writing.
config.yaml                     Watchlist, title lanes, Airtable IDs.
requirements.txt                Python dependencies (requests, pyyaml, pytest).
jobfetcher/
    config.py                   Loads and validates config.yaml.
    models.py                   Job and CompanyResult data shapes.
    text.py                     HTML-to-text conversion and date parsing.
    http.py                     HTTP requests with retries and error handling.
    filters.py                  Location, title and salary filters.
    dedup.py                    Dedup against existing Airtable records.
    resume.py                   Keyword-overlap scoring against a CV.
    airtable.py                 Reads from and writes to Airtable.
    runner.py                   Orchestrates the full pipeline.
    adapters/                   One module per ATS (see table above).
tests/
    samples/                    Saved API responses for offline tests.
    test_*.py                   Adapter, filter, dedup, text and scoring tests.
.github/workflows/
    fetch-jobs.yaml             Daily run plus a manual trigger.
```

## Running it yourself

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

python -m pytest tests/ -v      # tests
python run.py --dry-run         # fetch and filter, no Airtable writes
export AIRTABLE_TOKEN="pat..."  # Airtable personal access token
python run.py                   # real run
```

The token needs `data.records:read` and `data.records:write` on the target base. On GitHub it is stored as the `AIRTABLE_TOKEN` Actions secret and never committed.

### Adding a company

1. Click "Apply" on any of its jobs and check where the link goes: `job-boards.greenhouse.io` (Greenhouse), `jobs.ashbyhq.com` (Ashby), `jobs.lever.co` (Lever), `jobs.smartrecruiters.com` (SmartRecruiters), `*.jobs.personio.de` (Personio).
2. The slug is the part after the domain, e.g. `braze` in `boards.greenhouse.io/braze/jobs/123`.
3. Check the board returns jobs:
   ```
   curl "https://boards-api.greenhouse.io/v1/boards/YOUR_SLUG/jobs" | python3 -c "import sys,json; print(len(json.load(sys.stdin).get('jobs',[])),'jobs')"
   ```
   Zero on a company that is visibly hiring means the slug is wrong.
4. Add it under `companies` in `config.yaml` and run `python run.py --dry-run`.

### Adding a title

Add it to a lane under `title_lanes` in `config.yaml`. Matching is case-insensitive substring, so "Growth Marketing Manager" also catches "Senior Growth Marketing Manager, EMEA".

### Reading a failed run

Check the Actions tab for the run's log (look for `WARNING` and `ERROR` lines), then the Run Log table in Airtable, where every source has a row and failures carry the error in Notes. An **Empty** outcome usually means a wrong slug or a company that changed ATS.
