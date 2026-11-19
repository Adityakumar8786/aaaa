# NL2SQL schema-retrieval benchmark

- **Generated:** 2026-11-19 11:08
- **Database:** `baseball_1` (26 tables) &nbsp;|&nbsp; **Questions:** 5 (buckets 1/2/3+ tables = 15/31/4, seed 42)
- **LLM:** qwen2.5-coder:7b via Ollama (temperature 0.0) &nbsp;|&nbsp; **Embedder used:** -; retry: ollama, ollama, ollama; retry: ollama
- **Metric:** execution accuracy (EX) = predicted SQL returns the same result set as the gold SQL (simplified Spider-style comparison)
- ⚠ **Partial results:** some configs have not finished; all numbers use the 5 questions common to every config shown.

## 1. Summary

| Config | EX accuracy | 95% CI | Table recall | All gold tables kept | Avg tables in prompt | Avg prompt tokens | Δ tokens vs baseline | LLM calls/q | LLM time/q |
|---|---|---|---|---|---|---|---|---|---|
| `full_schema` | **100.0%** | 100.0% – 100.0% | 100.0% | 100.0% | 26.0 | 2,591 | +0% | 2.0 | 44.4s |
| `topk_vector` | **100.0%** | 100.0% – 100.0% | 100.0% | 100.0% | 8.0 | 1,185 | -54% | 2.0 | 70.9s |
| `hybrid` | **100.0%** | 100.0% – 100.0% | 100.0% | 100.0% | 8.0 | 1,047 | -60% | 2.0 | 5.5s |
| `topk_vector_rerank` | **100.0%** | 100.0% – 100.0% | 100.0% | 100.0% | 2.8 | 1,385 | -47% | 3.0 | 7.0s |
| `hybrid_rerank` | **100.0%** | 100.0% – 100.0% | 100.0% | 100.0% | 2.8 | 1,301 | -50% | 3.0 | 5.7s |
| `all_combined` | **100.0%** | 100.0% – 100.0% | 100.0% | 100.0% | 3.0 | 1,318 | -49% | 3.0 | 5.8s |
| `full_schema_retry` | **100.0%** | 100.0% – 100.0% | 100.0% | 100.0% | 26.0 | 2,591 | +0% | 2.0 | 44.4s |
| `hybrid_retry` | **100.0%** | 100.0% – 100.0% | 100.0% | 100.0% | 8.0 | 1,047 | -60% | 2.0 | 5.5s |
| `all_combined_retry` | **100.0%** | 100.0% – 100.0% | 100.0% | 100.0% | 3.0 | 1,318 | -49% | 3.0 | 5.8s |

**Highest EX:** `hybrid` (100.0%). **Fewest prompt tokens:** `hybrid` (1,047/question).

_With only 5 questions each EX figure has a wide confidence interval (see column 3); treat gaps smaller than the CI as noise and check the paired test in §4._

## 2. Retrieval quality

| Config | Candidate-pool recall | Final table recall | Final table precision | Reranker fallbacks | FK tables added/q |
|---|---|---|---|---|---|
| `full_schema` | 100.0% | 100.0% | 3.8% | 0 | 0.00 |
| `topk_vector` | 100.0% | 100.0% | 12.5% | 0 | 0.00 |
| `hybrid` | 100.0% | 100.0% | 12.5% | 0 | 0.00 |
| `topk_vector_rerank` | 100.0% | 100.0% | 36.7% | 0 | 0.00 |
| `hybrid_rerank` | 100.0% | 100.0% | 36.7% | 0 | 0.00 |
| `all_combined` | 100.0% | 100.0% | 33.3% | 0 | 0.20 |
| `full_schema_retry` | 100.0% | 100.0% | 3.8% | 0 | 0.00 |
| `hybrid_retry` | 100.0% | 100.0% | 12.5% | 0 | 0.00 |
| `all_combined_retry` | 100.0% | 100.0% | 33.3% | 0 | 0.20 |

_Candidate-pool recall = share of gold tables in the retrieval output before reranking / FK expansion. Precision for `full_schema` is low by construction (every table is included)._

## 3. Accuracy by question complexity (number of gold tables)

