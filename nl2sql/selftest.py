"""Offline end-to-end self-test: synthetic Spider-style DB (22 tables) + a mock LLM. No API key needed.

The numbers it produces are meaningless for research - it only proves the plumbing works.
"""
from __future__ import annotations

import json
import re
import shutil
import sqlite3
from pathlib import Path

import yaml

from .llm import LLMResult

# name -> list of parent tables (FK columns are <parent>_id)
TABLES = {
    "country": [], "city": ["country"], "campus": ["city"], "building": ["campus"], "classroom": ["building"],
    "department": ["campus"], "professor": ["department"], "student": ["department"], "course": ["department"],
    "enrollment": ["student", "course"], "lab": ["department"], "equipment": ["lab"], "library": ["campus"],
    "publisher": [], "book": ["publisher"], "author": [], "book_author": ["book", "author"],
    "loan": ["book", "student"], "project": ["professor"], "project_member": ["project", "student"],
    "club": ["campus"], "scholarship": ["student"],
}


def _words(t):
    return t.replace("_", " ")


def build_fixture(root: Path):
    """Create root/{tables.json, train_spider.json, database/uni/uni.sqlite}. Returns gold-question list."""
    if root.exists():
        shutil.rmtree(root)
    (root / "database" / "uni").mkdir(parents=True)
    db = sqlite3.connect(root / "database" / "uni" / "uni.sqlite")
    names = list(TABLES)
    col_names = [[-1, "*"]]
    col_types = ["text"]
    pks, fks = [], []
    idx_of = {}
    for ti, t in enumerate(names):
        cols = [(f"{t}_id", "INTEGER"), ("name", "TEXT"), ("size", "INTEGER")] + [(f"{p}_id", "INTEGER") for p in TABLES[t]]
        db.execute(f"CREATE TABLE {t} (" + ", ".join(f"{c} {ty}" for c, ty in cols) + ")")
        for c, ty in cols:
            idx_of[(t, c)] = len(col_names)
            col_names.append([ti, c])
            col_types.append("number" if ty == "INTEGER" else "text")
        pks.append(idx_of[(t, f"{t}_id")])
        for i in range(1, 7):
            vals = [i, f"{_words(t)} {i}", i * 10] + [(i % 4) + 1 for _ in TABLES[t]]
            db.execute(f"INSERT INTO {t} VALUES ({','.join('?' * len(vals))})", vals)
    for t in names:
        for p in TABLES[t]:
            fks.append([idx_of[(t, f"{p}_id")], idx_of[(p, f"{p}_id")]])
    db.commit()
    db.close()
    (root / "tables.json").write_text(json.dumps([{
        "db_id": "uni", "table_names_original": names, "table_names": [_words(n) for n in names],
        "column_names_original": col_names, "column_names": col_names, "column_types": col_types,
        "primary_keys": pks, "foreign_keys": fks}]))

    qs = []
    for t in names:
        qs.append({"db_id": "uni", "question": f"How many {_words(t)} records are there?", "query": f"SELECT count(*) FROM {t}"})
        qs.append({"db_id": "uni", "question": f"What are the names of all {_words(t)} entries?", "query": f"SELECT name FROM {t}"})
    for c, parents in TABLES.items():
        for p in parents:
            qs.append({"db_id": "uni",
                       "question": f"What are the names of {_words(p)} that have at least one {_words(c)}?",
                       "query": f"SELECT DISTINCT T1.name FROM {p} AS T1 JOIN {c} AS T2 ON T2.{p}_id = T1.{p}_id"})
    for c, parents in TABLES.items():
        for p in parents:
            for gp in TABLES[p]:
                qs.append({"db_id": "uni",
                           "question": f"Which {_words(gp)} names have a {_words(p)} that has a {_words(c)}?",
                           "query": (f"SELECT DISTINCT T1.name FROM {gp} AS T1 JOIN {p} AS T2 ON T2.{gp}_id = T1.{gp}_id "
                                     f"JOIN {c} AS T3 ON T3.{p}_id = T2.{p}_id")})
    (root / "train_spider.json").write_text(json.dumps(qs))
    return qs


