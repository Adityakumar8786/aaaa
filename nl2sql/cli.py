"""Command line interface:  python -m nl2sql <command> [options]"""
from __future__ import annotations

import argparse
import dataclasses
import os
import sys
from pathlib import Path

from .config import DEFAULT_CONFIG_FILE, load_settings


def _load_env():
    try:
        from dotenv import load_dotenv

        load_dotenv(Path.cwd() / ".env")
        load_dotenv(Path(__file__).resolve().parents[1] / ".env")
    except ImportError:
        pass


def _make_llm(settings):
    from .llm import Cache, make_llm

    cache = Cache(settings.paths.cache_path) if settings.llm.use_cache else None
    return make_llm(settings.llm, cache)


def _targets(settings, args) -> list:
    if getattr(args, "all", False):
        return list(settings.configs)
    if not getattr(args, "config", None):
        sys.exit("Specify --config NAME (see `list-configs`) or --all")
    return [a for a in args.config]


def _derive(settings, names, args) -> list:
    """Apply --max-retries / --retry-schema / --no-judge: creates derived configs such as `hybrid+r2`
    (own result files, so the plain config's results are never overwritten)."""
    mr = getattr(args, "max_retries", None)
    rs = getattr(args, "retry_schema", None)
    nj = bool(getattr(args, "no_judge", False))
    if mr is None and rs is None and not nj:
        return names
    out = []
    for n in names:
        rc = settings.get(n)
        changes, parts = {}, []
        if mr is not None:
            changes["max_retries"] = mr
            parts.append(f"r{mr}")
        if rs:
            changes["retry_schema"] = rs
            parts.append(rs.replace("_", ""))
        if nj:
            changes["retry_judge"] = False
            parts.append("nojudge")
        if not (changes.get("max_retries", rc.max_retries)):
            sys.exit(f"error: --retry-schema / --no-judge need retries: add --max-retries N (config {n!r} has max_retries 0)")
        new = dataclasses.replace(rc, name=f"{n}+{'-'.join(parts)}", **changes)
        new.validate()
        settings.configs[new.name] = new
        out.append(new.name)
    return out


# ------------------------------------------------------------------ commands
def cmd_list(settings, args):
    print(f"{'config':<22} {'retriever':<9} {'k':<6} rerank  fk_expand  description")
    for n, rc in settings.configs.items():
        k = "all" if rc.retriever == "full" else (f"{rc.candidates_k}->{rc.k}" if rc.rerank else str(rc.k))
        print(f"{n:<22} {rc.retriever:<9} {k:<6} {str(rc.rerank):<7} {str(rc.fk_expand):<10} {rc.description}")


def cmd_check(settings, args):
    ok = True
    print(f"config file : {settings.config_file}")
    try:
        from .data import find_spider_files

        root = find_spider_files(settings.paths.spider_dir)
        print(f"spider dir  : OK ({root})")
    except FileNotFoundError as e:
        ok = False
        print(f"spider dir  : MISSING - {e}")
    prov = settings.llm.provider
    print(f"provider    : {prov}  (model {settings.llm.model})")
    if prov == "groq":
        print(f"GROQ_API_KEY: {'set' if os.environ.get('GROQ_API_KEY') else 'NOT SET (copy .env.example to .env)'}")
        ok &= bool(os.environ.get("GROQ_API_KEY"))
    else:
        from .llm import LLMError, OllamaLLM

        try:
            names = OllamaLLM(settings.llm).list_models()
            print(f"ollama      : reachable, {len(names)} model(s) installed (run `ollama-setup` to pull what is missing)")
        except LLMError as e:
            ok = False
            print(f"ollama      : NOT REACHABLE - {e}")
    for mod in ("langgraph", "groq", "sklearn", "sqlglot", "yaml", "numpy"):
        try:
            __import__(mod)
            print(f"import {mod:<9}: OK")
        except ImportError:
            ok = False
            print(f"import {mod:<9}: MISSING (pip install -r requirements.txt)")
    from .data import gold_path

    print(f"gold set    : {'present' if gold_path(settings).exists() else 'not built yet (run `prepare`)'}")
    if args.ping and ok:
        llm = _make_llm(settings)
        try:
            r = llm.chat([{"role": "user", "content": "Reply with the single word: pong"}], max_tokens=8)
            print(f"chat ping   : OK ({settings.llm.model}) -> {r.text.strip()!r}")
        except Exception as e:  # noqa: BLE001
            ok = False
            print(f"chat ping   : FAILED ({type(e).__name__}: {str(e)[:200]})")
        first = settings.configs[next(iter(settings.configs))]
        try:
            llm.embed(["ping"], first.embedder_model)
            print(f"embed ping  : OK ({first.embedder_model} via {prov})")
        except Exception as e:  # noqa: BLE001
            print(f"embed ping  : FAILED ({type(e).__name__}: {str(e)[:150]}) -> vector search will use the fallback embedder")
    sys.exit(0 if ok else 1)


