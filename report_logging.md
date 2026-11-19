# NL2SQL schema-retrieval benchmark

- **Generated:** 2026-11-18 00:56
- **Database:** `baseball_1` (26 tables) &nbsp;|&nbsp; **Questions:** 50 (buckets 1/2/3+ tables = 15/31/4, seed 42)
- **LLM:** qwen2.5-coder:7b via Ollama (temperature 0.0) &nbsp;|&nbsp; **Embedder used:** ollama
- **Metric:** execution accuracy (EX) = predicted SQL returns the same result set as the gold SQL (simplified Spider-style comparison)

## 1. Summary

| Config | EX accuracy | 95% CI | Table recall | All gold tables kept | Avg tables in prompt | Avg prompt tokens | Δ tokens vs baseline | LLM calls/q | LLM time/q |
|---|---|---|---|---|---|---|---|---|---|
| `full_schema` | **60.0%** | 46.0% – 72.0% | 100.0% | 100.0% | 26.0 | 2,384 | +0% | 1.0 | 24.9s |
| `topk_vector` | **58.0%** | 44.0% – 70.0% | 97.0% | 94.0% | 8.0 | 1,009 | -58% | 1.0 | 73.0s |
| `hybrid` | **58.0%** | 44.0% – 70.0% | 96.0% | 94.0% | 8.0 | 925 | -61% | 1.0 | 4.5s |
| `topk_vector_rerank` | **60.0%** | 44.0% – 72.0% | 97.0% | 94.0% | 3.4 | 1,275 | -47% | 2.0 | 3.9s |
| `hybrid_rerank` | **60.0%** | 46.0% – 74.0% | 97.0% | 96.0% | 3.4 | 1,198 | -50% | 2.0 | 3.8s |
| `all_combined` | **54.0%** | 40.0% – 68.0% | 97.0% | 96.0% | 4.0 | 1,250 | -48% | 2.0 | 3.8s |

**Highest EX:** `hybrid_rerank` (60.0%). **Fewest prompt tokens:** `hybrid` (925/question).

_With only 50 questions each EX figure has a wide confidence interval (see column 3); treat gaps smaller than the CI as noise and check the paired test in §4._

## 2. Retrieval quality

| Config | Candidate-pool recall | Final table recall | Final table precision | Reranker fallbacks | FK tables added/q |
|---|---|---|---|---|---|
| `full_schema` | 100.0% | 100.0% | 6.8% | 0 | 0.00 |
| `topk_vector` | 97.0% | 97.0% | 21.5% | 0 | 0.00 |
| `hybrid` | 96.0% | 96.0% | 21.2% | 0 | 0.00 |
| `topk_vector_rerank` | 97.0% | 97.0% | 57.4% | 0 | 0.00 |
| `hybrid_rerank` | 99.0% | 97.0% | 58.8% | 0 | 0.00 |
| `all_combined` | 99.0% | 97.0% | 54.3% | 0 | 0.52 |

_Candidate-pool recall = share of gold tables in the retrieval output before reranking / FK expansion. Precision for `full_schema` is low by construction (every table is included)._

## 3. Accuracy by question complexity (number of gold tables)

| Config | 1 table (n=15) | 2 tables (n=31) | 3+ tables (n=4) |
|---|---|---|---|
| `full_schema` | 86.7% | 41.9% | 100.0% |
| `topk_vector` | 86.7% | 38.7% | 100.0% |
| `hybrid` | 86.7% | 38.7% | 100.0% |
| `topk_vector_rerank` | 86.7% | 45.2% | 75.0% |
| `hybrid_rerank` | 86.7% | 41.9% | 100.0% |
| `all_combined` | 86.7% | 35.5% | 75.0% |

## 4. Paired comparison against `full_schema`

| Config | Better than baseline | Worse than baseline | Same | Sign-test p |
|---|---|---|---|---|
| `topk_vector` | 1 | 2 | 47 | 1.000 |
| `hybrid` | 1 | 2 | 47 | 1.000 |
| `topk_vector_rerank` | 3 | 3 | 44 | 1.000 |
| `hybrid_rerank` | 3 | 3 | 44 | 1.000 |
| `all_combined` | 1 | 4 | 45 | 0.375 |

_"Better" = the question is answered correctly by the config but not by the baseline. p < 0.05 suggests a real difference._

## 5. Where do failures come from?

| Config | correct | retrieval miss | SQL error | wrong result |
|---|---|---|---|---|
| `full_schema` | 30 | 0 | 4 | 16 |
| `topk_vector` | 29 | 3 | 4 | 14 |
| `hybrid` | 29 | 3 | 4 | 14 |
| `topk_vector_rerank` | 30 | 3 | 2 | 15 |
| `hybrid_rerank` | 30 | 2 | 2 | 16 |
| `all_combined` | 27 | 2 | 2 | 19 |

