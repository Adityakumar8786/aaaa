"""Spider loading: schema objects, database selection, gold-question sampling."""
from __future__ import annotations

import hashlib
import json
import random
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .config import Settings
from .sqlexec import has_order_by, run_sql

_TYPE_MAP = {"text": "TEXT", "number": "NUMERIC", "time": "DATETIME", "boolean": "BOOLEAN", "others": "TEXT"}


# --------------------------------------------------------------------------- schema
@dataclass
class Table:
    name: str
    columns: list  # [(col_name, type)]
    pk: list = field(default_factory=list)
    fks: list = field(default_factory=list)  # [(col, ref_table, ref_col)]


def _q(ident: str) -> str:
    return ident if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", ident) else f'"{ident}"'


@dataclass
class Schema:
    db_id: str
    db_path: Path
    tables: dict  # name -> Table (insertion order == original schema order)

    @property
    def names(self) -> list:
        return list(self.tables)

    def ddl(self, names) -> str:
        wanted = set(names)
        out = []
        for t in self.tables.values():  # original order, regardless of retrieval order
            if t.name not in wanted:
                continue
            lines = [f"  {_q(c)} {ty}" for c, ty in t.columns]
            if t.pk:
                lines.append("  PRIMARY KEY (" + ", ".join(_q(c) for c in t.pk) + ")")
            for col, rt, rc in t.fks:
                lines.append(f"  FOREIGN KEY ({_q(col)}) REFERENCES {_q(rt)}({_q(rc)})")
            out.append(f"CREATE TABLE {_q(t.name)} (\n" + ",\n".join(lines) + "\n);")
        return "\n".join(out)

    def compact(self, name: str) -> str:
        t = self.tables[name]
        return f"{name}(" + ", ".join(c for c, _ in t.columns) + ")"


def find_spider_files(spider_dir: Path) -> Path:
    """Locate the folder containing tables.json (the given dir or one level below it)."""
    spider_dir = Path(spider_dir)
    if (spider_dir / "tables.json").exists():
        return spider_dir
    if spider_dir.exists():
        for sub in sorted(p for p in spider_dir.iterdir() if p.is_dir()):
            if (sub / "tables.json").exists():
                return sub
    raise FileNotFoundError(
        f"tables.json not found in {spider_dir} (or one level below). "
        "Set paths.spider_dir in config.yaml or pass --spider-dir."
    )


def _load_tables_json(spider_dir: Path) -> list:
    return json.loads((find_spider_files(spider_dir) / "tables.json").read_text(encoding="utf-8"))


def load_schema(spider_dir: Path, db_id: str) -> Schema:
    root = find_spider_files(spider_dir)
    entry = next((e for e in _load_tables_json(spider_dir) if e["db_id"] == db_id), None)
    if entry is None:
        raise KeyError(f"db_id {db_id!r} not in tables.json")
    tnames = entry["table_names_original"]
    cols = entry["column_names_original"]
    ctypes = entry["column_types"]
    tables = {n: Table(n, []) for n in tnames}
    for i, ((ti, cname), cty) in enumerate(zip(cols, ctypes)):
        if ti < 0:
            continue
        tables[tnames[ti]].columns.append((cname, _TYPE_MAP.get(cty, "TEXT")))
    pks = []
    for pk in entry.get("primary_keys", []):
        pks.extend(pk if isinstance(pk, list) else [pk])
    for ci in pks:
        ti, cname = cols[ci]
        if ti >= 0:
            tables[tnames[ti]].pk.append(cname)
    for a, b in entry.get("foreign_keys", []):
        (ta, ca), (tb, cb) = cols[a], cols[b]
        if ta >= 0 and tb >= 0:
            tables[tnames[ta]].fks.append((ca, tnames[tb], cb))
    db_path = root / "database" / db_id / f"{db_id}.sqlite"
    return Schema(db_id, db_path, tables)


# --------------------------------------------------------------------------- gold set
@dataclass
class GoldQuestion:
    qid: str
    db_id: str
    question: str
    gold_sql: str
    gold_tables: list
    bucket: int  # 1, 2, or 3 (= 3+ tables)


@dataclass
class Gold:
    meta: dict
    questions: list
    hash: str


def extract_tables(sql: str, table_names) -> list:
    lower = {t.lower(): t for t in table_names}
    try:
        import sqlglot
        from sqlglot import exp

        tree = sqlglot.parse_one(sql, read="sqlite")
        found = [t.name for t in tree.find_all(exp.Table)]
    except Exception:  # noqa: BLE001
        found = re.findall(r"\b(?:from|join)\s+[`\"\[]?([A-Za-z_]\w*)", sql, re.I)
    out = []
    for n in found:
        real = lower.get(n.lower())
        if real and real not in out:
            out.append(real)
    return out


def _question_files(settings: Settings, root: Path):
    for fn in settings.dataset.question_files:
        p = root / fn
        if p.exists():
            yield p


def _load_questions(settings: Settings) -> list:
    root = find_spider_files(settings.paths.spider_dir)
    items, seen = [], set()
    for p in _question_files(settings, root):
        for it in json.loads(p.read_text(encoding="utf-8")):
            key = (it["db_id"], it["question"].strip().lower())
            if key in seen:
                continue
            seen.add(key)
            items.append({"db_id": it["db_id"], "question": it["question"].strip(), "query": it["query"].strip()})
    return items


