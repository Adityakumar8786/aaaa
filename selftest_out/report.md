# NL2SQL schema-retrieval benchmark

> **SELFTEST: synthetic data + mock LLM. Numbers are NOT meaningful.**

- **Generated:** 2026-11-19 10:27
- **Database:** `uni` (22 tables) &nbsp;|&nbsp; **Questions:** 40 (buckets 1/2/3+ tables = 12/16/12, seed 42)
- **LLM:** llama-3.1-8b-instant via Groq (temperature 0.0) &nbsp;|&nbsp; **Embedder used:** -; retry: tfidf_char, tfidf_char, tfidf_char; retry: tfidf_char
- **Metric:** execution accuracy (EX) = predicted SQL returns the same result set as the gold SQL (simplified Spider-style comparison)

## 1. Summary

| Config | EX accuracy | 95% CI | Table recall | All gold tables kept | Avg tables in prompt | Avg prompt tokens | Δ tokens vs baseline | LLM calls/q | LLM time/q |
|---|---|---|---|---|---|---|---|---|---|
| `full_schema` | **100.0%** | 100.0% – 100.0% | 100.0% | 100.0% | 22.0 | 1,228 | +0% | 2.0 | 0.0s |
| `topk_vector` | **100.0%** | 100.0% – 100.0% | 88.8% | 67.5% | 2.0 | 705 | -43% | 3.0 | 0.0s |
| `hybrid` | **100.0%** | 100.0% – 100.0% | 88.8% | 67.5% | 2.0 | 727 | -41% | 3.0 | 0.0s |
| `topk_vector_rerank` | **100.0%** | 100.0% – 100.0% | 88.8% | 67.5% | 2.0 | 868 | -29% | 4.0 | 0.0s |
| `hybrid_rerank` | **100.0%** | 100.0% – 100.0% | 88.8% | 67.5% | 2.0 | 886 | -28% | 4.0 | 0.0s |
| `all_combined` | **100.0%** | 100.0% – 100.0% | 88.8% | 67.5% | 3.5 | 986 | -20% | 4.0 | 0.0s |
| `full_schema_retry` | **100.0%** | 100.0% – 100.0% | 100.0% | 100.0% | 22.0 | 1,228 | +0% | 2.0 | 0.0s |
| `hybrid_retry` | **100.0%** | 100.0% – 100.0% | 88.8% | 67.5% | 2.0 | 727 | -41% | 3.0 | 0.0s |
| `all_combined_retry` | **100.0%** | 100.0% – 100.0% | 88.8% | 67.5% | 3.5 | 986 | -20% | 4.0 | 0.0s |

**Highest EX:** `topk_vector` (100.0%). **Fewest prompt tokens:** `topk_vector` (705/question).

_With only 40 questions each EX figure has a wide confidence interval (see column 3); treat gaps smaller than the CI as noise and check the paired test in §4._

## 2. Retrieval quality

| Config | Candidate-pool recall | Final table recall | Final table precision | Reranker fallbacks | FK tables added/q |
|---|---|---|---|---|---|
| `full_schema` | 100.0% | 100.0% | 9.1% | 0 | 0.00 |
| `topk_vector` | 88.8% | 88.8% | 83.8% | 0 | 0.00 |
| `hybrid` | 88.8% | 88.8% | 83.8% | 0 | 0.00 |
| `topk_vector_rerank` | 100.0% | 88.8% | 83.8% | 0 | 0.00 |
| `hybrid_rerank` | 100.0% | 88.8% | 83.8% | 0 | 0.00 |
| `all_combined` | 100.0% | 88.8% | 54.3% | 0 | 1.55 |
| `full_schema_retry` | 100.0% | 100.0% | 9.1% | 0 | 0.00 |
| `hybrid_retry` | 88.8% | 88.8% | 83.8% | 0 | 0.00 |
| `all_combined_retry` | 100.0% | 88.8% | 54.3% | 0 | 1.55 |