| Config | 1 table (n=5) |
|---|---|
| `full_schema` | 100.0% |
| `topk_vector` | 100.0% |
| `hybrid` | 100.0% |
| `topk_vector_rerank` | 100.0% |
| `hybrid_rerank` | 100.0% |
| `all_combined` | 100.0% |
| `full_schema_retry` | 100.0% |
| `hybrid_retry` | 100.0% |
| `all_combined_retry` | 100.0% |

## 4. Paired comparison against `full_schema`

| Config | Better than baseline | Worse than baseline | Same | Sign-test p |
|---|---|---|---|---|
| `topk_vector` | 0 | 0 | 5 | 1.000 |
| `hybrid` | 0 | 0 | 5 | 1.000 |
| `topk_vector_rerank` | 0 | 0 | 5 | 1.000 |
| `hybrid_rerank` | 0 | 0 | 5 | 1.000 |
| `all_combined` | 0 | 0 | 5 | 1.000 |
| `full_schema_retry` | 0 | 0 | 5 | 1.000 |
| `hybrid_retry` | 0 | 0 | 5 | 1.000 |
| `all_combined_retry` | 0 | 0 | 5 | 1.000 |

_"Better" = the question is answered correctly by the config but not by the baseline. p < 0.05 suggests a real difference._

## 5. Where do failures come from?

| Config | correct | retrieval miss | SQL error | wrong result |
|---|---|---|---|---|
| `full_schema` | 5 | 0 | 0 | 0 |
| `topk_vector` | 5 | 0 | 0 | 0 |
| `hybrid` | 5 | 0 | 0 | 0 |
| `topk_vector_rerank` | 5 | 0 | 0 | 0 |
| `hybrid_rerank` | 5 | 0 | 0 | 0 |
| `all_combined` | 5 | 0 | 0 | 0 |
| `full_schema_retry` | 5 | 0 | 0 | 0 |
| `hybrid_retry` | 5 | 0 | 0 | 0 |
| `all_combined_retry` | 5 | 0 | 0 | 0 |

_retrieval miss = at least one gold table was not in the prompt (generation could not have succeeded); SQL error = tables were present but the query failed to run; wrong result = it ran but returned different data._

## 6. Error-fix loop impact

| Config | Max retries | EX first attempt | EX after loop | Fixed | Regressed | Needed a retry | Retry triggers: error / empty / judge | Judge false alarms | Full-schema fallback used → rescued | Kept an earlier attempt | LLM calls/q | Prompt tokens/q |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `full_schema` | 2 | 100.0% | **100.0%** | 0 | 0 | 0 | 0 / 0 / 0 | 0 | 0 → 0 | 0 | 2.0 | 2,591 |
| `topk_vector` | 2 | 100.0% | **100.0%** | 0 | 0 | 0 | 0 / 0 / 0 | 0 | 0 → 0 | 0 | 2.0 | 1,185 |
| `hybrid` | 2 | 100.0% | **100.0%** | 0 | 0 | 0 | 0 / 0 / 0 | 0 | 0 → 0 | 0 | 2.0 | 1,047 |
| `topk_vector_rerank` | 2 | 100.0% | **100.0%** | 0 | 0 | 0 | 0 / 0 / 0 | 0 | 0 → 0 | 0 | 3.0 | 1,385 |
| `hybrid_rerank` | 2 | 100.0% | **100.0%** | 0 | 0 | 0 | 0 / 0 / 0 | 0 | 0 → 0 | 0 | 3.0 | 1,301 |
| `all_combined` | 2 | 100.0% | **100.0%** | 0 | 0 | 0 | 0 / 0 / 0 | 0 | 0 → 0 | 0 | 3.0 | 1,318 |
| `full_schema_retry` | 2 | 100.0% | **100.0%** | 0 | 0 | 0 | 0 / 0 / 0 | 0 | 0 → 0 | 0 | 2.0 | 2,591 |
| `hybrid_retry` | 2 | 100.0% | **100.0%** | 0 | 0 | 0 | 0 / 0 / 0 | 0 | 0 → 0 | 0 | 2.0 | 1,047 |
| `all_combined_retry` | 2 | 100.0% | **100.0%** | 0 | 0 | 0 | 0 / 0 / 0 | 0 | 0 → 0 | 0 | 3.0 | 1,318 |

