"""Central configuration loader. Everything is driven by config.yaml."""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Optional

import yaml

DEFAULT_CONFIG_FILE = "config.yaml"


@dataclass
class LLMSettings:
    provider: str = "groq"           # groq | ollama
    ollama: dict = field(default_factory=dict)   # host, num_ctx, keep_alive, timeout_s, seed (see config.ollama.yaml)
    model: str = "llama-3.1-8b-instant"
    temperature: float = 0.0
    max_tokens: int = 512
    rpm: int = 25
    tpm: int = 5500
    max_retries: int = 6
    max_wait_seconds: int = 90
    use_cache: bool = True


@dataclass
class DatasetSettings:
    db_id: str = "auto"
    min_tables: int = 20
    n_questions: int = 50
    seed: int = 42
    question_files: list = field(default_factory=lambda: ["train_spider.json", "train_others.json", "dev.json"])
    bucket_mix: dict = field(default_factory=lambda: {1: 0.3, 2: 0.4, 3: 0.3})
    exclude_empty_gold: bool = True


@dataclass
class Paths:
    spider_dir: Path
    data_dir: Path
    results_dir: Path
    cache_path: Path
    report_path: Path


@dataclass
class RunConfig:
    """One fully-resolved configuration (defaults + overrides)."""
    name: str
    description: str = ""
    retriever: str = "full"          # full | vector | hybrid
    k: int = 8
    rerank: bool = False
    candidates_k: int = 15
    fk_expand: bool = False
    fk_mode: str = "bridge"          # bridge | neighbors
    fk_max_added: int = 3
    fk_infer_shared_id: bool = True
    # --- error-fix / retry loop (max_retries = 0 disables it) ---
    max_retries: int = 0
    retry_on_empty: bool = True          # an empty result set counts as a failure
    retry_judge: bool = True             # an LLM judge may reject a result that ran fine (1 extra LLM call per attempt)
    retry_schema: str = "hybrid_rerank"  # how the schema changes on a retry: none | neighbors | hybrid_rerank
    retry_full_schema_last: bool = True  # the LAST allowed retry gets the full schema
    judge_rows: int = 5                  # result rows shown to the judge
    fusion: str = "rrf"              # rrf | weighted
    rrf_k: int = 60
    alpha: float = 0.5
    embedder_type: str = "groq"      # groq | tfidf_char | sentence_transformers
    embedder_model: str = "nomic-embed-text-v1_5"
    embedder_fallback: str = "tfidf_char"
    bm25_k1: float = 1.5
    bm25_b: float = 0.75
    model: Optional[str] = None      # per-config LLM override

    def validate(self) -> None:
        if self.retriever not in ("full", "vector", "hybrid"):
            raise ValueError(f"[{self.name}] retriever must be full|vector|hybrid, got {self.retriever!r}")
        if self.retriever == "full" and (self.rerank or self.fk_expand):
            raise ValueError(f"[{self.name}] rerank/fk_expand make no sense with retriever: full")
        if self.max_retries < 0:
            raise ValueError(f"[{self.name}] max_retries must be >= 0")
        if self.retry_schema not in ("none", "neighbors", "hybrid_rerank"):
            raise ValueError(f"[{self.name}] retry_schema must be none|neighbors|hybrid_rerank")
        if self.max_retries and self.retry_schema == "hybrid_rerank" and self.candidates_k < self.k:
            raise ValueError(f"[{self.name}] candidates_k ({self.candidates_k}) must be >= k ({self.k}) for retry_schema: hybrid_rerank")
        if self.fusion not in ("rrf", "weighted"):
            raise ValueError(f"[{self.name}] fusion must be rrf|weighted")
        if self.fk_mode not in ("bridge", "neighbors"):
            raise ValueError(f"[{self.name}] fk_mode must be bridge|neighbors")
        if self.embedder_type not in ("groq", "ollama", "tfidf_char", "sentence_transformers"):
            raise ValueError(f"[{self.name}] unknown embedder_type {self.embedder_type!r}")
        if self.embedder_fallback not in ("none", "tfidf_char"):
            raise ValueError(f"[{self.name}] embedder_fallback must be none|tfidf_char")
        if self.rerank and self.candidates_k < self.k:
            raise ValueError(f"[{self.name}] candidates_k ({self.candidates_k}) must be >= k ({self.k})")


