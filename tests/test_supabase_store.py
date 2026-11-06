"""Tests for reading from and writing to Supabase, with the database faked out."""
import pytest

from jobfetcher import runner, supabase_store
from jobfetcher.config import Company, Config, load_config
from jobfetcher.models import Job


class _FakeCursor:
    """Records every statement. Answers selects with `rows` and inserts with `returning`."""

    def __init__(self, conn):
        self.conn = conn
        self._result = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        self.conn.statements.append((sql, params))
        if sql.lstrip().lower().startswith("select"):
            self._result = list(self.conn.rows)
        elif "returning" in sql:
            # job_url is the 9th column; a URL in `conflicts` behaves like an existing row.
            url = params[supabase_store._JOB_COLUMNS.index("job_url")]
            self._result = [] if url in self.conn.conflicts else [(1,)]
        else:
            self._result = []

    def fetchall(self):
        return self._result

    def fetchone(self):
        return self._result[0] if self._result else None


class _FakeConn:
    def __init__(self, rows=(), conflicts=()):
        self.rows = rows
        self.conflicts = set(conflicts)
        self.statements = []
        self.closed = False

    def cursor(self):
        return _FakeCursor(self)

    def close(self):
        self.closed = True


@pytest.fixture
def fake_conn(monkeypatch):
    conn = _FakeConn()
    monkeypatch.setattr(supabase_store, "_conn", conn)
    yield conn
    monkeypatch.setattr(supabase_store, "_conn", None)


def _job(**kwargs):
    fields = dict(title="GTM Engineer", company="TestCo", url="https://Example.com/1")
    fields.update(kwargs)
    return Job(**fields)


class TestFetchExistingJobs:
    def test_reads_every_row_lowercased(self, fake_conn):
        fake_conn.rows = [
            ("https://Example.com/job/1", "TestCo", "GTM Engineer"),
            (None, "Other Co", "CRM Executive"),
            ("https://example.com/job/2", None, None),
        ]
        urls, company_titles = supabase_store.fetch_existing_jobs()
        assert urls == {"https://example.com/job/1", "https://example.com/job/2"}
        assert company_titles == {"testco|gtm engineer", "other co|crm executive"}


class TestInsertJobs:
    def test_counts_only_rows_actually_created(self, fake_conn):
        # A URL already in the table is skipped by the database, not overwritten,
        # and must not be counted as inserted.
        fake_conn.conflicts = {"https://example.com/dup"}
        jobs = [_job(url="https://example.com/new"), _job(url="https://example.com/dup", title="Other")]
        assert supabase_store.insert_jobs(jobs) == 1

    def test_row_is_tagged_and_keeps_structured_salary(self, fake_conn):
        job = _job(
            salary_text="£50,000 - £60,000", salary_min=50000, salary_max=60000,
            salary_currency="GBP", salary_interval="year", posted_date="2026-11-01",
            posted_date_kind="first_published", lane="GTM Engineering", match_score=30,
            raw={"id": 7},
        )
        supabase_store.insert_jobs([job], source="LinkedIn")
        sql, params = fake_conn.statements[-1]
        row = dict(zip(supabase_store._JOB_COLUMNS, params))

        assert "on conflict (job_url) do nothing" in sql
        assert row["pipeline"] == "claude"
        assert row["data_source"] == "job-fetch"
        assert row["source"] == "LinkedIn"
        assert row["job_label"] == "TestCo — GTM Engineer"
        assert row["job_url"] == "https://Example.com/1"
        assert (row["salary_min"], row["salary_max"], row["salary_currency"]) == (50000, 60000, "GBP")
        assert row["raw_blob"] == '{"id": 7}'
        assert row["status"] == "New"
        assert row["first_seen"] is not None


class TestInsertRunLog:
    def test_writes_one_tagged_row(self, fake_conn):
        supabase_store.insert_run_log("Braze", "ATS", "OK", 2, note="total: 10")
        sql, params = fake_conn.statements[-1]
        assert "jobhunt.run_log" in sql
        assert params[:3] == ["claude", "job-fetch", "Braze"]
        assert params[3] == "ATS"
        assert params[6:] == ["OK", 2, "total: 10"]


def test_close_closes_and_forgets_the_connection(fake_conn):
    supabase_store.close()
    assert fake_conn.closed is True
    assert supabase_store._conn is None