_retrieval miss = at least one gold table was not in the prompt (generation could not have succeeded); SQL error = tables were present but the query failed to run; wrong result = it ran but returned different data._

## 6. Configurations compared

| Config | Description | Retriever | k | Rerank | FK expand |
|---|---|---|---|---|---|
| `full_schema` | Baseline - the entire schema goes into the prompt | full | all | no | no |
| `topk_vector` | Top-k tables by vector similarity | vector | 8 | no | no |
| `hybrid` | Top-k tables by vector + BM25 (reciprocal rank fusion) | hybrid | 8 | no | no |
| `topk_vector_rerank` | Vector top-N candidates -> LLM reranker keeps best k | vector | 15→8 | yes | no |
| `hybrid_rerank` | Hybrid top-N candidates -> LLM reranker keeps best k | hybrid | 15→8 | yes | no |
| `all_combined` | Hybrid -> LLM reranker -> FK bridge expansion | hybrid | 15→8 | yes | yes (bridge) |

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
    host: https://meets-capabilities-punk-moments.trycloudflare.com
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

```
</details>

## 7. Per-question matrix

`✓` correct · `✗R` retrieval miss · `✗E` SQL error · `✗` wrong result

| Q | Tables needed | `full_schema` | `topk_vector` | `hybrid` | `topk_vector_rerank` | `hybrid_rerank` | `all_combined` |
|---|---|---|---|---|---|---|---|
| q001 | 1 | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| q002 | 1 | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| q003 | 1 | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| q004 | 1 | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| q005 | 1 | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| q006 | 1 | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ |
| q007 | 2 | ✗ | ✗R | ✗R | ✗R | ✗ | ✗ |
| q008 | 2 | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| q009 | 2 | ✗ | ✗ | ✗ | ✗ | ✓ | ✗ |
| q010 | 2 | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ |
| q011 | 2 | ✗ | ✓ | ✓ | ✓ | ✓ | ✓ |
| q012 | 2 | ✗E | ✗E | ✗E | ✗E | ✗E | ✗E |
| q013 | 1 | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| q014 | 2 | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ |
| q015 | 2 | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| q016 | 2 | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ |
| q017 | 3+ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| q018 | 2 | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| q019 | 2 | ✗ | ✗E | ✗E | ✗ | ✗ | ✗ |
| q020 | 3+ | ✓ | ✓ | ✓ | ✗ | ✓ | ✗ |
| q021 | 2 | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| q022 | 2 | ✗ | ✗R | ✗R | ✗R | ✗R | ✗R |
| q023 | 2 | ✗E | ✗E | ✗E | ✗E | ✗E | ✗E |
| q024 | 2 | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ |
| q025 | 2 | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| q026 | 1 | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| q027 | 2 | ✓ | ✗ | ✗ | ✗ | ✗ | ✗ |
| q028 | 1 | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| q029 | 1 | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| q030 | 3+ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| q031 | 2 | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| q032 | 1 | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| q033 | 2 | ✗E | ✗R | ✗ | ✗R | ✗R | ✗R |
| q034 | 1 | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ |
| q035 | 2 | ✗E | ✗E | ✗E | ✗ | ✗ | ✗ |
| q036 | 1 | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| q037 | 2 | ✓ | ✓ | ✓ | ✓ | ✗ | ✗ |
| q038 | 2 | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| q039 | 2 | ✗ | ✗ | ✗ | ✓ | ✓ | ✗ |
| q040 | 2 | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| q041 | 3+ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| q042 | 2 | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ |
| q043 | 2 | ✗ | ✗ | ✗ | ✓ | ✗ | ✗ |
| q044 | 1 | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| q045 | 2 | ✗ | ✗ | ✗R | ✗ | ✗ | ✗ |
| q046 | 2 | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| q047 | 1 | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| q048 | 2 | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| q049 | 2 | ✓ | ✗ | ✗ | ✗ | ✗ | ✗ |
| q050 | 2 | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ |

## 8. Caveats

- One database, so results show how retrieval behaves on **this** schema; they will not transfer blindly to other schemas.
- EX comparison is a simplified version of Spider's evaluator (row multiset, column-order insensitive, row order only when gold has ORDER BY).
- LLM output at temperature 0 is not guaranteed bit-identical across runs; responses are cached so re-running this benchmark reproduces these numbers exactly.
- Ollama runs: prompt-token figures are character-based estimates (~3.3 chars/token) because Ollama's own counter ignores prompt-cache hits; they are consistent across configs but not exact.
- If the embeddings endpoint was unavailable the vector index fell back to TF-IDF (see *Embedder used* above); BM25 and TF-IDF are both lexical, which shrinks hybrid's advantage.
