"""Groq client: rate limiting, retries, on-disk cache, embeddings."""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path

from .config import LLMSettings


class LLMError(RuntimeError):
    pass


class RateLimitExhausted(LLMError):
    """Groq asked us to wait longer than max_wait_seconds (usually a daily cap)."""


@dataclass
class LLMResult:
    text: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency: float = 0.0
    cached: bool = False


# --------------------------------------------------------------------------- cache
class Cache:
    def __init__(self, path: Path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(path))
        self.conn.execute("CREATE TABLE IF NOT EXISTS kv (k TEXT PRIMARY KEY, v TEXT)")
        self.conn.commit()

    @staticmethod
    def key(payload) -> str:
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()

    def get(self, k):
        r = self.conn.execute("SELECT v FROM kv WHERE k=?", (k,)).fetchone()
        return json.loads(r[0]) if r else None

    def set(self, k, v):
        self.conn.execute("INSERT OR REPLACE INTO kv VALUES (?,?)", (k, json.dumps(v)))
        self.conn.commit()


# --------------------------------------------------------------------------- limiter
class RateLimiter:
    """Sliding 60-second window on requests and (estimated) tokens."""

    def __init__(self, rpm: int, tpm: int, sleep=time.sleep, now=time.monotonic):
        self.rpm, self.tpm = max(1, rpm), max(1, tpm)
        self.events: deque = deque()  # (t, tokens)
        self._sleep, self._now = sleep, now

    def acquire(self, est_tokens: int) -> None:
        while True:
            t = self._now()
            while self.events and t - self.events[0][0] >= 60:
                self.events.popleft()
            used = sum(tok for _, tok in self.events)
            if not self.events or (len(self.events) < self.rpm and used + est_tokens <= self.tpm):
                self.events.append((t, est_tokens))
                return
            self._sleep(max(0.2, 60 - (t - self.events[0][0]) + 0.1))


def parse_duration(text: str) -> float | None:
    parts = re.findall(r"([\d.]+)(ms|h|m|s)", text or "")
    if not parts:
        return None
    mult = {"ms": 0.001, "s": 1, "m": 60, "h": 3600}
    return sum(float(v) * mult[u] for v, u in parts)


def _retry_after(exc) -> float:
    try:
        ra = exc.response.headers.get("retry-after")
        if ra:
            return float(ra)
    except Exception:  # noqa: BLE001
        pass
    m = re.search(r"try again in ([0-9hms.]+)", str(exc))
    return parse_duration(m.group(1)) if m and parse_duration(m.group(1)) is not None else 20.0


