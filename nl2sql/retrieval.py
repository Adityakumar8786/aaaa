"""Schema retrieval: full / vector / BM25 / hybrid, LLM reranker, FK expansion."""
from __future__ import annotations

import json
import math
import re
from collections import Counter

import numpy as np

from .config import RunConfig
from .data import Schema
from .llm import LLMError, RateLimitExhausted
from .prompts import RERANK_SYSTEM, RERANK_USER
from .text import tokenize, words


# --------------------------------------------------------------------------- documents
def build_table_docs(schema: Schema) -> dict:
    """One searchable text document per table (name + column names)."""
    docs = {}
    for t in schema.tables.values():
        nm = words(t.name)
        cols = ", ".join(words(c) for c, _ in t.columns)
        docs[t.name] = f"table {nm}. {nm}. columns: {cols}"
    return docs


# --------------------------------------------------------------------------- BM25
class Bm25Index:
    def __init__(self, docs: dict, k1: float = 1.5, b: float = 0.75):
        self.names = list(docs)
        self.k1, self.b = k1, b
        toks = [tokenize(docs[n]) for n in self.names]
        self.tf = [Counter(t) for t in toks]
        self.len = [len(t) for t in toks]
        self.avgdl = (sum(self.len) / len(self.len)) or 1.0
        df = Counter()
        for t in toks:
            df.update(set(t))
        n = len(self.names)
        self.idf = {w: math.log(1 + (n - c + 0.5) / (c + 0.5)) for w, c in df.items()}

    def scores(self, query: str) -> dict:
        q = tokenize(query)
        out = {}
        for i, name in enumerate(self.names):
            s = 0.0
            for w in q:
                f = self.tf[i].get(w, 0)
                if f:
                    s += self.idf.get(w, 0.0) * f * (self.k1 + 1) / (f + self.k1 * (1 - self.b + self.b * self.len[i] / self.avgdl))
            out[name] = s
        return out


# --------------------------------------------------------------------------- vectors
_ST_MODELS: dict = {}


class VectorIndex:
    """Dense / sparse-vector table index. `used` records which embedder actually ran."""

    def __init__(self, docs: dict, rc: RunConfig, llm=None, log=print):
        self.names = list(docs)
        self.raw = [docs[n] for n in self.names]
        self.rc, self.llm, self.log = rc, llm, log
        self.used = rc.embedder_type
        self.note = ""
        try:
            self._build(rc.embedder_type)
        except RateLimitExhausted:
            raise
        except Exception as e:  # noqa: BLE001
            if rc.embedder_type != "tfidf_char" and rc.embedder_fallback == "tfidf_char":
                self.note = f"{rc.embedder_type} unavailable ({type(e).__name__}: {str(e)[:160]}) -> fell back to tfidf_char"
                self.log(f"   [vector] WARNING: {self.note}")
                self._build("tfidf_char")
                self.used = "tfidf_char (fallback)"
            else:
                raise

    # prefixes required by nomic / bge style models
    def _prefixes(self):
        m = self.rc.embedder_model.lower()
        if "nomic" in m:
            return "search_document: ", "search_query: "
        if "bge" in m:
            return "", "Represent this sentence for searching relevant passages: "
        return "", ""

    def _build(self, kind: str):
        self.kind = kind
        if kind == "tfidf_char":
            from sklearn.feature_extraction.text import TfidfVectorizer

            self.vec = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), sublinear_tf=True)
            self.M = self.vec.fit_transform([" ".join(tokenize(t)) for t in self.raw])
        elif kind in ("groq", "ollama"):
            if self.llm is None or not hasattr(self.llm, "embed"):
                raise LLMError("no LLM client available for embeddings")
            dp, _ = self._prefixes()
            M = np.array(self.llm.embed([dp + t for t in self.raw], self.rc.embedder_model), dtype=np.float32)
            self.M = M / (np.linalg.norm(M, axis=1, keepdims=True) + 1e-9)
        elif kind == "sentence_transformers":
            from sentence_transformers import SentenceTransformer

            name = self.rc.embedder_model
            if name not in _ST_MODELS:
                _ST_MODELS[name] = SentenceTransformer(name, trust_remote_code=True)
            self.st = _ST_MODELS[name]
            dp, _ = self._prefixes()
            self.M = np.asarray(self.st.encode([dp + t for t in self.raw], normalize_embeddings=True))
        else:
            raise ValueError(kind)

    def scores(self, query: str) -> dict:
        if self.kind == "tfidf_char":
            q = self.vec.transform([" ".join(tokenize(query))])
            sims = (self.M @ q.T).toarray().ravel()
        else:
            _, qp = self._prefixes()
            if self.kind in ("groq", "ollama"):
                v = np.array(self.llm.embed([qp + query], self.rc.embedder_model)[0], dtype=np.float32)
                v = v / (np.linalg.norm(v) + 1e-9)
            else:
                v = np.asarray(self.st.encode([qp + query], normalize_embeddings=True))[0]
            sims = self.M @ v
        return {n: float(s) for n, s in zip(self.names, sims)}