# ---------------------------------------------------------------------------
# The runner with storage set to Supabase
# ---------------------------------------------------------------------------

def _config(**kwargs):
    fields = dict(
        companies=[Company(name="TestCo", ats="greenhouse", slug="testco")],
        title_lanes={"Growth": ["Growth Marketing Manager"]},
        storage="supabase",
        supabase_db_url="postgresql://test",
    )
    fields.update(kwargs)
    return Config(**fields)


def _block_storage(monkeypatch):
    def must_not_call(*args, **kwargs):
        raise AssertionError("storage should not be called")

    for name in ("fetch_existing_jobs", "insert_jobs", "insert_run_log"):
        monkeypatch.setattr(supabase_store, name, must_not_call)
        monkeypatch.setattr(runner.airtable, name, must_not_call)


class TestRunnerWithSupabase:
    def test_missing_url_stops_before_any_request(self, monkeypatch):
        _block_storage(monkeypatch)
        summary = runner.run(_config(supabase_db_url=""))
        assert summary["aborted"] is True
        assert runner.exit_code(summary) == 1

    def test_airtable_ids_are_not_needed(self, monkeypatch):
        calls = []
        monkeypatch.setattr(supabase_store, "fetch_existing_jobs", lambda: calls.append("read") or (set(), set()))
        monkeypatch.setattr(supabase_store, "insert_run_log", lambda **kw: calls.append(kw["outcome"]))
        monkeypatch.setattr(runner, "ADAPTERS", {})  # no network: company fails as unknown ATS
        summary = runner.run(_config())
        assert summary["aborted"] is False
        assert calls == ["read", "Failed"]

    def test_dry_run_reads_but_never_writes(self, monkeypatch):
        reads = []

        def must_not_write(*args, **kwargs):
            raise AssertionError("a dry run must not write")

        monkeypatch.setattr(supabase_store, "fetch_existing_jobs", lambda: reads.append(1) or (set(), set()))
        monkeypatch.setattr(supabase_store, "insert_jobs", must_not_write)
        monkeypatch.setattr(supabase_store, "insert_run_log", must_not_write)
        monkeypatch.setattr(runner, "ADAPTERS", {})
        summary = runner.run(_config(), dry_run=True)
        assert reads == [1]
        assert summary["aborted"] is False

    def test_unreadable_database_writes_nothing_and_fails(self, monkeypatch):
        def broken_read():
            raise RuntimeError("password authentication failed")

        def must_not_write(*args, **kwargs):
            raise AssertionError("nothing should be written after a failed read")

        monkeypatch.setattr(supabase_store, "fetch_existing_jobs", broken_read)
        monkeypatch.setattr(supabase_store, "insert_jobs", must_not_write)
        monkeypatch.setattr(supabase_store, "insert_run_log", must_not_write)
        summary = runner.run(_config())
        assert summary["aborted"] is True
        assert runner.exit_code(summary) == 1

    def test_connection_is_closed_after_the_run(self, monkeypatch):
        closed = []
        monkeypatch.setattr(supabase_store, "close", lambda: closed.append(1))
        _block_storage(monkeypatch)
        runner.run(_config(supabase_db_url=""))
        assert closed == [1]


class TestStorageSetting:
    def _write(self, tmp_path, storage_line):
        path = tmp_path / "config.yaml"
        path.write_text(
            "{}companies:\n  - name: TestCo\n    ats: greenhouse\n    slug: testco\n"
            "title_lanes:\n  Growth: [Growth Marketing Manager]\n".format(storage_line)
        )
        return str(path)

    def test_defaults_to_airtable(self, tmp_path):
        assert load_config(self._write(tmp_path, "")).storage == "airtable"

    def test_reads_supabase_and_the_url_from_the_environment(self, tmp_path, monkeypatch):
        monkeypatch.setenv("SUPABASE_DB_URL", "postgresql://from-env")
        config = load_config(self._write(tmp_path, "storage: Supabase\n"))
        assert config.storage == "supabase"
        assert config.supabase_db_url == "postgresql://from-env"

    def test_rejects_unknown_storage(self, tmp_path):
        with pytest.raises(ValueError):
            load_config(self._write(tmp_path, "storage: notion\n"))