def cmd_prepare(settings, args):
    from .data import build_gold, list_candidate_dbs

    if args.list_dbs:
        for c in list_candidate_dbs(settings):
            print(f"{c['db_id']:<28} tables={c['n_tables']:<3} questions={c['n_questions']}")
        return
    build_gold(settings, args.db_id)


def _common(settings):
    from .data import load_gold, load_schema

    gold = load_gold(settings)
    schema = load_schema(settings.paths.spider_dir, gold.meta["db_id"])
    return gold, schema


def cmd_ask(settings, args):
    from .pipeline import Pipeline

    gold, schema = _common(settings)
    rc = settings.get(_derive(settings, [args.config], args)[0])
    pipe = Pipeline(rc, schema, _make_llm(settings), model=settings.llm.model, exec_timeout=settings.exec_timeout_s)
    question = args.question
    gq = None
    if question.startswith("q") and question[1:].isdigit():
        gq = next((q for q in gold.questions if q.qid == question), None)
        if gq:
            question = gq.question
    print(f"graph    : {pipe.describe()}\nquestion : {question}")
    st = pipe.run(question)
    print(f"tables   : {st['tables']}  (candidates: {st['candidates'][:12]}{'...' if len(st['candidates']) > 12 else ''})")
    if st.get("fk_added"):
        print(f"fk added : {st['fk_added']}")
    for r in st.get("retry_log", []):
        print(f"retry {r['n']}  : trigger={r['kind']}, schema={r['schema_mode']} ({r['n_tables']} tables, added {r['added']}) - {r['feedback']}")
    for j in st.get("judge_log", []):
        print(f"judge #{j['attempt']} : {'accepts' if j['ok'] else 'REJECTS'} - {j['reason']}")
    print(f"SQL      : {st['sql']}")
    print(f"executed : {'ok' if st['exec_ok'] else 'ERROR ' + st['error']}")
    for r in st.get("rows", [])[:8]:
        print("   ", r)
    if gq:
        print(f"gold SQL : {gq.gold_sql}\ngold tbl : {gq.gold_tables}")
    print(f"usage    : {st['usage']}")


