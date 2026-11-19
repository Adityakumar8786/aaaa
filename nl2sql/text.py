"""Tiny text utilities shared by BM25 / vector retrieval."""
from __future__ import annotations

import re

STOP = set(
    """a an the of in on at to for from by with and or is are was were be been being what which who whom whose
    how many much that this those these there their its it as than then have has had do does did not no please
    list show give find return tell me all each every where when also any more most
    """.split()
)


def stem(tok: str) -> str:
    if len(tok) > 4 and tok.endswith("ies"):
        return tok[:-3] + "y"
    if len(tok) > 4 and tok.endswith("sses"):
        return tok[:-2]
    if len(tok) > 3 and tok.endswith("s") and not tok.endswith(("ss", "us", "is")):
        return tok[:-1]
    return tok


def tokenize(text: str, drop_stop: bool = True) -> list[str]:
    text = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", text)  # camelCase -> camel Case
    toks = re.findall(r"[A-Za-z0-9]+", text.lower())
    if drop_stop:
        toks = [t for t in toks if t not in STOP]
    return [stem(t) for t in toks]


def words(identifier: str) -> str:
    return re.sub(r"[_\W]+", " ", identifier).strip()
