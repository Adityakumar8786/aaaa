"""Build report.md comparing all configurations that have results."""
from __future__ import annotations

import json
import math
import random
from datetime import datetime
from pathlib import Path

import yaml

from collections import Counter

from .config import RunConfig, Settings
from .data import Gold
from .evaluate import load_rows, result_paths

BUCKET_LABEL = {1: "1 table", 2: "2 tables", 3: "3+ tables"}


def bootstrap_ci(vals: list, n: int = 2000, seed: int = 0) -> tuple:
    if not vals:
        return (0.0, 0.0)
    rng = random.Random(seed)
    m = len(vals)
    means = sorted(sum(vals[rng.randrange(m)] for _ in range(m)) / m for _ in range(n))
    return means[int(0.025 * n)], means[int(0.975 * n) - 1]


def sign_test_p(wins: int, losses: int) -> float:
    """Two-sided exact binomial (sign) test on discordant pairs."""
    n = wins + losses
    if n == 0:
        return 1.0
    k = min(wins, losses)
    p = sum(math.comb(n, i) for i in range(k + 1)) / 2**n
    return min(1.0, 2 * p)


def _mean(xs):
    return sum(xs) / len(xs) if xs else 0.0


def _pct(x):
    return f"{100 * x:.1f}%"


def _failure(r: dict) -> str:
    if r["ex_correct"]:
        return "correct"
    if not r["perfect_recall"]:
        return "retrieval miss"
    if not r["exec_ok"]:
        return "SQL error"
    return "wrong result"


