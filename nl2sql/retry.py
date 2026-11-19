"""Helpers for the error-fix (retry) loop: the LLM result judge and feedback wording."""
from __future__ import annotations

import json
import re

from .prompts import JUDGE_SYSTEM, JUDGE_USER


def preview_rows(rows: list, n: int = 5, width: int = 160) -> str:
    if not rows:
        return "(no rows)"
    lines = []
    for r in rows[:n]:
        s = repr(tuple(r))
        lines.append(s if len(s) <= width else s[: width - 3] + "...")
    if len(rows) > n:
        lines.append(f"... ({len(rows) - n} more rows)")
    return "\n".join(lines)


def parse_verdict(text: str):
    """Returns (answers_question: bool, reason: str). Unparsable output is treated as 'accepted' (never retry on noise)."""
    m = re.search(r"\{.*\}", text or "", re.S)
    if m:
        try:
            d = json.loads(m.group(0))
            v = d.get("answers_question")
            if isinstance(v, str):
                v = v.strip().lower() in ("true", "yes")
            if isinstance(v, bool):
                return v, str(d.get("reason", "")).strip()[:300]
        except (json.JSONDecodeError, AttributeError):
            pass
    return True, "unparsable judge verdict; accepted"


def judge_answer(llm, question: str, sql: str, rows: list, n_preview: int = 5, model: str | None = None):
    """One LLM call. Returns (ok, reason, LLMResult)."""
    prompt = JUDGE_USER.format(question=question, sql=sql, n_rows=len(rows), preview=preview_rows(rows, n_preview))
    res = llm.chat([{"role": "system", "content": JUDGE_SYSTEM}, {"role": "user", "content": prompt}],
                   max_tokens=120, model=model)
    ok, reason = parse_verdict(res.text)
    return ok, reason, res


def feedback_text(kind: str, error: str = "", judge_reason: str = "") -> str:
    """The sentence shown to the model in the FIX prompt (also used to enrich the retry retrieval query)."""
    if kind == "error":
        return f"it failed to run with this error: {error[:300]}"
    if kind == "empty":
        return "it ran but returned no rows"
    return f"a reviewer found that its result does not answer the question ({judge_reason[:250]})"