# --------------------------------------------------------------------------- facade
def _rank(scores: dict) -> list:
    return sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))


def _minmax(scores: dict) -> dict:
    lo, hi = min(scores.values()), max(scores.values())
    return {k: (v - lo) / (hi - lo) if hi > lo else 0.0 for k, v in scores.items()}


class SchemaRetriever:
    """rank(question) -> [(table, score)] covering ALL tables, best first."""

    def __init__(self, schema: Schema, rc: RunConfig, llm=None, log=print):
        self.schema, self.rc = schema, rc
        self.vector = self.bm25 = None
        self.embedder_used = "-"
        docs = build_table_docs(schema)
        if rc.retriever in ("vector", "hybrid"):
            self.vector = VectorIndex(docs, rc, llm, log)
            self.embedder_used = self.vector.used
        if rc.retriever in ("hybrid",):
            self.bm25 = Bm25Index(docs, rc.bm25_k1, rc.bm25_b)

    def rank(self, question: str) -> list:
        rc = self.rc
        if rc.retriever == "full":
            return [(n, 0.0) for n in self.schema.names]
        v = self.vector.scores(question)
        if rc.retriever == "vector":
            return _rank(v)
        b = self.bm25.scores(question)
        if rc.fusion == "weighted":
            vn, bn = _minmax(v), _minmax(b)
            return _rank({n: rc.alpha * vn[n] + (1 - rc.alpha) * bn[n] for n in v})
        rv = {n: i for i, (n, _) in enumerate(_rank(v))}
        rb = {n: i for i, (n, _) in enumerate(_rank(b))}
        return _rank({n: 1 / (rc.rrf_k + rv[n] + 1) + 1 / (rc.rrf_k + rb[n] + 1) for n in v})


# --------------------------------------------------------------------------- reranker
def _parse_table_list(text: str, allowed: list) -> list:
    m = re.search(r"\{.*\}", text or "", re.S)
    names = []
    if m:
        try:
            data = json.loads(m.group(0))
            names = data.get("tables", []) if isinstance(data, dict) else []
        except json.JSONDecodeError:
            names = re.findall(r'"([A-Za-z_][\w ]*)"', m.group(0))
    lower = {a.lower(): a for a in allowed}
    out = []
    for n in names:
        real = lower.get(str(n).strip().lower())
        if real and real not in out:
            out.append(real)
    return out


def llm_rerank(question: str, candidates: list, schema: Schema, llm, keep: int):
    """Returns (selected_tables, LLMResult, fell_back)."""
    cand_txt = "\n".join(f"- {schema.compact(c)}" for c in candidates)
    msgs = [
        {"role": "system", "content": RERANK_SYSTEM},
        {"role": "user", "content": RERANK_USER.format(question=question, candidates=cand_txt, k=keep)},
    ]
    res = llm.chat(msgs, max_tokens=200)
    picked = _parse_table_list(res.text, candidates)[:keep]
    if not picked:
        return candidates[:keep], res, True
    return picked, res, False


# --------------------------------------------------------------------------- FK expansion
def fk_graph(schema: Schema, infer_shared_id: bool = True) -> dict:
    adj = {n: set() for n in schema.names}
    for t in schema.tables.values():
        for _, rt, _ in t.fks:
            if rt in adj and rt != t.name:
                adj[t.name].add(rt)
                adj[rt].add(t.name)
    if infer_shared_id:
        owners: dict = {}
        for t in schema.tables.values():
            for c, _ in t.columns:
                cl = c.lower()
                if cl != "id" and cl.endswith("id"):
                    owners.setdefault(cl, set()).add(t.name)
        for tabs in owners.values():
            if 1 < len(tabs) <= 6:  # ignore ubiquitous columns (would link everything)
                for a in tabs:
                    for b in tabs:
                        if a != b:
                            adj[a].add(b)
    return adj


def fk_expand(selected: list, schema: Schema, mode: str, max_added: int, infer_shared_id: bool = True):
    """Returns (tables_after, added)."""
    adj = fk_graph(schema, infer_shared_id)
    sel = set(selected)
    need = 2 if mode == "bridge" else 1
    scored = []
    for t in schema.names:
        if t in sel:
            continue
        links = len(adj[t] & sel)
        if links >= need:
            scored.append((-links, t))
    scored.sort()
    added = [t for _, t in scored[:max_added]]
    return list(selected) + added, added