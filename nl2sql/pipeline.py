"""LangGraph NL2SQL pipeline. The graph topology is built from the RunConfig:

    retrieve_tables -> [rerank_tables] -> [expand_fk] -> generate_sql -> execute_sql
                                                                           |
        (only when max_retries > 0)   ok? --yes--> [judge_result] --accepts--> finalize_sql -> END
                                       |                 |
                                       no            rejects
                                       v                 v
                                    retry_sql <----------+        (retry_sql -> execute_sql, up to max_retries times)
"""
from __future__ import annotations

import dataclasses
import re
import time
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from .config import RunConfig
from .data import Schema
from .prompts import FIX_USER, GEN_SYSTEM, GEN_USER
from .retrieval import SchemaRetriever, fk_expand, llm_rerank
from .retry import feedback_text, judge_answer
from .sqlexec import run_sql


class PipeState(TypedDict, total=False):
    question: str
    candidates: list      # retrieval output (before rerank)
    tables: list          # current table selection
    tables_initial: list  # selection used for the first attempt (retrieval quality is measured on this)
    fk_added: list
    rerank_fallback: bool
    schema_text: str
    raw_sql: str
    sql: str
    exec_ok: bool
    rows: list
    error: str
    usage: dict
    timings: dict
    # --- retry loop ---
    attempts: int         # retries used so far
    first_sql: str
    first_exec_ok: bool
    first_rows: list
    best: dict            # latest attempt that ran fine (sql/raw/rows) - used if later attempts get worse
    judge_ok: bool
    judge_reason: str
    judge_log: list
    retry_log: list
    chose_earlier: bool


def _usage0() -> dict:
    return {"prompt_tokens": 0, "completion_tokens": 0, "llm_calls": 0, "llm_seconds": 0.0}


def _add_usage(state: PipeState, res) -> dict:
    u = dict(state.get("usage") or _usage0())
    u["prompt_tokens"] += res.prompt_tokens
    u["completion_tokens"] += res.completion_tokens
    u["llm_calls"] += 1
    u["llm_seconds"] += res.latency
    return u


def extract_sql(text: str) -> str:
    m = re.search(r"```(?:sql|sqlite)?\s*(.*?)```", text or "", re.S | re.I)
    sql = (m.group(1) if m else (text or "")).strip()
    return sql.rstrip(";").strip()


