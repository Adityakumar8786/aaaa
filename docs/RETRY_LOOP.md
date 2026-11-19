# Error-fix (retry) loop

After the first SQL is generated and executed, the pipeline can retry up to **`max_retries`** times. It is **off by default**
(`max_retries: 0`), so all your existing configurations and results are unchanged.

```
retrieve -> [rerank] -> [fk_expand] -> generate_sql -> execute_sql --failed?--> retry_sql -> execute_sql ...
                                              |
                                              +--ran fine--> judge_result --accepts--> finalize_sql -> END
                                                                   +--rejects--> retry_sql ...
```

## What triggers a retry
| Trigger | Condition |
|---|---|
| **error** | SQLite raised an error (syntax, no such column, timeout ...) |
| **empty** | the query ran but returned 0 rows (`retry_on_empty: true`; gold questions never have empty answers) |
| **judge** | the query ran and returned rows, but an LLM judge says the result does not answer the question (`retry_judge: true`, 1 extra LLM call per attempt) |

The judge sees only the question, the SQL and the first `judge_rows` result rows. It never sees the gold SQL or gold result.
The judge is skipped on the last attempt (a retry is no longer possible), and an unparsable judge reply counts as "accepted".

## What the model sees / what changes on a retry
Every retry sends: the **schema**, the **question**, its **previous SQL** (as an assistant turn) and the **feedback**
(the error text, "returned no rows", or the judge's reason). The schema is chosen like this:

1. **Last allowed retry -> the FULL schema** (`retry_full_schema_last: true`). A safety net for retrieval misses.
   (With `max_retries: 1` the single retry therefore already uses the full schema.)
2. **Earlier retries -> `retry_schema`** (default **`hybrid_rerank`**): the question *plus the feedback text* is used as a new
   hybrid (vector + BM25) query, the top `candidates_k` tables go to the LLM reranker (which also sees the feedback), and the
   selected tables are **merged with the tables already shown** (nothing is dropped). `fk_expand` is applied too if the config uses it.
   Alternatives: `neighbors` (add foreign-key neighbour tables) or `none` (same schema).
3. If the schema already contains every table (e.g. `full_schema` configs) the schema is left alone.

If the final attempt is unusable (error / empty) but an **earlier attempt ran fine** (e.g. the judge rejected it and the retry then
failed), the earlier attempt is returned instead (`Kept an earlier attempt` in the report).

## Configure
In `config.yaml` (`defaults:` for everything, or per configuration):

```yaml
max_retries: 2              # 0 = off
retry_on_empty: true
retry_judge: true
retry_schema: hybrid_rerank # hybrid_rerank | neighbors | none
retry_full_schema_last: true
judge_rows: 5
```

Three ready-made configurations were added: `full_schema_retry`, `hybrid_retry`, `all_combined_retry` (all `max_retries: 2`).

Or switch the loop on from the command line for any configuration, without editing the file:

```bash
python -m nl2sql run --config hybrid --max-retries 3          # creates + runs the derived config "hybrid+r3"
python -m nl2sql run --all --max-retries 2                    # every config with a 2-retry loop ("full_schema+r2", ...)
python -m nl2sql run --config hybrid_rerank --max-retries 2 --no-judge          # errors / empty only -> "hybrid_rerank+r2-nojudge"
python -m nl2sql run --config hybrid --max-retries 2 --retry-schema neighbors   # -> "hybrid+r2-neighbors"
python -m nl2sql ask q007 --config hybrid --max-retries 2     # watch one question: triggers, schema changes, judge verdicts
python -m nl2sql test --config hybrid --max-retries 2         # 5-question smoke test
python -m nl2sql report                                       # report includes every config that has results, derived ones too
```
(With Ollama put `-c config.ollama.yaml` before the command name, as usual.)

Derived configs store their results under their own name, so the plain configuration's results are never overwritten.

## Reading the report (new section "Error-fix loop impact")
* **EX first attempt** = accuracy before any feedback (equals the same config without the loop); **EX after loop** = final accuracy.
* **Fixed** = wrong -> right because of the loop. **Regressed** = right -> wrong: possible only through the judge (it rejected a correct
  answer and the retry was worse). **Judge false alarms** counts the first-attempt-correct answers the judge asked to retry.
* **Retry triggers** = how many retries came from errors / empty results / the judge.
* **Full-schema fallback used -> rescued** = how often the last-retry full schema was used, and in how many of those the question was then answered correctly.
* **LLM calls/q** and **Prompt tokens/q** show the cost. Expect roughly 2x calls per question because of the judge.
* Retrieval recall/precision in the retrieval section are always measured on the *first attempt's* tables, so they still describe the retriever alone.

## Cost notes
Each question costs: 1 generation + 1 judge call, plus for each retry 1 generation (+1 rerank call for `hybrid_rerank`) (+1 judge call
if more retries remain). `python -m nl2sql estimate` includes rough numbers (assumes ~35% of questions need a retry).
`--no-judge` removes the judge calls. Everything is cached, so re-running after an interruption costs nothing for finished calls.