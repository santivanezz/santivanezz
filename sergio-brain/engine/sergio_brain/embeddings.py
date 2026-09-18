"""Embedding providers and the vector index.

Providers:
  hashed  - deterministic feature-hashing of word/char n-grams. No model, no
            network, works offline out of the box. Lower quality, but honest.
  local   - sentence-transformers (multilingual MiniLM by default). Best default.
  ollama  - Ollama /api/embeddings
  openai  - OpenAI embeddings (cloud; blocked in LOCAL_ONLY mode)

Vectors are stored in SQLite as float32 blobs and loaded into a numpy matrix
for cosine search. For a personal vault (thousands of notes) this is fast and
needs no FAISS/LanceDB. Swap ``VectorIndex`` if the vault grows past ~500k chunks.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import time
import urllib.request
from typing import Iterable

import numpy as np

from .config import Config
from .db import Database

_TOKEN_RE = re.compile(r"[a-záéíóúñü0-9]+", re.IGNORECASE)
_STOP = set("""a al algo ante bajo cabe como con contra de del desde durante e el ella ellas ellos en entre era es esa
ese eso esta estas este esto estos fue ha han hay la las le les lo los mas más me mi mis muy ni no nos o os para pero
por que qué se sin so sobre su sus te tras tu tus un una unas uno unos y ya the a an and or of to in on for is are was
were be been it its this that these those with as by at from i you he she we they not but if then than so""".split())


def tokenize(text: str) -> list[str]:
    return [t.lower() for t in _TOKEN_RE.findall(text)]


def content_words(text: str) -> list[str]:
    return [t for t in tokenize(text) if t not in _STOP and len(t) > 2]


class EmbeddingProvider:
    name = "base"
    model = ""
    dim = 0
    cloud = False

    def embed(self, texts: list[str]) -> np.ndarray:
        raise NotImplementedError

    def embed_one(self, text: str) -> np.ndarray:
        return self.embed([text])[0]


class HashedEmbeddingProvider(EmbeddingProvider):
    """Feature hashing over word unigrams, bigrams and character trigrams."""

    name = "hashed"
    cloud = False

    def __init__(self, dim: int = 512):
        self.dim = dim
        self.model = f"hashed-ngram-{dim}"

    @staticmethod
    def _h(feature: str, dim: int) -> tuple[int, float]:
        d = hashlib.blake2b(feature.encode("utf-8"), digest_size=8).digest()
        idx = int.from_bytes(d[:4], "little") % dim
        sign = 1.0 if d[4] & 1 else -1.0
        return idx, sign

    def embed(self, texts: list[str]) -> np.ndarray:
        out = np.zeros((len(texts), self.dim), dtype=np.float32)
        for i, text in enumerate(texts):
            words = content_words(text)
            feats: dict[str, float] = {}
            for w in words:
                feats[f"w:{w}"] = feats.get(f"w:{w}", 0.0) + 1.0
                for j in range(len(w) - 2):
                    tri = w[j:j + 3]
                    feats[f"c:{tri}"] = feats.get(f"c:{tri}", 0.0) + 0.35
            for a, b in zip(words, words[1:]):
                feats[f"b:{a}_{b}"] = feats.get(f"b:{a}_{b}", 0.0) + 0.8
            for f, weight in feats.items():
                idx, sign = self._h(f, self.dim)
                out[i, idx] += sign * math.log1p(weight)
            norm = np.linalg.norm(out[i])
            if norm > 0:
                out[i] /= norm
        return out


class SentenceTransformerProvider(EmbeddingProvider):
    name = "local"
    cloud = False

    def __init__(self, model: str):
        from sentence_transformers import SentenceTransformer  # optional dependency
        self.model = model
        self._m = SentenceTransformer(model)
        self.dim = int(self._m.get_sentence_embedding_dimension())

    def embed(self, texts: list[str]) -> np.ndarray:
        v = self._m.encode(texts, normalize_embeddings=True, batch_size=32, show_progress_bar=False)
        return np.asarray(v, dtype=np.float32)


class OllamaEmbeddingProvider(EmbeddingProvider):
    name = "ollama"
    cloud = False

    def __init__(self, url: str, model: str):
        self.url = url.rstrip("/")
        self.model = model
        self.dim = 0

    def embed(self, texts: list[str]) -> np.ndarray:
        vecs = []
        for t in texts:
            req = urllib.request.Request(self.url + "/api/embeddings", data=json.dumps({"model": self.model, "prompt": t}).encode(),
                                         headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=120) as r:
                data = json.loads(r.read())
            vecs.append(np.asarray(data["embedding"], dtype=np.float32))
        arr = np.vstack(vecs)
        self.dim = arr.shape[1]
        norms = np.linalg.norm(arr, axis=1, keepdims=True)
        norms[norms == 0] = 1
        return arr / norms


class OpenAIEmbeddingProvider(EmbeddingProvider):
    name = "openai"
    cloud = True

    def __init__(self, model: str):
        import os
        self.model = model
        self.key = os.environ.get("OPENAI_API_KEY", "")
        if not self.key:
            raise RuntimeError("OPENAI_API_KEY not set")
        self.dim = 0

    def embed(self, texts: list[str]) -> np.ndarray:
        req = urllib.request.Request("https://api.openai.com/v1/embeddings",
                                     data=json.dumps({"model": self.model, "input": texts}).encode(),
                                     headers={"Content-Type": "application/json", "Authorization": f"Bearer {self.key}"})
        with urllib.request.urlopen(req, timeout=120) as r:
            data = json.loads(r.read())
        arr = np.asarray([d["embedding"] for d in data["data"]], dtype=np.float32)
        self.dim = arr.shape[1]
        norms = np.linalg.norm(arr, axis=1, keepdims=True)
        norms[norms == 0] = 1
        return arr / norms


def build_embedding_provider(cfg: Config, log=None) -> EmbeddingProvider:
    choice = cfg.ai.embedding_provider
    mode = cfg.ai.mode.upper()
    if choice in ("auto", "local"):
        try:
            p = SentenceTransformerProvider(cfg.ai.embedding_model)
            return p
        except Exception as exc:  # noqa: BLE001 - optional dependency may be missing
            if choice == "local" and log:
                log.warning("local embeddings unavailable (%s); falling back to hashed", exc)
            return HashedEmbeddingProvider()
    if choice == "ollama":
        return OllamaEmbeddingProvider(cfg.ai.ollama_url, cfg.ai.ollama_embedding_model)
    if choice == "openai":
        if mode == "LOCAL_ONLY":
            raise RuntimeError("openai embeddings requested but ai.mode is LOCAL_ONLY")
        return OpenAIEmbeddingProvider(cfg.ai.openai_embedding_model)
    return HashedEmbeddingProvider()


def to_blob(v: np.ndarray) -> bytes:
    return np.asarray(v, dtype=np.float32).tobytes()


def from_blob(b: bytes, dim: int) -> np.ndarray:
    return np.frombuffer(b, dtype=np.float32, count=dim)


class VectorIndex:
    """In-memory cosine index backed by the embeddings table."""

    def __init__(self, db: Database):
        self.db = db
        self._ids: np.ndarray | None = None
        self._matrix: np.ndarray | None = None
        self._loaded_at = 0.0
        self._dirty = True

    def invalidate(self) -> None:
        self._dirty = True

    def _load(self) -> None:
        rows = self.db.query("SELECT chunk_id, dim, vector FROM embeddings")
        if not rows:
            self._ids = np.zeros((0,), dtype=np.int64)
            self._matrix = np.zeros((0, 1), dtype=np.float32)
        else:
            dim = rows[0]["dim"]
            usable = [r for r in rows if r["dim"] == dim]
            self._ids = np.asarray([r["chunk_id"] for r in usable], dtype=np.int64)
            self._matrix = np.vstack([from_blob(r["vector"], dim) for r in usable])
        self._dirty = False
        self._loaded_at = time.time()

    def search(self, query_vec: np.ndarray, k: int = 20, exclude_chunk_ids: Iterable[int] = ()) -> list[tuple[int, float]]:
        if self._dirty or self._matrix is None:
            self._load()
        assert self._matrix is not None and self._ids is not None
        if self._matrix.shape[0] == 0 or self._matrix.shape[1] != query_vec.shape[0]:
            return []
        scores = self._matrix @ query_vec.astype(np.float32)
        excl = set(exclude_chunk_ids)
        order = np.argsort(-scores)
        out: list[tuple[int, float]] = []
        for idx in order:
            cid = int(self._ids[idx])
            if cid in excl:
                continue
            out.append((cid, float(scores[idx])))
            if len(out) >= k:
                break
        return out

    def vector_for(self, chunk_id: int) -> np.ndarray | None:
        row = self.db.one("SELECT dim, vector FROM embeddings WHERE chunk_id=?", (chunk_id,))
        return from_blob(row["vector"], row["dim"]) if row else None

    def size(self) -> int:
        if self._dirty or self._matrix is None:
            self._load()
        return int(self._ids.shape[0]) if self._ids is not None else 0
