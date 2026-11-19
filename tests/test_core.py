import json
import os
from pathlib import Path

import httpx
import pytest

from nl2sql import llm as llm_mod
from nl2sql.config import LLMSettings, load_settings
from nl2sql.data import _allocate, extract_tables
from nl2sql.pipeline import extract_sql
from nl2sql.report import bootstrap_ci, sign_test_p
from nl2sql.retrieval import Bm25Index, _parse_table_list, fk_expand
from nl2sql.selftest import build_fixture, run_selftest
from nl2sql.sqlexec import results_match, run_sql

ROOT = Path(__file__).resolve().parents[1]


def test_results_match_variants():
    assert results_match([(1, "a"), (2, "b")], [(2, "b"), (1, "a")])
    assert not results_match([(1, "a"), (2, "b")], [(2, "b"), (1, "a")], order_matters=True)
    assert results_match([("a", 1)], [(1, "a")])            # column permutation
    assert results_match([(1.0000001,)], [(1,)])            # float tolerance
    assert not results_match([(1,)], [(1,), (1,)])
    assert not results_match(None, [(1,)])


def test_extract_helpers():
    assert extract_sql("Here:\n```sql\nSELECT 1;\n```") == "SELECT 1"
    assert extract_sql("SELECT a FROM t") == "SELECT a FROM t"
    assert extract_tables("SELECT * FROM A AS x JOIN b ON x.i=b.i WHERE z IN (SELECT z FROM c)", ["a", "B", "c", "d"]) == ["a", "B", "c"]
    assert _parse_table_list('sure! {"tables": ["Book", "nope", "author"]}', ["book", "author"]) == ["book", "author"]
    assert _parse_table_list("garbage", ["a"]) == []


def test_allocate_sums_and_respects_availability():
    a = _allocate(50, {1: .3, 2: .4, 3: .3}, {1: 5, 2: 100, 3: 100})
    assert sum(a.values()) == 50 and a[1] == 5


def test_bm25_ranks_relevant_table_first():
    idx = Bm25Index({"singer": "table singer. columns: name, age", "concert": "table concert. columns: venue, year"})
    s = idx.scores("which singers are older than 30")
    assert s["singer"] > s["concert"]


def test_stats_helpers():
    assert sign_test_p(0, 0) == 1.0 and sign_test_p(10, 0) < 0.01 and sign_test_p(5, 5) == 1.0
    lo, hi = bootstrap_ci([1.0] * 5 + [0.0] * 5)
    assert 0.1 < lo < 0.5 < hi < 0.9


def test_run_sql_is_read_only(tmp_path):
    build_fixture(tmp_path / "s")
    db = tmp_path / "s" / "database" / "uni" / "uni.sqlite"
    assert run_sql(db, "SELECT count(*) FROM country")[0]
    assert not run_sql(db, "DELETE FROM country")[0]
    assert not run_sql(db, "SELECT * FROM nope")[0]


def test_fk_expand_adds_bridge(tmp_path):
    from nl2sql.data import load_schema
    build_fixture(tmp_path / "s")
    schema = load_schema(tmp_path / "s", "uni")
    tables, added = fk_expand(["student", "course"], schema, "bridge", 3)
    assert "enrollment" in added
    tables, added = fk_expand(["student"], schema, "bridge", 3)
    assert added == []  # nothing bridges a single table


def test_config_validation(tmp_path):
    s = load_settings(ROOT / "config.yaml")
    assert len(s.configs) == 9 and s.configs["all_combined"].fk_expand
    bad = tmp_path / "c.yaml"
    bad.write_text("configs:\n  x: {retriever: full, rerank: true}\n")
    with pytest.raises(ValueError):
        load_settings(bad)
    bad.write_text("configs:\n  x: {retriever: vector, kk: 3}\n")
    with pytest.raises(ValueError):
        load_settings(bad)


def test_rate_limiter_waits():
    t = [0.0]; sleeps = []
    def sleep(x): sleeps.append(x); t[0] += x
    rl = llm_mod.RateLimiter(rpm=2, tpm=10_000, sleep=sleep, now=lambda: t[0])
    for _ in range(3):
        rl.acquire(10)
    assert sleeps and sum(sleeps) >= 59


def test_parse_duration():
    assert llm_mod.parse_duration("1m23.4s") == pytest.approx(83.4)
    assert llm_mod.parse_duration("2h5m") == 7500
    assert llm_mod.parse_duration("250ms") == pytest.approx(0.25)


def _fake_groq_client(groq, script):
    class Comp:
        def create(self, **kw):
            item = script.pop(0)
            if isinstance(item, Exception):
                raise item
            return item
    class Chat: completions = Comp()
    class C: chat = Chat()
    return C()


def test_groq_client_retries_then_caches_and_stops_on_daily_cap(tmp_path, monkeypatch):
    import groq
    from types import SimpleNamespace as NS
    monkeypatch.setenv("GROQ_API_KEY", "x")
    req = httpx.Request("POST", "http://x")
    rate = lambda ra: groq.RateLimitError("rl", response=httpx.Response(429, headers={"retry-after": ra}, request=req), body=None)
    ok = NS(choices=[NS(message=NS(content="hi"))], usage=NS(prompt_tokens=3, completion_tokens=1))
    monkeypatch.setattr(llm_mod.time, "sleep", lambda s: None)
    cache = llm_mod.Cache(tmp_path / "c.sqlite")
    g = llm_mod.GroqLLM(LLMSettings(rpm=1000, tpm=10**9, max_wait_seconds=60), cache)
    g.client = _fake_groq_client(groq, [rate("1"), ok])
    r = g.chat([{"role": "user", "content": "q"}])
    assert r.text == "hi" and not r.cached
    assert g.chat([{"role": "user", "content": "q"}]).cached          # served from cache, script is empty
    g.client = _fake_groq_client(groq, [rate("7200")])
    with pytest.raises(llm_mod.RateLimitExhausted):
        g.chat([{"role": "user", "content": "other"}])


def test_end_to_end_selftest(tmp_path):
    p = run_selftest(tmp_path / "st", log=lambda *a: None)
    text = p.read_text(encoding="utf-8")
    assert "Summary" in text and "all_combined" in text and "Per-question matrix" in text