_Candidate-pool recall = share of gold tables in the retrieval output before reranking / FK expansion. Precision for `full_schema` is low by construction (every table is included)._

## 3. Accuracy by question complexity (number of gold tables)

| Config | 1 table (n=12) | 2 tables (n=16) | 3+ tables (n=12) |
|---|---|---|---|
| `full_schema` | 100.0% | 100.0% | 100.0% |
| `topk_vector` | 100.0% | 100.0% | 100.0% |
| `hybrid` | 100.0% | 100.0% | 100.0% |
| `topk_vector_rerank` | 100.0% | 100.0% | 100.0% |
| `hybrid_rerank` | 100.0% | 100.0% | 100.0% |
| `all_combined` | 100.0% | 100.0% | 100.0% |
| `full_schema_retry` | 100.0% | 100.0% | 100.0% |
| `hybrid_retry` | 100.0% | 100.0% | 100.0% |
| `all_combined_retry` | 100.0% | 100.0% | 100.0% |

## 4. Paired comparison against `full_schema`

| Config | Better than baseline | Worse than baseline | Same | Sign-test p |
|---|---|---|---|---|
| `topk_vector` | 0 | 0 | 40 | 1.000 |
| `hybrid` | 0 | 0 | 40 | 1.000 |
| `topk_vector_rerank` | 0 | 0 | 40 | 1.000 |
| `hybrid_rerank` | 0 | 0 | 40 | 1.000 |
| `all_combined` | 0 | 0 | 40 | 1.000 |
| `full_schema_retry` | 0 | 0 | 40 | 1.000 |
| `hybrid_retry` | 0 | 0 | 40 | 1.000 |
| `all_combined_retry` | 0 | 0 | 40 | 1.000 |

_"Better" = the question is answered correctly by the config but not by the baseline. p < 0.05 suggests a real difference._

## 5. Where do failures come from?

| Config | correct | retrieval miss | SQL error | wrong result |
|---|---|---|---|---|
| `full_schema` | 40 | 0 | 0 | 0 |
| `topk_vector` | 40 | 0 | 0 | 0 |
| `hybrid` | 40 | 0 | 0 | 0 |
| `topk_vector_rerank` | 40 | 0 | 0 | 0 |
| `hybrid_rerank` | 40 | 0 | 0 | 0 |
| `all_combined` | 40 | 0 | 0 | 0 |
| `full_schema_retry` | 40 | 0 | 0 | 0 |
| `hybrid_retry` | 40 | 0 | 0 | 0 |
| `all_combined_retry` | 40 | 0 | 0 | 0 |

_retrieval miss = at least one gold table was not in the prompt (generation could not have succeeded); SQL error = tables were present but the query failed to run; wrong result = it ran but returned different data._

## 6. Error-fix loop impact

| Config | Max retries | EX first attempt | EX after loop | Fixed | Regressed | Needed a retry | Retry triggers: error / empty / judge | Judge false alarms | Full-schema fallback used → rescued | Kept an earlier attempt | LLM calls/q | Prompt tokens/q |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `full_schema` | 2 | 100.0% | **100.0%** | 0 | 0 | 0 | 0 / 0 / 0 | 0 | 0 → 0 | 0 | 2.0 | 1,228 |
| `topk_vector` | 2 | 67.5% | **100.0%** | 13 | 0 | 13 | 11 / 0 / 14 | 0 | 12 → 12 | 0 | 3.0 | 705 |
| `hybrid` | 2 | 67.5% | **100.0%** | 13 | 0 | 13 | 12 / 0 / 14 | 0 | 13 → 13 | 0 | 3.0 | 727 |
| `topk_vector_rerank` | 2 | 67.5% | **100.0%** | 13 | 0 | 13 | 11 / 0 / 14 | 0 | 12 → 12 | 0 | 4.0 | 868 |
| `hybrid_rerank` | 2 | 67.5% | **100.0%** | 13 | 0 | 13 | 12 / 0 / 14 | 0 | 13 → 13 | 0 | 4.0 | 886 |
| `all_combined` | 2 | 67.5% | **100.0%** | 13 | 0 | 13 | 11 / 0 / 14 | 0 | 12 → 12 | 0 | 4.0 | 986 |
| `full_schema_retry` | 2 | 100.0% | **100.0%** | 0 | 0 | 0 | 0 / 0 / 0 | 0 | 0 → 0 | 0 | 2.0 | 1,228 |
| `hybrid_retry` | 2 | 67.5% | **100.0%** | 13 | 0 | 13 | 12 / 0 / 14 | 0 | 13 → 13 | 0 | 3.0 | 727 |
| `all_combined_retry` | 2 | 67.5% | **100.0%** | 13 | 0 | 13 | 11 / 0 / 14 | 0 | 12 → 12 | 0 | 4.0 | 986 |