@dataclass
class Settings:
    config_file: Path
    paths: Paths
    dataset: DatasetSettings
    llm: LLMSettings
    exec_timeout_s: float
    configs: dict  # name -> RunConfig
    raw: dict = field(default_factory=dict)  # merged YAML (after `extends`)

    def get(self, name: str) -> RunConfig:
        if name not in self.configs:
            raise KeyError(f"Unknown config {name!r}. Available: {', '.join(self.configs)}")
        return self.configs[name]


def _pick(cls, data: dict, where: str):
    valid = {f.name for f in fields(cls)}
    bad = set(data) - valid
    if bad:
        raise ValueError(f"Unknown key(s) in config.yaml [{where}]: {sorted(bad)}. Valid: {sorted(valid)}")
    return cls(**data)


def _deep_merge(a: dict, b: dict) -> dict:
    out = dict(a)
    for k, v in b.items():
        out[k] = _deep_merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def _load_raw(path: Path, _seen: tuple = ()) -> dict:
    """Load YAML; `extends: other.yaml` deep-merges this file over the base file."""
    path = Path(path).resolve()
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")
    if path in _seen:
        raise ValueError(f"Circular `extends` involving {path}")
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    base = raw.pop("extends", None)
    if base:
        raw = _deep_merge(_load_raw(path.parent / base, _seen + (path,)), raw)
    return raw


def load_settings(path: str | Path = DEFAULT_CONFIG_FILE, spider_dir: str | None = None) -> Settings:
    path = Path(path).resolve()
    raw = _load_raw(path)
    root = path.parent

    p = raw.get("paths", {})

    def rp(key, default):
        return (root / p.get(key, default)).resolve()

    paths = Paths(
        spider_dir=Path(spider_dir).resolve() if spider_dir else rp("spider_dir", "./spider"),
        data_dir=rp("data_dir", "./data"),
        results_dir=rp("results_dir", "./results"),
        cache_path=rp("cache_path", "./.cache/llm_cache.sqlite"),
        report_path=rp("report_path", "./report.md"),
    )

    ds = _pick(DatasetSettings, raw.get("dataset", {}), "dataset")
    ds.bucket_mix = {int(k): float(v) for k, v in ds.bucket_mix.items()}
    llm = _pick(LLMSettings, raw.get("llm", {}), "llm")
    if llm.provider not in ("groq", "ollama"):
        raise ValueError(f"llm.provider must be groq|ollama, got {llm.provider!r}")
    exec_timeout = float(raw.get("execution", {}).get("timeout_s", 15))

    defaults = raw.get("defaults", {}) or {}
    configs = {}
    for name, overrides in (raw.get("configs") or {}).items():
        merged = {**defaults, **(overrides or {})}
        merged["name"] = name
        rc = _pick(RunConfig, merged, f"configs.{name}")
        rc.validate()
        configs[name] = rc
    if not configs:
        raise ValueError("config.yaml has no `configs:` section")
    return Settings(path, paths, ds, llm, exec_timeout, configs, raw)


def fingerprint(rc: RunConfig, llm: LLMSettings, gold_hash: str) -> str:
    """Hash of everything that affects results; used to decide if saved results can be resumed."""
    d = asdict(rc)
    d.pop("description", None)
    d["llm_model"] = rc.model or llm.model
    d["provider"] = llm.provider
    d["temperature"] = llm.temperature
    d["max_tokens"] = llm.max_tokens
    d["gold"] = gold_hash
    return hashlib.sha1(json.dumps(d, sort_keys=True).encode()).hexdigest()[:16]