def build_report(settings: Settings, gold: Gold, title_note: str = "") -> str:
    names = list(settings.configs)
    # configs created at run time with --max-retries (e.g. "hybrid+r2") are not in config.yaml: pick them up from results/
    rcs = dict(settings.configs)
    for mp in sorted(Path(settings.paths.results_dir).glob("*.meta.json")):
        nm = mp.name[: -len(".meta.json")]
        if nm not in rcs and not nm.startswith("_"):
            try:
                rcs[nm] = RunConfig(**json.loads(mp.read_text())["run_config"])
                names.append(nm)
            except Exception:  # noqa: BLE001
                pass
    data = {n: load_rows(settings.paths.results_dir, n) for n in names}
    data = {n: r for n, r in data.items() if r}
    if not data:
        raise RuntimeError("No results found. Run `python -m nl2sql run --all` first.")
    metas = {}
    for n in data:
        mp = result_paths(settings.paths.results_dir, n)[1]
        metas[n] = json.loads(mp.read_text()) if mp.exists() else {}

    qid_sets = [{r["qid"] for r in rows} for rows in data.values()]
    common = set.intersection(*qid_sets)
    partial = any(len(s) < len(gold.questions) for s in qid_sets)
    by = {n: {r["qid"]: r for r in rows if r["qid"] in common} for n, rows in data.items()}
    order = [q.qid for q in gold.questions if q.qid in common]
    base = "full_schema" if "full_schema" in by else next(iter(by))
    m = gold.meta
    base_tokens = _mean([by[base][q]["prompt_tokens"] for q in order]) or 1

    L = []
    L.append("# NL2SQL schema-retrieval benchmark")
    if title_note:
        L.append(f"\n> **{title_note}**")
    L.append("")
    L.append(f"- **Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    L.append(f"- **Database:** `{m['db_id']}` ({m['n_tables']} tables) &nbsp;|&nbsp; **Questions:** {len(order)} "
             f"(buckets 1/2/3+ tables = {m['bucket_counts']['1']}/{m['bucket_counts']['2']}/{m['bucket_counts']['3']}, seed {m['seed']})")
    models = sorted({mm.get('model', '?') for mm in metas.values()})
    embs = sorted({mm.get('embedder_used', '-') for mm in metas.values() if mm.get('embedder_used', '-') != '-'})
    provs = sorted({mm.get('provider', 'groq') for mm in metas.values()})
    L.append(f"- **LLM:** {', '.join(models)} via {', '.join(p.capitalize() for p in provs)} (temperature {settings.llm.temperature}) &nbsp;|&nbsp; "
             f"**Embedder used:** {', '.join(embs) or 'n/a'}")
    L.append(f"- **Metric:** execution accuracy (EX) = predicted SQL returns the same result set as the gold SQL "
             f"(simplified Spider-style comparison)")
    if partial:
        L.append(f"- ⚠ **Partial results:** some configs have not finished; all numbers use the {len(order)} questions "
                 f"common to every config shown.")
    L.append("")

    # ---- summary
    L.append("## 1. Summary\n")
    L.append("| Config | EX accuracy | 95% CI | Table recall | All gold tables kept | Avg tables in prompt | Avg prompt tokens | Δ tokens vs baseline | LLM calls/q | LLM time/q |")
    L.append("|---|---|---|---|---|---|---|---|---|---|")
    summary = {}
    for n in by:
        rs = [by[n][q] for q in order]
        ex = [1.0 if r["ex_correct"] else 0.0 for r in rs]
        lo, hi = bootstrap_ci(ex)
        tok = _mean([r["prompt_tokens"] for r in rs])
        summary[n] = dict(ex=_mean(ex), tok=tok, rec=_mean([r["table_recall"] for r in rs]))
        L.append(f"| `{n}` | **{_pct(_mean(ex))}** | {_pct(lo)} – {_pct(hi)} | {_pct(_mean([r['table_recall'] for r in rs]))} | "
                 f"{_pct(_mean([1.0 if r['perfect_recall'] else 0.0 for r in rs]))} | {_mean([r['n_tables'] for r in rs]):.1f} | "
                 f"{tok:,.0f} | {(tok / base_tokens - 1) * 100:+.0f}% | {_mean([r['llm_calls'] for r in rs]):.1f} | "
                 f"{_mean([r['llm_seconds'] for r in rs]):.1f}s |")
    L.append("")
    best = max(summary, key=lambda n: (summary[n]["ex"], -summary[n]["tok"]))
    cheapest = min(summary, key=lambda n: summary[n]["tok"])
    L.append(f"**Highest EX:** `{best}` ({_pct(summary[best]['ex'])}). **Fewest prompt tokens:** `{cheapest}` "
             f"({summary[cheapest]['tok']:,.0f}/question).")
    L.append(f"\n_With only {len(order)} questions each EX figure has a wide confidence interval (see column 3); "
             f"treat gaps smaller than the CI as noise and check the paired test in §4._\n")

    # ---- retrieval quality
    L.append("## 2. Retrieval quality\n")
    L.append("| Config | Candidate-pool recall | Final table recall | Final table precision | Reranker fallbacks | FK tables added/q |")
    L.append("|---|---|---|---|---|---|")
    for n in by:
        rs = [by[n][q] for q in order]
        L.append(f"| `{n}` | {_pct(_mean([r['candidate_recall'] for r in rs]))} | {_pct(_mean([r['table_recall'] for r in rs]))} | "
                 f"{_pct(_mean([r['table_precision'] for r in rs]))} | {sum(r['rerank_fallback'] for r in rs)} | "
                 f"{_mean([len(r['fk_added']) for r in rs]):.2f} |")
    L.append("\n_Candidate-pool recall = share of gold tables in the retrieval output before reranking / FK expansion. "
             "Precision for `full_schema` is low by construction (every table is included)._\n")

    # ---- by bucket
    L.append("## 3. Accuracy by question complexity (number of gold tables)\n")
    bucks = sorted({by[base][q]["bucket"] for q in order})
    L.append("| Config | " + " | ".join(f"{BUCKET_LABEL[b]} (n={sum(1 for q in order if by[base][q]['bucket'] == b)})" for b in bucks) + " |")
    L.append("|---|" + "---|" * len(bucks))
    for n in by:
        cells = []
        for b in bucks:
            qs = [q for q in order if by[base][q]["bucket"] == b]
            cells.append(_pct(_mean([1.0 if by[n][q]["ex_correct"] else 0.0 for q in qs])))
        L.append(f"| `{n}` | " + " | ".join(cells) + " |")
    L.append("")

    # ---- paired
    L.append(f"## 4. Paired comparison against `{base}`\n")
    L.append("| Config | Better than baseline | Worse than baseline | Same | Sign-test p |")
    L.append("|---|---|---|---|---|")
    for n in by:
        if n == base:
            continue
        w = sum(1 for q in order if by[n][q]["ex_correct"] and not by[base][q]["ex_correct"])
        l = sum(1 for q in order if by[base][q]["ex_correct"] and not by[n][q]["ex_correct"])
        L.append(f"| `{n}` | {w} | {l} | {len(order) - w - l} | {sign_test_p(w, l):.3f} |")
    L.append("\n_\"Better\" = the question is answered correctly by the config but not by the baseline. p < 0.05 suggests a real difference._\n")

    # ---- failures
    L.append("## 5. Where do failures come from?\n")
    cats = ["correct", "retrieval miss", "SQL error", "wrong result"]
    L.append("| Config | " + " | ".join(cats) + " |")
    L.append("|---|" + "---|" * len(cats))
    for n in by:
        cnt = {c: 0 for c in cats}
        for q in order:
            cnt[_failure(by[n][q])] += 1
        L.append(f"| `{n}` | " + " | ".join(str(cnt[c]) for c in cats) + " |")
    L.append("\n_retrieval miss = at least one gold table was not in the prompt (generation could not have succeeded); "
             "SQL error = tables were present but the query failed to run; wrong result = it ran but returned different data._\n")

    # ---- config snapshot
    retry_names = [n for n in by if rcs[n].max_retries > 0]
    sec = 6
    if retry_names:
        sec = 7
        L.append("## 6. Error-fix loop impact\n")
        L.append("| Config | Max retries | EX first attempt | EX after loop | Fixed | Regressed | Needed a retry | Retry triggers: error / empty / judge | Judge false alarms | Full-schema fallback used → rescued | Kept an earlier attempt | LLM calls/q | Prompt tokens/q |")
        L.append("|---|---|---|---|---|---|---|---|---|---|---|---|---|")
        for n in retry_names:
            rs = [by[n][q] for q in order]
            first = [bool(r.get("first_attempt_correct")) for r in rs]
            fin = [bool(r["ex_correct"]) for r in rs]
            kinds = Counter(k for r in rs for k in r.get("retry_kinds", []))
            false_alarm = sum(1 for r in rs if r.get("first_attempt_correct") and r.get("retry_kinds", [""])[:1] == ["judge"])
            fb_used = sum(1 for r in rs if r.get("full_schema_fallback"))
            fb_ok = sum(1 for r in rs if r.get("full_schema_fallback") and r["ex_correct"] and not r.get("first_attempt_correct"))
            L.append(f"| `{n}` | {rcs[n].max_retries} | {_pct(_mean(first))} | **{_pct(_mean(fin))}** | "
                     f"{sum(1 for a, b in zip(first, fin) if b and not a)} | {sum(1 for a, b in zip(first, fin) if a and not b)} | "
                     f"{sum(1 for r in rs if r.get('n_retries', 0) > 0)} | {kinds['error']} / {kinds['empty']} / {kinds['judge']} | "
                     f"{false_alarm} | {fb_used} → {fb_ok} | {sum(1 for r in rs if r.get('chose_earlier_attempt'))} | "
                     f"{_mean([r['llm_calls'] for r in rs]):.1f} | {_mean([r['prompt_tokens'] for r in rs]):,.0f} |")
        L.append("\n_EX first attempt = the SQL before any feedback (identical to the same config without the loop). "
                 "**Fixed** = wrong → right thanks to the loop; **Regressed** = right → wrong (only possible when the LLM judge rejects a correct answer "
                 "and the retry is worse); **Judge false alarms** = first attempt was correct but the judge asked for a retry. "
                 "Retrieval metrics in §2 are measured on the first attempt's tables, before any retry widening._\n")
    L.append(f"## {sec}. Configurations compared\n")
    L.append("| Config | Description | Retriever | k | Rerank | FK expand | Retry loop |")
    L.append("|---|---|---|---|---|---|---|")
    for n in by:
        rc = rcs[n]
        k = "all" if rc.retriever == "full" else (f"{rc.candidates_k}→{rc.k}" if rc.rerank else str(rc.k))
        L.append(f"| `{n}` | {rc.description} | {rc.retriever} | {k} | {'yes' if rc.rerank else 'no'} | "
                 f"{('yes (' + rc.fk_mode + ')') if rc.fk_expand else 'no'} | "
                 f"{('max ' + str(rc.max_retries) + ', judge ' + ('on' if rc.retry_judge else 'off') + ', retry schema ' + rc.retry_schema + (', last retry = full schema' if rc.retry_full_schema_last else '')) if rc.max_retries else 'no'} |")
    L.append("\n<details><summary>Effective configuration used</summary>\n\n```yaml\n" +
             yaml.safe_dump(settings.raw, sort_keys=False, allow_unicode=True) + "\n```\n</details>\n")

    # ---- appendix
    L.append(f"## {sec + 1}. Per-question matrix\n")
    L.append("`✓` correct · `✗R` retrieval miss · `✗E` SQL error · `✗` wrong result\n")
    L.append("| Q | Tables needed | " + " | ".join(f"`{n}`" for n in by) + " |")
    L.append("|---|---|" + "---|" * len(by))
    sym = {"correct": "✓", "retrieval miss": "✗R", "SQL error": "✗E", "wrong result": "✗"}
    for q in order:
        r0 = by[base][q]
        L.append(f"| {q} | {r0['bucket'] if r0['bucket'] < 3 else '3+'} | " +
                 " | ".join(sym[_failure(by[n][q])] for n in by) + " |")
    L.append(f"\n## {sec + 2}. Caveats\n")
    L.append("- One database, so results show how retrieval behaves on **this** schema; they will not transfer blindly to other schemas.")
    L.append("- EX comparison is a simplified version of Spider's evaluator (row multiset, column-order insensitive, row order only when gold has ORDER BY).")
    L.append("- LLM output at temperature 0 is not guaranteed bit-identical across runs; responses are cached so re-running this benchmark reproduces these numbers exactly.")
    if "ollama" in provs:
        L.append("- Ollama runs: prompt-token figures are character-based estimates (~3.3 chars/token) because Ollama's own counter ignores prompt-cache hits; they are consistent across configs but not exact.")
    L.append("- The error-fix loop never sees the gold SQL or gold result. The LLM judge can wrongly reject a correct answer (see *Judge false alarms* / *Regressed* in the loop section).")
    L.append("- If the embeddings endpoint was unavailable the vector index fell back to TF-IDF (see *Embedder used* above); BM25 and TF-IDF are both lexical, which shrinks hybrid's advantage.")
    return "\n".join(L) + "\n"


def write_report(settings: Settings, gold: Gold, out: Path | None = None, title_note: str = "") -> Path:
    out = Path(out) if out else settings.paths.report_path
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(build_report(settings, gold, title_note), encoding="utf-8")
    return out