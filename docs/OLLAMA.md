"""`ollama-setup`: check the server, pull the models named in the config, smoke-test chat + embeddings."""
from __future__ import annotations

import json
import time

from .config import Settings
from .llm import LLMError, OllamaLLM


def _norm(name: str) -> str:
    return name if ":" in name else name + ":latest"


def needed_models(settings: Settings) -> list:
    models = [settings.llm.model]
    for rc in settings.configs.values():
        if rc.model:
            models.append(rc.model)
        if rc.embedder_type == "ollama" and rc.retriever in ("vector", "hybrid"):
            models.append(rc.embedder_model)
    seen, out = set(), []
    for m in models:
        if _norm(m) not in seen:
            seen.add(_norm(m))
            out.append(m)
    return out


def pull(llm: OllamaLLM, model: str, log=print) -> None:
    log(f"  pulling {model} (this can take a few minutes the first time) ...")
    last_pct = -10
    with llm._request("POST", "/api/pull", {"model": model, "stream": True}, timeout=3600) as r:
        for line in r:
            if not line.strip():
                continue
            d = json.loads(line)
            if "error" in d:
                raise LLMError(f"pull failed: {d['error']}")
            if d.get("total") and d.get("completed") is not None:
                pct = int(100 * d["completed"] / d["total"])
                if pct >= last_pct + 10:
                    last_pct = pct
                    log(f"    {pct}%")
            elif d.get("status") == "success":
                log("    done")


def setup(settings: Settings, do_pull: bool = True, log=print) -> bool:
    llm = OllamaLLM(settings.llm, cache=None, log=log)
    log(f"Ollama server: {llm.host}")
    try:
        installed = {_norm(m) for m in llm.list_models()}
    except LLMError as e:
        log(f"  NOT REACHABLE: {e}")
        return False
    log(f"  reachable; {len(installed)} model(s) installed")
    ok = True
    for m in needed_models(settings):
        if _norm(m) in installed:
            log(f"  [ok]      {m}")
            continue
        if not do_pull:
            log(f"  [missing] {m}   ->  ollama pull {m}")
            ok = False
            continue
        try:
            pull(llm, m, log)
        except LLMError as e:
            log(f"  [failed]  {m}: {e}")
            ok = False
    if not ok:
        return False
    log("Smoke test (the first call loads the model into memory and can take a while) ...")
    t0 = time.monotonic()
    r = llm.chat([{"role": "user", "content": "Reply with the single word: pong"}], max_tokens=8)
    log(f"  chat  OK  {settings.llm.model}: {r.text.strip()!r}  ({time.monotonic() - t0:.1f}s)")
    emb_models = [rc.embedder_model for rc in settings.configs.values() if rc.embedder_type == "ollama"]
    if emb_models:
        v = llm.embed(["ping"], emb_models[0])
        log(f"  embed OK  {emb_models[0]}: {len(v[0])} dimensions")
    log("Setup complete.")
    return True