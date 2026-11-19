"""Safe SQLite execution + execution-accuracy result comparison."""
from __future__ import annotations

import re
import sqlite3
import time
from collections import Counter
from itertools import permutations
from pathlib import Path


def run_sql(db_path, sql: str, timeout_s: float = 15.0, max_rows: int = 100_000):
    """Returns (ok, rows | None, error | None). Opens the DB read-only."""
    sql = (sql or "").strip()
    if not sql:
        return False, None, "empty SQL"
    if not re.match(r"^\s*(select|with)\b", sql, re.I):
        return False, None, "only SELECT / WITH queries are allowed"
    uri = Path(db_path).resolve().as_uri() + "?mode=ro"
    conn = None
    try:
        conn = sqlite3.connect(uri, uri=True, timeout=timeout_s)
        conn.text_factory = lambda b: b.decode("utf-8", errors="ignore")
        deadline = time.monotonic() + timeout_s
        conn.set_progress_handler(lambda: 1 if time.monotonic() > deadline else 0, 20000)
        cur = conn.execute(sql)
        rows = [tuple(r) for r in cur.fetchmany(max_rows)]
        return True, rows, None
    except Exception as e:  # noqa: BLE001
        return False, None, f"{type(e).__name__}: {e}"
    finally:
        if conn is not None:
            conn.close()


def _norm(v):
    if isinstance(v, bool):
        return int(v)
    if isinstance(v, (int, float)):
        return round(float(v), 6)
    return v


def _norm_rows(rows):
    return [tuple(_norm(v) for v in r) for r in rows]


def has_order_by(sql: str) -> bool:
    return re.search(r"\border\s+by\b", sql or "", re.I) is not None


def results_match(pred_rows, gold_rows, order_matters: bool = False) -> bool:
    """Simplified Spider-style execution match (row multiset; column order insensitive)."""
    if pred_rows is None or gold_rows is None:
        return False
    p, g = _norm_rows(pred_rows), _norm_rows(gold_rows)
    if len(p) != len(g):
        return False
    if not g:
        return True
    n = len(g[0])
    if len(p[0]) != n:
        return False

    def same(a, b):
        return a == b if order_matters else Counter(a) == Counter(b)

    if same(p, g):
        return True
    if n > 6:
        return False
    # allow column permutation (cheap prefilter on column multisets first)
    pcols = sorted(tuple(sorted(map(repr, col))) for col in zip(*p))
    gcols = sorted(tuple(sorted(map(repr, col))) for col in zip(*g))
    if pcols != gcols:
        return False
    for perm in permutations(range(n)):
        if same([tuple(r[i] for i in perm) for r in p], g):
            return True
    return False