class MockLLM:
    """Pretends to be the LLM. Generation = oracle gold SQL, but only when every gold table is in the prompt;
    otherwise it returns either a broken query or a valid-but-wrong one (so both retry triggers are exercised).
    The judge is an oracle (compares with gold) - fine for plumbing tests, meaningless as a quality measure."""

    def __init__(self, questions):
        self.gold = {q["question"]: q["query"] for q in questions}
        self.calls = 0
        self.kinds = {"judge": 0, "rerank": 0, "fix": 0, "gen": 0}

    @staticmethod
    def _norm(sql):
        return re.sub(r"\s+", " ", sql).strip().lower()

    def chat(self, messages, max_tokens=None, model=None) -> LLMResult:
        self.calls += 1
        first_user = next(m["content"] for m in messages if m["role"] == "user")
        last_user = messages[-1]["content"]
        q = re.search(r"Question: (.*)", first_user).group(1).strip()
        if "Does this result plausibly" in last_user:  # LLM judge
            self.kinds["judge"] += 1
            sql = re.search(r"SQL query:\n(.*?)\n\nResult", last_user, re.S).group(1)
            same = self._norm(sql) == self._norm(self.gold[q])
            return LLMResult(json.dumps({"answers_question": same, "reason": "mock oracle judge"}), len(last_user) // 4, 15, 0.01)
        if "Select at most" in last_user:  # reranker
            self.kinds["rerank"] += 1
            k = int(re.search(r"at most (\d+) tables", last_user).group(1))
            cands = re.findall(r"^- (\w+)\(", last_user, re.M)
            qtoks = set(re.findall(r"[a-z]+", q.lower()))
            hit = [c for c in cands if all(w.rstrip("s") in {t.rstrip("s") for t in qtoks} for w in c.split("_"))]
            rest = [c for c in cands if c not in hit]
            return LLMResult(json.dumps({"tables": (hit + rest)[:k]}), len(last_user) // 4, 20, 0.01)
        self.kinds["fix" if "Fix it" in last_user else "gen"] += 1
        sql = self.gold[q]
        present = set(re.findall(r"CREATE TABLE (\w+)", first_user))
        needed = set(re.findall(r"\b(?:FROM|JOIN)\s+(\w+)", sql))
        if needed <= present:
            out = sql
        elif len(q) % 2 == 0:
            out = "SELECT * FROM table_that_does_not_exist"            # broken query -> error trigger
        else:
            out = f"SELECT name FROM {sorted(present)[0]}"              # runs, non-empty, wrong -> judge trigger
        return LLMResult(f"```sql\n{out}\n```", len(first_user) // 4, 30, 0.01)


def run_selftest(out_dir: Path, log=print) -> Path:
    from .config import load_settings
    from .data import build_gold, load_schema
    from .evaluate import run_config
    from .report import write_report

    out_dir = Path(out_dir).resolve()
    if out_dir.exists():
        shutil.rmtree(out_dir)
    spider = out_dir / "fake_spider"
    qs = build_fixture(spider)
    cfg_path = out_dir / "config.yaml"
    base = yaml.safe_load((Path(__file__).resolve().parents[1] / "config.yaml").read_text(encoding="utf-8"))
    base["paths"] = {"spider_dir": "./fake_spider", "data_dir": "./data", "results_dir": "./results",
                     "cache_path": "./.cache/c.sqlite", "report_path": "./report.md"}
    base["dataset"].update(n_questions=40, min_tables=20)
    base["defaults"].update(embedder_type="tfidf_char", embedder_fallback="none", k=2, candidates_k=6)
    cfg_path.write_text(yaml.safe_dump(base, sort_keys=False))
    settings = load_settings(cfg_path)

    gold = build_gold(settings, log=log)
    schema = load_schema(settings.paths.spider_dir, gold.meta["db_id"])
    llm = MockLLM(qs)
    for name, rc in settings.configs.items():
        run_config(settings, rc, gold, schema, llm, verbose=False, log=log)
    path = write_report(settings, gold, title_note="SELFTEST: synthetic data + mock LLM. Numbers are NOT meaningful.")
    log(f"\nSelf-test OK. Sample report: {path}")
    return path