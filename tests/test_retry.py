import dataclasses
import json
from pathlib import Path

import pytest

from nl2sql.cli import _derive
from nl2sql.config import load_settings
from nl2sql.data import load_gold, load_schema, _load_questions
from nl2sql.evaluate import load_rows, run_config
from nl2sql.llm import LLMResult
from nl2sql.pipeline import Pipeline
from nl2sql.report import build_report
from nl2sql.retry import feedback_text, parse_verdict, preview_rows
from nl2sql.selftest import MockLLM, build_fixture, run_selftest

ROOT = Path(__file__).resolve().parents[1]


class Args:  # stand-in for argparse.Namespace
    def __init__(self, **kw):
        self.max_retries = self.retry_schema = None
        self.no_judge = False
        self.__dict__.update(kw)


@pytest.fixture(scope="module")
def env(tmp_path_factory):
    d = tmp_path_factory.mktemp("st")
    run_selftest(d, log=lambda *a: None)
    s = load_settings(d / "config.yaml")
    return s, load_gold(s), load_schema(s.paths.spider_dir, "uni")


class Script:
    """LLM that returns scripted replies in order and records the prompts."""
    def __init__(self, *replies):
        self.replies, self.prompts = list(replies), []

    def chat(self, messages, max_tokens=None, model=None):
        self.prompts.append(messages)
        return LLMResult(self.replies.pop(0), 10, 5, 0.0)


def _pipe(rc_changes, llm, tmp_path):
    s = load_settings(ROOT / "config.yaml")
    build_fixture(tmp_path / "s")
    schema = load_schema(tmp_path / "s", "uni")
    rc = dataclasses.replace(s.configs["topk_vector"], embedder_type="tfidf_char", k=2, **rc_changes)
    return Pipeline(rc, schema, llm)


def sql(s): return f"```sql\n{s}\n```"
Q = "How many country records are there?"
VERDICT_NO = json.dumps({"answers_question": False, "reason": "wrong columns"})
VERDICT_YES = json.dumps({"answers_question": True, "reason": "ok"})


def test_helpers():
    assert parse_verdict('x {"answers_question": false, "reason": "r"} y') == (False, "r")
    assert parse_verdict('{"answers_question": "true"}')[0] is True
    assert parse_verdict("no json at all")[0] is True              # noise never triggers a retry
    assert "(no rows)" == preview_rows([])
    assert "more rows" in preview_rows([(i,) for i in range(9)], 3)
    assert "error: boom" in feedback_text("error", "boom") and "no rows" in feedback_text("empty")


def test_graph_topology(tmp_path):
    base = dict(max_retries=0)
    assert "retry_sql" not in _pipe(base, Script(), tmp_path).describe()
    d = _pipe(dict(max_retries=2), Script(), tmp_path).describe()
    assert "retry_sql" in d and "judge_result" in d
    d = _pipe(dict(max_retries=2, retry_judge=False), Script(), tmp_path).describe()
    assert "retry_sql" in d and "judge_result" not in d


def test_judge_accepts_no_retry(tmp_path):
    llm = Script(sql("SELECT count(*) FROM country"), VERDICT_YES)
    st = _pipe(dict(max_retries=2), llm, tmp_path).run(Q)
    assert st["attempts"] == 0 and st["exec_ok"] and len(llm.prompts) == 2


def test_error_triggers_retry_with_feedback_and_full_schema_on_last(tmp_path):
    llm = Script(sql("SELECT * FROM nope"), sql("SELECT count(*) FROM country"))
    st = _pipe(dict(max_retries=1, retry_judge=False), llm, tmp_path).run(Q)
    assert st["attempts"] == 1 and st["exec_ok"] and st["sql"] == "SELECT count(*) FROM country"
    fix_prompt = llm.prompts[1]
    assert "no such table: nope" in fix_prompt[-1]["content"] and "SELECT * FROM nope" in fix_prompt[-2]["content"]
    assert st["retry_log"][0]["kind"] == "error" and st["retry_log"][0]["schema_mode"] == "full_schema"
    assert fix_prompt[1]["content"].count("CREATE TABLE") == 22        # last retry sees the whole schema