_EX first attempt = the SQL before any feedback (identical to the same config without the loop). **Fixed** = wrong → right thanks to the loop; **Regressed** = right → wrong (only possible when the LLM judge rejects a correct answer and the retry is worse); **Judge false alarms** = first attempt was correct but the judge asked for a retry. Retrieval metrics in §2 are measured on the first attempt's tables, before any retry widening._

## 7. Configurations compared

| Config | Description | Retriever | k | Rerank | FK expand | Retry loop |
|---|---|---|---|---|---|---|
| `full_schema` | Baseline - the entire schema goes into the prompt | full | all | no | no | max 2, judge on, retry schema hybrid_rerank, last retry = full schema |
| `topk_vector` | Top-k tables by vector similarity | vector | 2 | no | no | max 2, judge on, retry schema hybrid_rerank, last retry = full schema |
| `hybrid` | Top-k tables by vector + BM25 (reciprocal rank fusion) | hybrid | 2 | no | no | max 2, judge on, retry schema hybrid_rerank, last retry = full schema |
| `topk_vector_rerank` | Vector top-N candidates -> LLM reranker keeps best k | vector | 6→2 | yes | no | max 2, judge on, retry schema hybrid_rerank, last retry = full schema |
| `hybrid_rerank` | Hybrid top-N candidates -> LLM reranker keeps best k | hybrid | 6→2 | yes | no | max 2, judge on, retry schema hybrid_rerank, last retry = full schema |
| `all_combined` | Hybrid -> LLM reranker -> FK bridge expansion | hybrid | 6→2 | yes | yes (bridge) | max 2, judge on, retry schema hybrid_rerank, last retry = full schema |
| `full_schema_retry` | full_schema + error-fix loop (2 retries) | full | all | no | no | max 2, judge on, retry schema hybrid_rerank, last retry = full schema |
| `hybrid_retry` | hybrid + error-fix loop (2 retries) | hybrid | 2 | no | no | max 2, judge on, retry schema hybrid_rerank, last retry = full schema |
| `all_combined_retry` | hybrid -> reranker -> FK expansion + error-fix loop (2 retries) | hybrid | 6→2 | yes | yes (bridge) | max 2, judge on, retry schema hybrid_rerank, last retry = full schema |

<details><summary>Effective configuration used</summary>