# --------------------------------------------------------------------------- client
class GroqLLM:
    def __init__(self, settings: LLMSettings, cache: Cache | None = None):
        import os

        try:
            import groq
        except ImportError as e:  # pragma: no cover
            raise LLMError("The `groq` package is not installed: pip install -r requirements.txt") from e
        key = os.environ.get("GROQ_API_KEY")
        if not key:
            raise LLMError("GROQ_API_KEY is not set. Copy .env.example to .env and add your key.")
        self._groq = groq
        self.client = groq.Groq(api_key=key, max_retries=0, timeout=60)
        self.s = settings
        self.cache = cache if settings.use_cache else None
        self.limiter = RateLimiter(settings.rpm, settings.tpm)

    # ---- chat
    def chat(self, messages, max_tokens: int | None = None, model: str | None = None) -> LLMResult:
        model = model or self.s.model
        max_tokens = max_tokens or self.s.max_tokens
        payload = {"m": model, "t": self.s.temperature, "mt": max_tokens, "msgs": messages}
        ck = Cache.key(payload)
        if self.cache:
            hit = self.cache.get(ck)
            if hit:
                return LLMResult(hit["text"], hit["pt"], hit["ct"], hit["lat"], cached=True)
        est = int(len(json.dumps(messages)) / 3.3) + max_tokens // 2
        g = self._groq
        for attempt in range(self.s.max_retries + 1):
            self.limiter.acquire(est)
            t0 = time.monotonic()
            try:
                resp = self.client.chat.completions.create(
                    model=model, messages=messages, temperature=self.s.temperature, max_tokens=max_tokens
                )
            except g.RateLimitError as e:
                wait = _retry_after(e)
                if wait > self.s.max_wait_seconds:
                    raise RateLimitExhausted(
                        f"Groq rate limit: asked to wait {wait:.0f}s (> max_wait_seconds={self.s.max_wait_seconds}). "
                        "This is usually the daily cap. Progress is saved - re-run the same command later to resume."
                    ) from e
                time.sleep(wait + 1)
                continue
            except (g.APIConnectionError, g.APITimeoutError, g.InternalServerError):
                time.sleep(min(2**attempt, 30))
                continue
            except g.APIStatusError as e:
                raise LLMError(f"Groq API error {e.status_code}: {e}") from e
            lat = time.monotonic() - t0
            text = resp.choices[0].message.content or ""
            u = resp.usage
            res = LLMResult(text, getattr(u, "prompt_tokens", 0), getattr(u, "completion_tokens", 0), lat)
            if self.cache:
                self.cache.set(ck, {"text": text, "pt": res.prompt_tokens, "ct": res.completion_tokens, "lat": lat})
            return res
        raise LLMError("Groq request failed after all retries")

    # ---- embeddings
    def embed(self, texts: list, model: str) -> list:
        """Returns list of vectors. Cached per (model, text). Raises LLMError if endpoint unavailable."""
        out: list = [None] * len(texts)
        todo = []
        for i, t in enumerate(texts):
            hit = self.cache.get(Cache.key({"emb": model, "t": t})) if self.cache else None
            if hit is not None:
                out[i] = hit
            else:
                todo.append(i)
        g = self._groq
        for start in range(0, len(todo), 32):
            batch = todo[start : start + 32]
            for attempt in range(self.s.max_retries + 1):
                self.limiter.acquire(sum(len(texts[i]) for i in batch) // 3 + 1)
                try:
                    resp = self.client.embeddings.create(model=model, input=[texts[i] for i in batch])
                    break
                except g.RateLimitError as e:
                    wait = _retry_after(e)
                    if wait > self.s.max_wait_seconds:
                        raise RateLimitExhausted(f"Groq embeddings rate limit ({wait:.0f}s wait)") from e
                    time.sleep(wait + 1)
                except (g.APIConnectionError, g.APITimeoutError, g.InternalServerError):
                    time.sleep(min(2**attempt, 30))
                except g.APIStatusError as e:
                    raise LLMError(f"Groq embeddings error {e.status_code}: {e}") from e
                except AttributeError as e:
                    raise LLMError("Installed groq SDK has no embeddings API; upgrade: pip install -U groq") from e
            else:
                raise LLMError("Groq embeddings failed after all retries")
            for i, d in zip(batch, resp.data):
                out[i] = list(d.embedding)
                if self.cache:
                    self.cache.set(Cache.key({"emb": model, "t": texts[i]}), out[i])
        return out


# --------------------------------------------------------------------------- Ollama (local)
class OllamaLLM:
    """Same interface as GroqLLM, talking to a local Ollama server (REST API, stdlib only)."""

    def __init__(self, settings: LLMSettings, cache: Cache | None = None, log=print):
        self.s = settings
        o = settings.ollama or {}
        self.host = str(o.get("host", "http://localhost:11434")).rstrip("/")
        self.num_ctx = int(o.get("num_ctx", 8192))
        self.keep_alive = o.get("keep_alive", "30m")
        self.timeout = float(o.get("timeout_s", 600))
        self.seed = int(o.get("seed", 42))
        self.cache = cache if settings.use_cache else None
        self.log = log
        self._warned = False

    # ---- low level
    def _request(self, method: str, path: str, payload=None, timeout=None, model: str = ""):
        import socket
        import urllib.error
        import urllib.request

        data = json.dumps(payload).encode() if payload is not None else None
        req = urllib.request.Request(self.host + path, data=data, method=method,
                                     headers={"Content-Type": "application/json"})
        try:
            return urllib.request.urlopen(req, timeout=timeout or self.timeout)
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "ignore")[:300]
            if e.code == 404 and model:
                raise LLMError(f"Ollama does not have model {model!r} ({body}). Run:  ollama pull {model}") from e
            raise LLMError(f"Ollama HTTP {e.code} on {path}: {body}") from e
        except urllib.error.URLError as e:
            raise LLMError(f"Cannot reach Ollama at {self.host} ({e.reason}). Is it running? Start it with `ollama serve` "
                           f"(or open the Ollama app), or fix llm.ollama.host in the config.") from e
        except (socket.timeout, TimeoutError) as e:
            raise LLMError(f"Ollama did not answer within {self.timeout:.0f}s. Large models on CPU are slow: raise "
                           f"llm.ollama.timeout_s or use a smaller model.") from e

    def _json(self, method, path, payload=None, timeout=None, model=""):
        with self._request(method, path, payload, timeout, model) as r:
            return json.loads(r.read().decode("utf-8"))

    def list_models(self) -> list:
        return [m["name"] for m in self._json("GET", "/api/tags", timeout=10).get("models", [])]

    # ---- chat
    def chat(self, messages, max_tokens: int | None = None, model: str | None = None) -> LLMResult:
        model = model or self.s.model
        max_tokens = max_tokens or self.s.max_tokens
        payload = {"p": "ollama", "m": model, "t": self.s.temperature, "mt": max_tokens, "ctx": self.num_ctx,
                   "seed": self.seed, "msgs": messages}
        ck = Cache.key(payload)
        if self.cache:
            hit = self.cache.get(ck)
            if hit:
                return LLMResult(hit["text"], hit["pt"], hit["ct"], hit["lat"], cached=True)
        est_prompt = int(sum(len(m["content"]) for m in messages) / 3.3)
        if est_prompt > 0.9 * self.num_ctx and not self._warned:
            self._warned = True
            self.log(f"   [ollama] WARNING: prompt (~{est_prompt} tokens) is close to num_ctx={self.num_ctx}; Ollama silently "
                     f"truncates long prompts. Raise llm.ollama.num_ctx (more RAM/VRAM) or reduce k.")
        t0 = time.monotonic()
        d = self._json("POST", "/api/chat", {
            "model": model, "messages": messages, "stream": False, "keep_alive": self.keep_alive,
            "options": {"temperature": self.s.temperature, "num_predict": max_tokens, "num_ctx": self.num_ctx, "seed": self.seed},
        }, model=model)
        lat = time.monotonic() - t0
        text = (d.get("message") or {}).get("content", "")
        # Ollama reuses its prompt cache, so `prompt_eval_count` under-reports repeated prefixes (e.g. the same full
        # schema). To keep token comparisons between configs fair we use a character-based estimate for the prompt.
        res = LLMResult(text, est_prompt, int(d.get("eval_count", 0)), lat)
        if self.cache:
            self.cache.set(ck, {"text": text, "pt": res.prompt_tokens, "ct": res.completion_tokens, "lat": lat})
        return res

    # ---- embeddings
    def embed(self, texts: list, model: str) -> list:
        out: list = [None] * len(texts)
        todo = []
        for i, t in enumerate(texts):
            hit = self.cache.get(Cache.key({"emb": model, "p": "ollama", "t": t})) if self.cache else None
            if hit is not None:
                out[i] = hit
            else:
                todo.append(i)
        for start in range(0, len(todo), 32):
            batch = todo[start : start + 32]
            d = self._json("POST", "/api/embed", {"model": model, "input": [texts[i] for i in batch],
                                                  "keep_alive": self.keep_alive}, model=model)
            embs = d.get("embeddings") or []
            if len(embs) != len(batch):
                raise LLMError(f"Ollama /api/embed returned {len(embs)} vectors for {len(batch)} inputs "
                               f"(is {model!r} an embedding model? try: ollama pull nomic-embed-text)")
            for i, e in zip(batch, embs):
                out[i] = list(e)
                if self.cache:
                    self.cache.set(Cache.key({"emb": model, "p": "ollama", "t": texts[i]}), out[i])
        return out


def make_llm(settings: LLMSettings, cache: Cache | None = None, log=print):
    """Factory used by the CLI: llm.provider decides the backend."""
    if settings.provider == "ollama":
        return OllamaLLM(settings, cache, log)
    return GroqLLM(settings, cache)