def test_empty_result_triggers_retry(tmp_path):
    llm = Script(sql("SELECT name FROM country WHERE 1=0"), sql("SELECT name FROM country"))
    st = _pipe(dict(max_retries=1, retry_judge=False), llm, tmp_path).run(Q)
    assert st["retry_log"][0]["kind"] == "empty" and st["rows"]
    st2 = _pipe(dict(max_retries=1, retry_judge=False, retry_on_empty=False), Script(sql("SELECT name FROM country WHERE 1=0")), tmp_path).run(Q)
    assert st2["attempts"] == 0                                       # empty accepted when retry_on_empty is off


def test_judge_rejection_then_error_keeps_earlier_attempt(tmp_path):
    llm = Script(sql("SELECT name FROM country"), VERDICT_NO, sql("SELECT * FROM nope"))
    st = _pipe(dict(max_retries=1), llm, tmp_path).run(Q)
    assert st["retry_log"][0]["kind"] == "judge"
    assert st["chose_earlier"] and st["exec_ok"] and st["sql"] == "SELECT name FROM country"


def test_retry_budget_is_respected(tmp_path):
    llm = Script(*([sql("SELECT * FROM nope")] * 6))
    st = _pipe(dict(max_retries=3, retry_judge=False, retry_schema="none"), llm, tmp_path).run(Q)
    assert st["attempts"] == 3 and len(llm.prompts) == 4 and not st["exec_ok"]
    assert [r["schema_mode"] for r in st["retry_log"]] == ["same", "same", "full_schema"]


def test_hybrid_rerank_retry_merges_tables_and_uses_feedback(env):
    s, gold, schema = env
    mock = MockLLM(_load_questions(s))
    rc = dataclasses.replace(s.configs["hybrid"], max_retries=2, retry_full_schema_last=False, k=3, candidates_k=8)
    pipe = Pipeline(rc, schema, mock)
    q = next(q for q in gold.questions if q.bucket == 3)
    st = pipe.run(q.question)
    assert set(st["tables_initial"]) <= set(st["tables"])             # retries only add tables
    for r in st["retry_log"]:
        assert r["schema_mode"] == "hybrid_rerank"


def test_selftest_loop_beats_plain_and_never_regresses(env):
    s, gold, schema = env
    plain, loop = load_rows(s.paths.results_dir, "hybrid"), load_rows(s.paths.results_dir, "hybrid_retry")
    acc = lambda rows, k: sum(r[k] for r in rows) / len(rows)
    assert acc(loop, "first_attempt_correct") == pytest.approx(acc(plain, "ex_correct"))
    assert acc(loop, "ex_correct") > acc(plain, "ex_correct")
    assert all(r["n_retries"] <= 2 for r in loop)
    assert all(r["first_attempt_correct"] <= r["ex_correct"] for r in loop)


def test_cli_override_creates_derived_config_and_report_lists_it(env):
    s, gold, schema = env
    names = _derive(s, ["hybrid"], Args(max_retries=1, no_judge=True))
    assert names == ["hybrid+r1-nojudge"]
    rc = s.configs[names[0]]
    assert rc.max_retries == 1 and not rc.retry_judge and s.configs["hybrid"].max_retries == 0
    mock = MockLLM(_load_questions(s))
    rows = run_config(s, rc, gold, schema, mock, verbose=False, log=lambda *a: None)
    assert mock.kinds["judge"] == 0 and all(r["n_retries"] <= 1 for r in rows)
    s2 = load_settings(s.config_file)                                    # fresh settings: derived config only known via results/
    text = build_report(s2, gold)
    assert "hybrid+r1-nojudge" in text and "Error-fix loop impact" in text
    with pytest.raises(SystemExit):
        _derive(s, ["hybrid"], Args(no_judge=True))                      # --no-judge without retries makes no sense


def test_config_validation():
    s = load_settings(ROOT / "config.yaml")
    assert s.configs["hybrid"].max_retries == 0 and s.configs["hybrid_retry"].max_retries == 2
    with pytest.raises(ValueError):
        dataclasses.replace(s.configs["hybrid"], max_retries=-1).validate()
    with pytest.raises(ValueError):
        dataclasses.replace(s.configs["hybrid"], retry_schema="bogus").validate()