class Pipeline:
    def __init__(self, rc: RunConfig, schema: Schema, llm, model: str | None = None, exec_timeout: float = 15.0,
                 log=print, generate: bool = True):
        self.rc, self.schema, self.llm = rc, schema, llm
        self.model = rc.model or model
        self.exec_timeout = exec_timeout
        self.log = log
        self.retriever = SchemaRetriever(schema, rc, llm, log)
        self.generate = generate
        self.retry_on = generate and rc.max_retries > 0
        # the retry step re-retrieves with HYBRID search (+ rerank) by default, whatever the base retriever is
        self.retry_retriever = None
        if self.retry_on and rc.retry_schema == "hybrid_rerank":
            self.retry_retriever = (self.retriever if rc.retriever == "hybrid"
                                    else SchemaRetriever(schema, dataclasses.replace(rc, retriever="hybrid"), llm, log))
        self.graph = self._build()

    @property
    def embedder_used(self) -> str:
        used = self.retriever.embedder_used
        if self.retry_retriever is not None and self.retry_retriever is not self.retriever:
            used = f"{used}; retry: {self.retry_retriever.embedder_used}"
        return used

    # ---- helpers -----------------------------------------------------------
    def _timed(self, state, key, t0):
        tm = dict(state.get("timings") or {})
        tm[key] = round(time.monotonic() - t0, 4) + tm.get(key, 0.0)
        return tm

    def _good(self, ok: bool, rows: list) -> bool:
        """Did this attempt produce an acceptable-looking result (before the judge)?"""
        return bool(ok and (rows or not self.rc.retry_on_empty))

    # ---- nodes -------------------------------------------------------------
    def _retrieve(self, state: PipeState) -> dict:
        t0 = time.monotonic()
        rc = self.rc
        ranked = [n for n, _ in self.retriever.rank(state["question"])]
        if rc.retriever == "full":
            cands = ranked
        else:
            cands = ranked[: (rc.candidates_k if rc.rerank else rc.k)]
        return {"candidates": cands, "tables": list(cands), "fk_added": [],
                "usage": state.get("usage") or _usage0(), "timings": self._timed(state, "retrieve", t0)}

    def _rerank(self, state: PipeState) -> dict:
        t0 = time.monotonic()
        picked, res, fell_back = llm_rerank(state["question"], state["candidates"], self.schema, self.llm, self.rc.k)
        return {"tables": picked, "rerank_fallback": fell_back, "usage": _add_usage(state, res),
                "timings": self._timed(state, "rerank", t0)}

    def _expand(self, state: PipeState) -> dict:
        t0 = time.monotonic()
        rc = self.rc
        tables, added = fk_expand(state["tables"], self.schema, rc.fk_mode, rc.fk_max_added, rc.fk_infer_shared_id)
        return {"tables": tables, "fk_added": added, "timings": self._timed(state, "fk_expand", t0)}

    def _generate(self, state: PipeState) -> dict:
        t0 = time.monotonic()
        schema_text = self.schema.ddl(state["tables"])
        msgs = [
            {"role": "system", "content": GEN_SYSTEM},
            {"role": "user", "content": GEN_USER.format(schema=schema_text, question=state["question"])},
        ]
        res = self.llm.chat(msgs, model=self.model)
        return {"schema_text": schema_text, "raw_sql": res.text, "sql": extract_sql(res.text),
                "attempts": 0, "tables_initial": list(state["tables"]), "retry_log": [], "judge_log": [],
                "usage": _add_usage(state, res), "timings": self._timed(state, "generate", t0)}

    def _execute(self, state: PipeState) -> dict:
        t0 = time.monotonic()
        ok, rows, err = run_sql(self.schema.db_path, state["sql"], self.exec_timeout)
        rows = rows or []
        out = {"exec_ok": ok, "rows": rows, "error": err or "", "timings": self._timed(state, "execute", t0)}
        if state.get("attempts", 0) == 0:  # remember the first attempt so we can measure what the loop gained
            out.update(first_sql=state["sql"], first_exec_ok=ok, first_rows=rows)
        if self._good(ok, rows):
            out["best"] = {"sql": state["sql"], "raw": state.get("raw_sql", ""), "rows": rows}
        return out

    # ---- retry loop --------------------------------------------------------
    def _after_execute(self, state: PipeState) -> str:
        can_retry = state.get("attempts", 0) < self.rc.max_retries
        if not self._good(state["exec_ok"], state["rows"]):
            return "retry_sql" if can_retry else "finalize_sql"
        if can_retry and self.rc.retry_judge:
            return "judge_result"
        return "finalize_sql"

    def _judge(self, state: PipeState) -> dict:
        t0 = time.monotonic()
        ok, reason, res = judge_answer(self.llm, state["question"], state["sql"], state["rows"],
                                       self.rc.judge_rows, self.model)
        log = list(state.get("judge_log") or [])
        log.append({"attempt": state.get("attempts", 0), "ok": ok, "reason": reason})
        return {"judge_ok": ok, "judge_reason": reason, "judge_log": log, "usage": _add_usage(state, res),
                "timings": self._timed(state, "judge", t0)}

    def _after_judge(self, state: PipeState) -> str:
        return "finalize_sql" if state.get("judge_ok", True) else "retry_sql"

    def _retry_schema(self, state: PipeState, n: int, feedback: str):
        """Choose the table set for retry number n. Returns (tables, mode, usage)."""
        rc, schema = self.rc, self.schema
        tables = list(state["tables"])
        usage = state.get("usage") or _usage0()
        if set(tables) >= set(schema.names):          # already the full schema (e.g. full_schema config): nothing to widen
            return tables, "same", usage
        if rc.retry_full_schema_last and n == rc.max_retries:
            return list(schema.names), "full_schema", usage          # last chance: show everything
        if rc.retry_schema == "neighbors":
            widened, _ = fk_expand(tables, schema, "neighbors", rc.fk_max_added, rc.fk_infer_shared_id)
            return widened, "neighbors", usage
        if rc.retry_schema == "hybrid_rerank":
            q = f"{state['question']}\n(Problem with the previous attempt: {feedback})"
            ranked = [t for t, _ in self.retry_retriever.rank(q)]
            picked, res, _fb = llm_rerank(q, ranked[: rc.candidates_k], schema, self.llm, rc.k)
            usage = _add_usage(state, res)
            merged = tables + [t for t in picked if t not in tables]   # never drop what the first attempt already had
            if rc.fk_expand:
                merged, _ = fk_expand(merged, schema, rc.fk_mode, rc.fk_max_added, rc.fk_infer_shared_id)
            return merged, "hybrid_rerank", usage
        return tables, "same", usage

    def _retry(self, state: PipeState) -> dict:
        t0 = time.monotonic()
        rc = self.rc
        n = state.get("attempts", 0) + 1
        if not state["exec_ok"]:
            kind = "error"
        elif not state["rows"] and rc.retry_on_empty:
            kind = "empty"
        else:
            kind = "judge"
        feedback = feedback_text(kind, state.get("error", ""), state.get("judge_reason", ""))
        tables, mode, usage = self._retry_schema(state, n, feedback)
        schema_text = self.schema.ddl(tables)
        msgs = [
            {"role": "system", "content": GEN_SYSTEM},
            {"role": "user", "content": GEN_USER.format(schema=schema_text, question=state["question"])},
            {"role": "assistant", "content": state.get("raw_sql", "")},
            {"role": "user", "content": FIX_USER.format(reason=feedback)},
        ]
        res = self.llm.chat(msgs, model=self.model)
        log = list(state.get("retry_log") or [])
        log.append({"n": n, "kind": kind, "schema_mode": mode, "n_tables": len(tables),
                    "added": [t for t in tables if t not in state["tables"]], "feedback": feedback[:200]})
        return {"tables": tables, "schema_text": schema_text, "raw_sql": res.text, "sql": extract_sql(res.text),
                "attempts": n, "retry_log": log, "usage": _add_usage({**state, "usage": usage}, res),
                "timings": self._timed(state, "retry", t0)}

    def _finalize(self, state: PipeState) -> dict:
        """If the last attempt is unusable but an earlier one ran fine, answer with that earlier one."""
        best = state.get("best")
        if best and not self._good(state["exec_ok"], state["rows"]):
            return {"sql": best["sql"], "raw_sql": best["raw"], "rows": best["rows"], "exec_ok": True, "error": "",
                    "chose_earlier": True}
        return {}

    # ---- graph -------------------------------------------------------------
    def _build(self):
        steps = [("retrieve_tables", self._retrieve)]
        if self.rc.rerank:
            steps.append(("rerank_tables", self._rerank))
        if self.rc.fk_expand:
            steps.append(("expand_fk", self._expand))
        if self.generate:
            steps += [("generate_sql", self._generate), ("execute_sql", self._execute)]
        self.step_names = [n for n, _ in steps]
        g = StateGraph(PipeState)
        for name, fn in steps:
            g.add_node(name, fn)
        g.add_edge(START, steps[0][0])
        for (a, _), (b, _) in zip(steps, steps[1:]):
            g.add_edge(a, b)
        if self.retry_on:
            g.add_node("retry_sql", self._retry)
            g.add_node("finalize_sql", self._finalize)
            routes = {"retry_sql": "retry_sql", "finalize_sql": "finalize_sql"}
            if self.rc.retry_judge:
                g.add_node("judge_result", self._judge)
                routes["judge_result"] = "judge_result"
                g.add_conditional_edges("judge_result", self._after_judge,
                                        {"retry_sql": "retry_sql", "finalize_sql": "finalize_sql"})
            g.add_conditional_edges("execute_sql", self._after_execute, routes)
            g.add_edge("retry_sql", "execute_sql")
            g.add_edge("finalize_sql", END)
        else:
            g.add_edge(steps[-1][0], END)
        return g.compile()

    def run(self, question: str) -> dict:
        cfg = {"recursion_limit": 30 + 4 * self.rc.max_retries}
        state = self.graph.invoke({"question": question, "usage": _usage0()}, cfg)
        if not self.generate:  # retrieval-only: make sure the schema is rendered for display
            state["schema_text"] = self.schema.ddl(state.get("tables", []))
        return state

    def describe(self) -> str:
        s = " -> ".join(self.step_names)
        if self.retry_on:
            s += f"  [loop: {'judge_result, ' if self.rc.retry_judge else ''}retry_sql x{self.rc.max_retries} max -> finalize_sql]"
        return s