import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from nl2sql.config import LLMSettings, load_settings
from nl2sql.llm import Cache, LLMError, OllamaLLM, make_llm
from nl2sql.ollama_setup import needed_models, setup

ROOT = Path(__file__).resolve().parents[1]
CALLS = {"chat": 0, "embed": 0, "pull": 0}
INSTALLED = {"qwen2.5-coder:7b"}


class Fake(BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def _send(self, code, obj, raw=None):
        body = raw if raw is not None else json.dumps(obj).encode()
        self.send_response(code); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)

    def do_GET(self):
        if self.path == "/api/tags":
            self._send(200, {"models": [{"name": n} for n in sorted(INSTALLED)]})
        else:
            self._send(404, {})

    def do_POST(self):
        b = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if self.path == "/api/chat":
            CALLS["chat"] += 1
            if b["model"] == "ghost":
                return self._send(404, {"error": "model 'ghost' not found"})
            assert b["options"]["num_ctx"] == 4096 and b["stream"] is False
            self._send(200, {"message": {"content": "```sql\nSELECT 1\n```"}, "prompt_eval_count": 1, "eval_count": 7})
        elif self.path == "/api/embed":
            CALLS["embed"] += 1
            self._send(200, {"embeddings": [[1.0, 0.0, float(len(t))] for t in b["input"]]})
        elif self.path == "/api/pull":
            CALLS["pull"] += 1
            INSTALLED.add(b["model"] if ":" in b["model"] else b["model"] + ":latest")
            lines = [{"status": "pulling manifest"}, {"status": "pulling x", "total": 100, "completed": 50},
                     {"status": "pulling x", "total": 100, "completed": 100}, {"status": "success"}]
            self._send(200, None, raw="".join(json.dumps(l) + "\n" for l in lines).encode())


@pytest.fixture()
def server():
    INSTALLED.clear(); INSTALLED.add("qwen2.5-coder:7b")
    for k in CALLS: CALLS[k] = 0
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Fake)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def _llm(host, cache=None):
    return OllamaLLM(LLMSettings(provider="ollama", model="qwen2.5-coder:7b",
                                 ollama={"host": host, "num_ctx": 4096, "timeout_s": 5}), cache)


def test_chat_embed_and_cache(server, tmp_path):
    llm = _llm(server, Cache(tmp_path / "c.sqlite"))
    msgs = [{"role": "user", "content": "hello world"}]
    r = llm.chat(msgs)
    assert "SELECT 1" in r.text and r.completion_tokens == 7 and r.prompt_tokens == int(len("hello world") / 3.3)
    assert llm.chat(msgs).cached and CALLS["chat"] == 1
    v = llm.embed(["a", "bbb"], "nomic-embed-text")
    assert v == [[1.0, 0.0, 1.0], [1.0, 0.0, 3.0]]
    llm.embed(["a"], "nomic-embed-text")
    assert CALLS["embed"] == 1                                   # second call served from cache


def test_clear_errors(server):
    with pytest.raises(LLMError, match="ollama pull ghost"):
        _llm(server).chat([{"role": "user", "content": "x"}], model="ghost")
    with pytest.raises(LLMError, match="ollama serve"):
        _llm("http://127.0.0.1:9").chat([{"role": "user", "content": "x"}])


def test_make_llm_picks_provider():
    assert isinstance(make_llm(LLMSettings(provider="ollama")), OllamaLLM)


def test_config_extends_and_models():
    s = load_settings(ROOT / "config.ollama.yaml")
    assert s.llm.provider == "ollama" and s.llm.ollama["num_ctx"] == 8192
    assert len(s.configs) == 9                                    # inherited from config.yaml
    assert s.paths.results_dir.name == "results_ollama" and s.paths.data_dir.name == "data"
    assert needed_models(s) == ["qwen2.5-coder:7b", "nomic-embed-text"]
    assert s.raw["defaults"]["embedder_type"] == "ollama" and s.raw["defaults"]["k"] == 8


def test_setup_pulls_missing_and_smoke_tests(server):
    s = load_settings(ROOT / "config.ollama.yaml")
    s.llm.ollama.update(host=server, num_ctx=4096)
    out = []
    assert setup(s, do_pull=False, log=out.append) is False and any("ollama pull nomic-embed-text" in l for l in out)
    out.clear()
    assert setup(s, do_pull=True, log=out.append) is True
    assert CALLS["pull"] == 1 and any("chat  OK" in l for l in out) and any("embed OK" in l for l in out)