```yaml
paths:
  spider_dir: ./fake_spider
  data_dir: ./data
  results_dir: ./results
  cache_path: ./.cache/c.sqlite
  report_path: ./report.md
dataset:
  db_id: auto
  min_tables: 20
  n_questions: 40
  seed: 42
  question_files:
  - train_spider.json
  - train_others.json
  - dev.json
  bucket_mix:
    1: 0.3
    2: 0.4
    3: 0.3
  exclude_empty_gold: true
llm:
  model: llama-3.1-8b-instant
  temperature: 0.0
  max_tokens: 512
  rpm: 25
  tpm: 5500
  max_retries: 6
  max_wait_seconds: 90
  use_cache: true
execution:
  timeout_s: 15
defaults:
  k: 2
  candidates_k: 6
  embedder_type: tfidf_char
  embedder_model: nomic-embed-text-v1_5
  embedder_fallback: none
  bm25_k1: 1.5
  bm25_b: 0.75
  fusion: rrf
  rrf_k: 60
  alpha: 0.5
  max_retries: 2
  retry_on_empty: true
  retry_judge: true
  retry_schema: hybrid_rerank
  retry_full_schema_last: true
  judge_rows: 5
  fk_mode: bridge
  fk_max_added: 3
  fk_infer_shared_id: true
configs:
  full_schema:
    description: Baseline - the entire schema goes into the prompt
    retriever: full
  topk_vector:
    description: Top-k tables by vector similarity
    retriever: vector
  hybrid:
    description: Top-k tables by vector + BM25 (reciprocal rank fusion)
    retriever: hybrid
  topk_vector_rerank:
    description: Vector top-N candidates -> LLM reranker keeps best k
    retriever: vector
    rerank: true
  hybrid_rerank:
    description: Hybrid top-N candidates -> LLM reranker keeps best k
    retriever: hybrid
    rerank: true
  all_combined:
    description: Hybrid -> LLM reranker -> FK bridge expansion
    retriever: hybrid
    rerank: true
    fk_expand: true
  full_schema_retry:
    description: full_schema + error-fix loop (2 retries)
    retriever: full
    max_retries: 2
  hybrid_retry:
    description: hybrid + error-fix loop (2 retries)
    retriever: hybrid
    max_retries: 2
  all_combined_retry:
    description: hybrid -> reranker -> FK expansion + error-fix loop (2 retries)
    retriever: hybrid
    rerank: true
    fk_expand: true
    max_retries: 2

```
</details>

## 8. Per-question matrix

`✓` correct · `✗R` retrieval miss · `✗E` SQL error · `✗` wrong result

| Q | Tables needed | `full_schema` | `topk_vector` | `hybrid` | `topk_vector_rerank` | `hybrid_rerank` | `all_combined` | `full_schema_retry` | `hybrid_retry` | `all_combined_retry` |
|---|---|---|---|---|---|---|---|---|---|---|
| q001 | 2 | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| q002 | 3+ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| q003 | 1 | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| q004 | 3+ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| q005 | 2 | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| q006 | 2 | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| q007 | 1 | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| q008 | 1 | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| q009 | 3+ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| q010 | 2 | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| q011 | 1 | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| q012 | 2 | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| q013 | 2 | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| q014 | 3+ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| q015 | 1 | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| q016 | 1 | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| q017 | 2 | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| q018 | 3+ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| q019 | 1 | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| q020 | 3+ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| q021 | 2 | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| q022 | 2 | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| q023 | 2 | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| q024 | 3+ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| q025 | 3+ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| q026 | 1 | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| q027 | 2 | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| q028 | 2 | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| q029 | 1 | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| q030 | 3+ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| q031 | 1 | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| q032 | 2 | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| q033 | 3+ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| q034 | 1 | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| q035 | 3+ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| q036 | 1 | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| q037 | 2 | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| q038 | 2 | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| q039 | 3+ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| q040 | 2 | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |

## 9. Caveats

- One database, so results show how retrieval behaves on **this** schema; they will not transfer blindly to other schemas.
- EX comparison is a simplified version of Spider's evaluator (row multiset, column-order insensitive, row order only when gold has ORDER BY).
- LLM output at temperature 0 is not guaranteed bit-identical across runs; responses are cached so re-running this benchmark reproduces these numbers exactly.
- The error-fix loop never sees the gold SQL or gold result. The LLM judge can wrongly reject a correct answer (see *Judge false alarms* / *Regressed* in the loop section).
- If the embeddings endpoint was unavailable the vector index fell back to TF-IDF (see *Embedder used* above); BM25 and TF-IDF are both lexical, which shrinks hybrid's advantage.
