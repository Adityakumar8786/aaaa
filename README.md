# NL2SQL schema-retrieval benchmark (Spider · LangGraph · Groq)

Compares **how the schema is shown to the LLM** on one large Spider database (>= 20 tables), using the **same 50 gold questions**
for every configuration:

| Config | What goes into the SQL-generation prompt |
|---|---|
| `full_schema` | every table (baseline) |
| `topk_vector` | top-k tables by vector similarity |
| `hybrid` | top-k by vector + BM25, fused with reciprocal-rank-fusion |
| `topk_vector_rerank` | vector top-15 candidates -> Groq LLM reranker keeps best k |
| `hybrid_rerank` | hybrid top-15 candidates -> Groq LLM reranker keeps best k |
| `all_combined` | hybrid -> LLM reranker -> foreign-key "bridge table" expansion |

No self-correction loop (as requested). Each configuration is a different **LangGraph** graph:
`retrieve_tables -> [rerank_tables] -> [expand_fk] -> generate_sql -> execute_sql`.

Metrics: execution accuracy (EX, with 95% bootstrap CI), table recall / precision, prompt tokens, LLM calls, latency,
paired comparison vs. baseline, and a failure breakdown (retrieval miss / SQL error / wrong result).

---

## 1. Setup

Requires Python 3.10+.

```bash
unzip nl2sql-bench.zip && cd nl2sql-bench
python -m venv .venv
source .venv/bin/activate            # Windows PowerShell:  .venv\Scripts\Activate.ps1
pip install -r requirements.txt

cp .env.example .env                 # Windows: copy .env.example .env
# edit .env and paste your free key from https://console.groq.com/keys
```

Put the Spider dataset in `./spider` (or point `paths.spider_dir` in `config.yaml`, or pass `--spider-dir`).
It must contain `tables.json`, `train_spider.json` and/or `dev.json`, and `database/<db_id>/<db_id>.sqlite`:

```
spider/
  tables.json
  train_spider.json   (train_others.json, dev.json are used too if present)
  database/baseball_1/baseball_1.sqlite ...
```

Verify the install:

```bash
python -m nl2sql selftest            # offline: synthetic DB + mock LLM, no API key, ~5 s
python -m nl2sql check --ping        # checks deps, key, Spider path and makes one tiny live Groq call
```

## 2. Run the benchmark

```bash
python -m nl2sql prepare             # pick the DB (>= 20 tables) + build the 50-question gold set -> data/gold.json
python -m nl2sql estimate            # token / time budget per config (no LLM calls). READ THIS before running.
python -m nl2sql run --all           # runs all 6 configs, then writes report.md
```

Runs are **resumable and cached**: if Groq's daily limit stops a run, it exits cleanly with progress saved; just run the same
command again later (the next day for free-tier daily caps). Finished questions are never re-billed.

### All commands

| Command | Purpose |
|---|---|
| `python -m nl2sql list-configs` | show every configuration in `config.yaml` |
| `python -m nl2sql prepare [--db-id X] [--list-dbs]` | choose DB and build the gold set (`--list-dbs` shows candidates with >= min_tables) |
| `python -m nl2sql estimate` | token / request / minute budget for the full benchmark |
| `python -m nl2sql ask "question or q007" --config hybrid_rerank` | run ONE question through one config; prints retrieved tables, SQL, rows, gold SQL |
| `python -m nl2sql retrieval --config hybrid --config topk_vector` | retrieval-only metrics (table recall etc.); `--all` for all. Cheap: only rerank configs call the LLM |
| `python -m nl2sql test --config all_combined [--questions 5]` | smoke-test one config on 5 questions; results isolated in `results/_test` |
| `python -m nl2sql run --config hybrid` | full run of one config (repeat `--config` for several) |
| `python -m nl2sql run --all [--limit 10] [--fresh]` | all configs; `--limit` = first N questions, `--fresh` = discard saved results |
| `python -m nl2sql report [--out path]` | regenerate `report.md` from saved results (also works with partial results) |
| `python -m nl2sql check [--ping]` | environment check |
| `python -m nl2sql selftest` | offline end-to-end test (writes `selftest_out/`) |

Global options go before the command: `python -m nl2sql -c other_config.yaml --spider-dir /data/spider run --all`.

