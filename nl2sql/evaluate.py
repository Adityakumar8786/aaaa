"""Run one configuration over the gold set and persist per-question results."""
from __future__ import annotations

import json
import time
from dataclasses import asdict
from pathlib import Path

from .config import RunConfig, Settings, fingerprint
from .data import Gold, Schema
from .llm import RateLimitExhausted
from .pipeline import Pipeline
from .sqlexec import has_order_by, results_match, run_sql


def result_paths(results_dir: Path, name: str):
    return results_dir / f"{name}.jsonl", results_dir / f"{name}.meta.json"


def load_rows(results_dir: Path, name: str) -> list:
    rows_path, _ = result_paths(results_dir, name)
    if not rows_path.exists():
        return []
    return [json.loads(l) for l in rows_path.read_text(encoding="utf-8").splitlines() if l.strip()]


def score_row(q, state: dict, schema: Schema, timeout: float, generate: bool = True) -> dict:
    gold = set(q.gold_tables)
    final = list(state.get("tables_initial") or state.get("tables", []))  # retrieval quality is judged BEFORE any retry widening
    cands = list(state.get("candidates", []))
    hit = gold & set(final)
    row = {
        "qid": q.qid, "bucket": q.bucket, "question": q.question, "gold_sql": q.gold_sql,
        "gold_tables": q.gold_tables, "candidates": cands, "tables": final,
        "fk_added": state.get("fk_added", []), "rerank_fallback": bool(state.get("rerank_fallback", False)),
        "n_tables": len(final),
        "table_recall": len(hit) / len(gold) if gold else 1.0,
        "table_precision": len(hit) / len(final) if final else 0.0,
        "candidate_recall": len(gold & set(cands)) / len(gold) if gold else 1.0,
        "perfect_recall": gold <= set(final),
    }
    u = state.get("usage", {})
    row.update(prompt_tokens=u.get("prompt_tokens", 0), completion_tokens=u.get("completion_tokens", 0),
               llm_calls=u.get("llm_calls", 0), llm_seconds=round(u.get("llm_seconds", 0.0), 3))
    if generate:
        ok_g, gold_rows, _ = run_sql(schema.db_path, q.gold_sql, timeout)
        pred_ok = bool(state.get("exec_ok"))
        correct = pred_ok and ok_g and results_match(state.get("rows"), gold_rows, has_order_by(q.gold_sql))
        first_ok = bool(state.get("first_exec_ok", pred_ok))
        first_correct = first_ok and ok_g and results_match(state.get("first_rows", state.get("rows")), gold_rows,
                                                            has_order_by(q.gold_sql))
        rlog = state.get("retry_log", [])
        row.update(pred_sql=state.get("sql", ""), exec_ok=pred_ok, error=state.get("error", ""), ex_correct=bool(correct),
                   first_attempt_correct=bool(first_correct), n_retries=state.get("attempts", 0),
                   retry_log=rlog, retry_kinds=[r["kind"] for r in rlog],
                   full_schema_fallback=any(r["schema_mode"] == "full_schema" for r in rlog),
                   judge_calls=len(state.get("judge_log", [])),
                   judge_rejections=sum(1 for j in state.get("judge_log", []) if not j["ok"]),
                   chose_earlier_attempt=bool(state.get("chose_earlier", False)),
                   tables_final=list(state.get("tables", [])))
    return row


def run_config(settings: Settings, rc: RunConfig, gold: Gold, schema: Schema, llm, results_dir: Path | None = None,
               limit: int | None = None, fresh: bool = False, verbose: bool = True, log=print) -> list:
    results_dir = results_dir or settings.paths.results_dir
    results_dir.mkdir(parents=True, exist_ok=True)
    rows_path, meta_path = result_paths(results_dir, rc.name)
    fp = fingerprint(rc, settings.llm, gold.hash)

    if fresh and rows_path.exists():
        rows_path.unlink()
    existing = load_rows(results_dir, rc.name)
    if existing and meta_path.exists():
        if json.loads(meta_path.read_text()).get("fingerprint") != fp:
            log(f"[{rc.name}] config or gold set changed since the last run -> starting fresh")
            rows_path.unlink()
            existing = []
    done = {r["qid"] for r in existing}

    pipe = Pipeline(rc, schema, llm, model=settings.llm.model, exec_timeout=settings.exec_timeout_s, log=log)
    meta = {"fingerprint": fp, "config": rc.name, "model": rc.model or settings.llm.model, "provider": settings.llm.provider,
            "embedder_used": pipe.embedder_used, "run_config": asdict(rc), "graph": pipe.describe(), "gold_hash": gold.hash,
            "updated": time.strftime("%Y-%m-%d %H:%M:%S")}
    meta_path.write_text(json.dumps(meta, indent=2))

    qs = gold.questions[:limit] if limit else gold.questions
    log(f"[{rc.name}] graph: {pipe.describe()}   embedder: {pipe.embedder_used}   ({len(done)}/{len(qs)} already done)")
    rows = list(existing)
    try:
        for i, q in enumerate(qs, 1):
            if q.qid in done:
                continue
            state = pipe.run(q.question)
            row = score_row(q, state, schema, settings.exec_timeout_s)
            rows.append(row)
            with rows_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(row) + "\n")
            if verbose:
                mark = "OK " if row["ex_correct"] else ("ERR" if not row["exec_ok"] else "BAD")
                log(f"  [{i:>3}/{len(qs)}] {q.qid} {mark} tables={row['n_tables']:<2} recall={row['table_recall']:.2f} "
                    f"tok={row['prompt_tokens']:<5}")
    except RateLimitExhausted as e:
        log(f"\n[{rc.name}] STOPPED: {e}\n  {len(rows)}/{len(qs)} questions saved.")
        raise
    n = len(rows)
    acc = sum(r["ex_correct"] for r in rows) / n if n else 0.0
    log(f"[{rc.name}] done: EX={acc:.1%} over {n} questions")
    return rows


def retrieval_only(settings: Settings, rc: RunConfig, gold: Gold, schema: Schema, llm, limit=None, log=print) -> list:
    pipe = Pipeline(rc, schema, llm, model=settings.llm.model, exec_timeout=settings.exec_timeout_s, log=log, generate=False)
    rows = []
    for q in (gold.questions[:limit] if limit else gold.questions):
        rows.append(score_row(q, pipe.run(q.question), schema, settings.exec_timeout_s, generate=False))
    return rows