def list_candidate_dbs(settings: Settings) -> list:
    tables = _load_tables_json(settings.paths.spider_dir)
    qcount: dict = {}
    for it in _load_questions(settings):
        qcount[it["db_id"]] = qcount.get(it["db_id"], 0) + 1
    rows = [
        {"db_id": e["db_id"], "n_tables": len(e["table_names_original"]), "n_questions": qcount.get(e["db_id"], 0)}
        for e in tables
        if len(e["table_names_original"]) >= settings.dataset.min_tables
    ]
    rows = [r for r in rows if r["n_questions"] > 0]
    return sorted(rows, key=lambda r: (-r["n_questions"], -r["n_tables"], r["db_id"]))


def _allocate(n: int, mix: dict, avail: dict) -> dict:
    keys = sorted(mix)
    alloc = {b: min(avail.get(b, 0), round(n * mix[b])) for b in keys}
    while sum(alloc.values()) < n:
        spare = {b: avail.get(b, 0) - alloc[b] for b in keys}
        b = max(spare, key=lambda x: (spare[x], mix[x]))
        if spare[b] <= 0:
            break
        alloc[b] += 1
    while sum(alloc.values()) > n:
        b = max(alloc, key=alloc.get)
        alloc[b] -= 1
    return alloc


def build_gold(settings: Settings, db_id: str | None = None, log=print) -> Gold:
    ds = settings.dataset
    db_id = db_id or ds.db_id
    if db_id == "auto":
        cands = list_candidate_dbs(settings)
        if not cands:
            raise RuntimeError(
                f"No Spider database with >= {ds.min_tables} tables and questions was found. "
                "Lower dataset.min_tables or check paths.spider_dir."
            )
        log("Databases with >= %d tables:" % ds.min_tables)
        for c in cands[:10]:
            log(f"   {c['db_id']:<28} tables={c['n_tables']:<3} questions={c['n_questions']}")
        db_id = cands[0]["db_id"]
        log(f"-> auto-selected: {db_id}")
    schema = load_schema(settings.paths.spider_dir, db_id)
    if not schema.db_path.exists():
        raise FileNotFoundError(f"SQLite file missing: {schema.db_path}")
    pool = [q for q in _load_questions(settings) if q["db_id"] == db_id]
    log(f"{len(pool)} candidate questions for {db_id}; validating gold SQL ...")

    valid = []
    for it in pool:
        ok, rows, err = run_sql(schema.db_path, it["query"], settings.exec_timeout_s)
        if not ok or (ds.exclude_empty_gold and not rows):
            continue
        gt = extract_tables(it["query"], schema.names)
        if not gt:
            continue
        it["gold_tables"] = gt
        it["bucket"] = min(len(gt), 3)
        valid.append(it)
    log(f"{len(valid)} usable after dropping failing/empty gold queries")
    if len(valid) < ds.n_questions:
        log(f"WARNING: only {len(valid)} usable questions (< n_questions={ds.n_questions}); using all of them.")

    rng = random.Random(ds.seed)
    by_bucket: dict = {}
    for it in valid:
        by_bucket.setdefault(it["bucket"], []).append(it)
    for lst in by_bucket.values():
        rng.shuffle(lst)
    n = min(ds.n_questions, len(valid))
    alloc = _allocate(n, ds.bucket_mix, {b: len(v) for b, v in by_bucket.items()})
    chosen = []
    for b, cnt in alloc.items():
        chosen.extend(by_bucket.get(b, [])[:cnt])
    rng.shuffle(chosen)
    questions = [
        GoldQuestion(f"q{i + 1:03d}", c["db_id"], c["question"], c["query"], c["gold_tables"], c["bucket"])
        for i, c in enumerate(chosen)
    ]
    meta = {
        "db_id": db_id,
        "n_tables": len(schema.names),
        "n_questions": len(questions),
        "seed": ds.seed,
        "bucket_counts": {str(b): sum(1 for q in questions if q.bucket == b) for b in (1, 2, 3)},
        "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    gold = Gold(meta, questions, _hash_questions(questions))
    save_gold(settings, gold)
    log(f"Gold set: {meta['n_questions']} questions, buckets (1/2/3+ tables) = {meta['bucket_counts']}")
    return gold


def _hash_questions(questions) -> str:
    blob = json.dumps([(q.qid, q.question, q.gold_sql) for q in questions])
    return hashlib.sha1(blob.encode()).hexdigest()[:12]


def gold_path(settings: Settings) -> Path:
    return settings.paths.data_dir / "gold.json"


def save_gold(settings: Settings, gold: Gold) -> None:
    p = gold_path(settings)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        json.dumps({"meta": gold.meta, "questions": [q.__dict__ for q in gold.questions]}, indent=2),
        encoding="utf-8",
    )


def load_gold(settings: Settings) -> Gold:
    p = gold_path(settings)
    if not p.exists():
        raise FileNotFoundError(f"{p} not found. Run:  python -m nl2sql prepare")
    d = json.loads(p.read_text(encoding="utf-8"))
    qs = [GoldQuestion(**q) for q in d["questions"]]
    return Gold(d["meta"], qs, _hash_questions(qs))


__all__ = ["Schema", "Table", "Gold", "GoldQuestion", "load_schema", "build_gold", "load_gold", "has_order_by"]