_EX first attempt = the SQL before any feedback (identical to the same config without the loop). **Fixed** = wrong → right thanks to the loop; **Regressed** = right → wrong (only possible when the LLM judge rejects a correct answer and the retry is worse); **Judge false alarms** = first attempt was correct but the judge asked for a retry. Retrieval metrics in §2 are measured on the first attempt's tables, before any retry widening._

## 7. Configurations compared

| Config | Description | Retriever | k | Rerank | FK expand | Retry loop |
|---|---|---|---|---|---|---|
| `full_schema` | Baseline - the entire schema goes into the prompt | full | all | no | no | max 2, judge on, retry schema hybrid_rerank, last retry = full schema |
| `topk_vector` | Top-k tables by vector similarity | vector | 8 | no | no | max 2, judge on, retry schema hybrid_rerank, last retry = full schema |
| `hybrid` | Top-k tables by vector + BM25 (reciprocal rank fusion) | hybrid | 8 | no | no | max 2, judge on, retry schema hybrid_rerank, last retry = full schema |
| `topk_vector_rerank` | Vector top-N candidates -> LLM reranker keeps best k | vector | 15→8 | yes | no | max 2, judge on, retry schema hybrid_rerank, last retry = full schema |
| `hybrid_rerank` | Hybrid top-N candidates -> LLM reranker keeps best k | hybrid | 15→8 | yes | no | max 2, judge on, retry schema hybrid_rerank, last retry = full schema |
| `all_combined` | Hybrid -> LLM reranker -> FK bridge expansion | hybrid | 15→8 | yes | yes (bridge) | max 2, judge on, retry schema hybrid_rerank, last retry = full schema |
| `full_schema_retry` | full_schema + error-fix loop (2 retries) | full | all | no | no | max 2, judge on, retry schema hybrid_rerank, last retry = full schema |
| `hybrid_retry` | hybrid + error-fix loop (2 retries) | hybrid | 8 | no | no | max 2, judge on, retry schema hybrid_rerank, last retry = full schema |
| `all_combined_retry` | hybrid -> reranker -> FK expansion + error-fix loop (2 retries) | hybrid | 15→8 | yes | yes (bridge) | max 2, judge on, retry schema hybrid_rerank, last retry = full schema |

<details><summary>Effective configuration used</summary>

```yaml
paths:
  spider_dir: ./spider
  data_dir: ./data
  results_dir: ./results_ollama
  cache_path: ./.cache/ollama_cache.sqlite
  report_path: ./report_ollama.md
dataset:
  db_id: auto
  min_tables: 20
  n_questions: 50
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
  model: qwen2.5-coder:7b
  temperature: 0.0
  max_tokens: 512
  rpm: 25
  tpm: 5500
  max_retries: 6
  max_wait_seconds: 90
  use_cache: true
  provider: ollama
  ollama:
    host: https://street-classes-reconstruction-oct.trycloudflare.com
    num_ctx: 8192
    keep_alive: 30m
    timeout_s: 900
    seed: 42
execution:
  timeout_s: 15
defaults:
  k: 8
  candidates_k: 15
  embedder_type: ollama
  embedder_model: nomic-embed-text
  embedder_fallback: tfidf_char
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
| q001 | 1 | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| q002 | 1 | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| q003 | 1 | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| q004 | 1 | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| q005 | 1 | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |

## 9. Caveats

- One database, so results show how retrieval behaves on **this** schema; they will not transfer blindly to other schemas.
- EX comparison is a simplified version of Spider's evaluator (row multiset, column-order insensitive, row order only when gold has ORDER BY).
- LLM output at temperature 0 is not guaranteed bit-identical across runs; responses are cached so re-running this benchmark reproduces these numbers exactly.
- Ollama runs: prompt-token figures are character-based estimates (~3.3 chars/token) because Ollama's own counter ignores prompt-cache hits; they are consistent across configs but not exact.
- The error-fix loop never sees the gold SQL or gold result. The LLM judge can wrongly reject a correct answer (see *Judge false alarms* / *Regressed* in the loop section).
- If the embeddings endpoint was unavailable the vector index fell back to TF-IDF (see *Embedder used* above); BM25 and TF-IDF are both lexical, which shrinks hybrid's advantage.