Suggested first session: `check --ping` -> `prepare` -> `estimate` -> `test --config full_schema` -> `test --config all_combined` -> `run --all`.

## 3. The central config (`config.yaml`)

Everything is in one file: paths, dataset selection (`db_id`, `min_tables`, `n_questions`, `seed`, complexity mix), Groq model and
rate limits, shared `defaults` (k, candidates_k, embedder, BM25, fusion, FK expansion) and the `configs:` list. To add a
configuration, add an entry, e.g.:

```yaml
configs:
  hybrid_k5_weighted:
    description: Hybrid with k=5, weighted score fusion
    retriever: hybrid
    k: 5
    fusion: weighted
    alpha: 0.6
```

Any key from `defaults` can be overridden per config (including `model:` to use a different Groq model for just that config).
Typos in keys are rejected with a clear error. Changing a config (or the gold set) automatically invalidates its saved results.

## 4. Things you should know

* **Free-tier budget.** Default model is `llama-3.1-8b-instant` (free tier, at time of writing: 30 RPM, 6K TPM, ~500K tokens/day).
  `llama-3.3-70b-versatile` writes better SQL but only has ~100K tokens/day on the free tier, so the full benchmark would take about
  a week of daily quota. Use `estimate` to see your numbers; switch model in `config.yaml -> llm.model` (and set `tpm` to ~11000 for 70b).
  Limits change - check https://console.groq.com/settings/limits.
* **Vector search uses Groq embeddings** (`nomic-embed-text-v1_5`, via the Groq SDK's `embeddings` endpoint) as you asked. I could not
  test this endpoint live (no network access to Groq from where this was built), and I could not confirm it is enabled for every free
  account. If the call fails, the vector index **falls back to local TF-IDF char n-grams** (a loud warning is printed, and the report's
  header shows `Embedder used`). To forbid the fallback set `embedder_fallback: none`; to use a local model instead set
  `embedder_type: sentence_transformers` (`pip install sentence-transformers`). `check --ping` tells you which case you are in.
  BM25 and TF-IDF are both lexical, so with the fallback the hybrid-vs-vector gap will be small; real embeddings make that comparison meaningful.
* **Database choice.** `db_id: auto` picks the Spider database with >= 20 tables that has the most questions (`baseball_1` in the standard
  Spider release has 26 tables - run `prepare --list-dbs` to see what your copy offers). Questions are drawn from train + dev for that DB, gold SQL that
  fails or returns zero rows is dropped, and the 50 are sampled (seeded) with a 30/40/30 mix of 1 / 2 / 3+ table questions so retrieval is actually stressed.
  If fewer than 50 usable questions exist you get a warning and all of them are used.
* **Evaluation** is a simplified Spider-style execution match (row multiset, column order ignored, row order only when the gold SQL has `ORDER BY`),
  not the official test-suite evaluator. Gold tables for recall are parsed from the gold SQL with `sqlglot`.
* **50 questions is a small sample**: EX differences of a few points are noise. The report gives bootstrap CIs and a paired sign test for this reason.
* Tables are always rendered in original schema order (not retrieval order), so configs differ only in *which* tables are present.
* If your Spider copy lacks foreign-key metadata for a DB, `fk_infer_shared_id: true` also links tables that share `*_id` column names.

## 5. Project layout

```
config.yaml            central config (all configurations)
nl2sql/
  cli.py               CLI commands
  config.py            config loading / validation
  data.py              Spider loading, DB selection, gold-set sampling
  retrieval.py         BM25, vector index, hybrid fusion, LLM reranker, FK expansion
  pipeline.py          LangGraph graph (built per configuration)
  evaluate.py          per-question scoring, resumable runs
  report.py            report.md generator (CIs, paired test, failure analysis)
  llm.py               Groq client: rate limiter, retries, cache, embeddings
  sqlexec.py           read-only SQLite execution, result comparison
  selftest.py          offline synthetic fixture + mock LLM
tests/test_core.py     unit tests (python -m pytest -q)
data/gold.json         generated by `prepare`
results/<config>.jsonl per-question results (generated)
report.md              final comparison (generated)
```

## 6. Extending

* Self-correction later: in `pipeline.py` add a conditional edge from `execute_sql` back to `generate_sql` when `exec_ok` is false.
* New retriever: implement a scorer in `retrieval.py::SchemaRetriever.rank` and add its name to `RunConfig.validate`.