def cmd_estimate(settings, args):
    """Token / request / time budget per config for the current gold set, WITHOUT calling the LLM."""
    from .prompts import GEN_SYSTEM, GEN_USER, RERANK_SYSTEM, RERANK_USER
    from .retrieval import SchemaRetriever, fk_expand

    gold, schema = _common(settings)
    try:
        llm = _make_llm(settings)
    except Exception:  # noqa: BLE001  (no key: fine unless a config uses Groq embeddings)
        llm = None
    est = lambda s: int(len(s) / 3.3)  # noqa: E731
    s = settings.llm
    if s.provider == "ollama":
        print(f"Local Ollama model {s.model} (no rate limits; speed depends on your hardware). {len(gold.questions)} questions\n")
    else:
        print(f"Model {s.model}; limits enforced client-side: {s.rpm} RPM, {s.tpm} TPM.  ({len(gold.questions)} questions)\n")
    print(f"{'config':<22} {'requests':>9} {'~tokens':>9} {'~min @TPM':>10}   avg prompt tok (generation)")
    tot_t = tot_r = 0
    for name, rc in settings.configs.items():
        ret = SchemaRetriever(schema, rc, llm, log=lambda *a: None)
        toks = reqs = 0
        gen_tok = []
        for q in gold.questions:
            ranked = [n for n, _ in ret.rank(q.question)]
            tables = ranked if rc.retriever == "full" else ranked[: rc.k]
            if rc.rerank:
                cand = ranked[: rc.candidates_k]
                prompt = RERANK_SYSTEM + RERANK_USER.format(question=q.question, k=rc.k,
                                                            candidates="\n".join("- " + schema.compact(c) for c in cand))
                toks += est(prompt) + 40
                reqs += 1
            if rc.fk_expand:
                tables, _ = fk_expand(tables, schema, rc.fk_mode, rc.fk_max_added, rc.fk_infer_shared_id)
            g = est(GEN_SYSTEM + GEN_USER.format(schema=schema.ddl(tables), question=q.question)) + 60
            gen_tok.append(g)
            toks += g
            reqs += 1
            if rc.max_retries:  # ASSUMPTIONS: judge call ~350 tokens; ~35% of questions need a retry of ~(g+150) tokens (+ rerank call)
                if rc.retry_judge:
                    toks += 350
                    reqs += 1
                toks += int(0.35 * (g + 150) * min(rc.max_retries, 2))
                reqs += 0.35 * min(rc.max_retries, 2) * (2 if rc.retry_schema == "hybrid_rerank" and rc.retriever != "full" else 1)
        tot_t += toks
        tot_r += reqs
        print(f"{name:<22} {reqs:>9.0f} {toks:>9,} {max(toks / s.tpm, reqs / s.rpm):>10.1f}   {sum(gen_tok) / len(gen_tok):,.0f}")
    print(f"{'TOTAL':<22} {tot_r:>9.0f} {tot_t:>9,} {max(tot_t / s.tpm, tot_r / s.rpm):>10.1f}")
    print("\n(retry configs: assumes a judge call per question and ~35% of questions needing a retry; real usage depends on the model.)")
    print("Compare TOTAL tokens with your daily token cap (free 8b: ~500K/day, free 70b: ~100K/day). "
          "Runs resume automatically, so a total above the cap just means it takes more than one day.")


def cmd_retrieval(settings, args):
    from .evaluate import retrieval_only

    gold, schema = _common(settings)
    llm = _make_llm(settings)
    print(f"{'config':<22} {'cand.recall':>11} {'recall':>8} {'precision':>10} {'all gold kept':>14} {'avg tables':>11}")
    for name in _targets(settings, args):
        rows = retrieval_only(settings, settings.get(name), gold, schema, llm, args.limit)
        n = len(rows)
        print(f"{name:<22} {sum(r['candidate_recall'] for r in rows) / n:>11.1%} {sum(r['table_recall'] for r in rows) / n:>8.1%} "
              f"{sum(r['table_precision'] for r in rows) / n:>10.1%} {sum(r['perfect_recall'] for r in rows) / n:>14.1%} "
              f"{sum(r['n_tables'] for r in rows) / n:>11.1f}")


def cmd_run(settings, args, results_dir=None, verbose=True):
    from .evaluate import run_config
    from .llm import RateLimitExhausted

    gold, schema = _common(settings)
    llm = _make_llm(settings)
    try:
        for name in _derive(settings, _targets(settings, args), args):
            run_config(settings, settings.get(name), gold, schema, llm, results_dir=results_dir,
                       limit=args.limit, fresh=args.fresh, verbose=verbose)
    except RateLimitExhausted:
        sys.exit(2)
    if results_dir is None and not args.no_report:
        from .report import write_report

        try:
            print(f"\nreport written -> {write_report(settings, gold)}")
        except RuntimeError as e:
            print(e)


def cmd_test(settings, args):
    """Smoke-test one config on a few questions; results go to results/_test and do not touch real results."""
    args.limit, args.fresh, args.no_report, args.all = args.questions, True, True, False
    args.config = [args.config]
    cmd_run(settings, args, results_dir=settings.paths.results_dir / "_test", verbose=True)


def cmd_report(settings, args):
    from .data import load_gold
    from .report import write_report

    print(f"report written -> {write_report(settings, load_gold(settings), args.out)}")


def cmd_ollama_setup(settings, args):
    from .ollama_setup import setup

    if settings.llm.provider != "ollama":
        print("note: this config has llm.provider = groq. Use the Ollama config:  python -m nl2sql -c config.ollama.yaml ollama-setup")
    sys.exit(0 if setup(settings, do_pull=not args.no_pull) else 1)


def cmd_selftest(settings, args):
    from .selftest import run_selftest

    run_selftest(Path(args.out))


# ------------------------------------------------------------------ parser
def _retry_opts(sp):
    sp.add_argument("--max-retries", type=int, metavar="N", help="turn on the error-fix loop with up to N retries (creates a derived config like hybrid+r2)")
    sp.add_argument("--retry-schema", choices=["none", "neighbors", "hybrid_rerank"], help="how the schema changes on a retry (default: hybrid_rerank)")
    sp.add_argument("--no-judge", action="store_true", help="retry only on SQL errors / empty results (no LLM judge)")


def main(argv=None):
    _load_env()
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            pass
    p = argparse.ArgumentParser(prog="python -m nl2sql", description="NL2SQL schema-retrieval benchmark (Spider + LangGraph + Groq)")
    p.add_argument("-c", "--config-file", default=DEFAULT_CONFIG_FILE, help="path to config.yaml")
    p.add_argument("--spider-dir", help="override paths.spider_dir")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("list-configs", help="show configurations defined in config.yaml"); s.set_defaults(fn=cmd_list)
    s = sub.add_parser("check", help="verify setup (deps, key, Spider path)"); s.add_argument("--ping", action="store_true", help="make a tiny live Groq call"); s.set_defaults(fn=cmd_check)
    s = sub.add_parser("prepare", help="pick the DB and build the gold question set")
    s.add_argument("--db-id"); s.add_argument("--list-dbs", action="store_true"); s.set_defaults(fn=cmd_prepare)

    s = sub.add_parser("ask", help="run ONE question through a config (text, or a gold id like q007)")
    s.add_argument("question"); s.add_argument("--config", required=True); _retry_opts(s); s.set_defaults(fn=cmd_ask)

    s = sub.add_parser("estimate", help="token/time budget for the whole benchmark (no LLM calls)"); s.set_defaults(fn=cmd_estimate)

    s = sub.add_parser("retrieval", help="retrieval-only metrics (no SQL generation; rerank configs use 1 LLM call/question)")
    s.add_argument("--config", action="append"); s.add_argument("--all", action="store_true"); s.add_argument("--limit", type=int); s.set_defaults(fn=cmd_retrieval)

    s = sub.add_parser("run", help="full evaluation of one or more configs (resumable)")
    s.add_argument("--config", action="append", help="config name (repeatable)"); s.add_argument("--all", action="store_true")
    s.add_argument("--limit", type=int, help="only the first N gold questions"); s.add_argument("--fresh", action="store_true", help="discard saved results first")
    s.add_argument("--no-report", action="store_true"); _retry_opts(s); s.set_defaults(fn=cmd_run)

    s = sub.add_parser("test", help="smoke-test one config on a few questions (isolated results)")
    s.add_argument("--config", required=True); s.add_argument("--questions", type=int, default=5, help="how many gold questions to run"); _retry_opts(s); s.set_defaults(fn=cmd_test)

    s = sub.add_parser("report", help="(re)generate report.md from saved results")
    s.add_argument("--out"); s.set_defaults(fn=cmd_report)

    s = sub.add_parser("ollama-setup", help="check the Ollama server, pull the models named in the config, smoke-test them")
    s.add_argument("--no-pull", action="store_true", help="only report missing models, do not download"); s.set_defaults(fn=cmd_ollama_setup)

    s = sub.add_parser("selftest", help="offline end-to-end check with synthetic data + mock LLM (no API key)")
    s.add_argument("--out", default="selftest_out"); s.set_defaults(fn=cmd_selftest)

    args = p.parse_args(argv)
    try:
        settings = load_settings(args.config_file, args.spider_dir)
        args.fn(settings, args)
    except (FileNotFoundError, KeyError, ValueError, RuntimeError) as e:
        sys.exit(f"error: {e}")


if __name__ == "__main__":
    main()