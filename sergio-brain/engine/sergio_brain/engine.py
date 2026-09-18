"""The Engine facade: wires config, DB, vault, providers and subsystems together."""
from __future__ import annotations

import logging
from pathlib import Path

from .config import Config, load_config
from .db import Database
from .embeddings import VectorIndex, build_embedding_provider, EmbeddingProvider
from .events import EventBus, JobQueue
from .logging_setup import setup_logging
from .providers import build_llm_provider, CostTracker, LLMProvider
from .vault import Vault
from .writer import VaultWriter


class Engine:
    def __init__(self, cfg: Config | None = None, config_path: Path | None = None):
        self.cfg = cfg or load_config(config_path)
        if not self.cfg.vault_path:
            raise RuntimeError("vault_path is not configured. Run: sergio-brain doctor / sergio-brain init --vault <path>")
        if not self.cfg.vault.exists():
            raise RuntimeError(f"Vault not found: {self.cfg.vault}")
        self.cfg.ensure_dirs()
        self.log: logging.Logger = setup_logging(self.cfg.log_dir)
        self.db = Database(self.cfg.db_path)
        self.vault = Vault(self.cfg)
        self.writer = VaultWriter(self.cfg)
        self.events = EventBus(self.db)
        self.jobs = JobQueue(self.db)
        self.vectors = VectorIndex(self.db)
        self.costs = CostTracker(self.db, self.cfg)
        self._embedder: EmbeddingProvider | None = None
        self._llm: LLMProvider | None = None
        # lazy subsystems
        from .indexer import Indexer
        from .memory import MemoryEngine
        from .graph import GraphEngine
        from .search import HybridSearch
        from .rag import Assistant
        from .intelligence import Intelligence
        from .reviews import Reviews
        from .inbox import Inbox
        from .backup import BackupManager
        self.indexer = Indexer(self)
        self.memory = MemoryEngine(self)
        self.graph = GraphEngine(self)
        self.search = HybridSearch(self)
        self.assistant = Assistant(self)
        self.intel = Intelligence(self)
        self.reviews = Reviews(self)
        self.inbox = Inbox(self)
        self.backups = BackupManager(self)
        self.indexer.register_jobs()

    @property
    def embedder(self) -> EmbeddingProvider:
        if self._embedder is None:
            self._embedder = build_embedding_provider(self.cfg, self.log)
            self.log.info("embedding provider: %s (%s)", self._embedder.name, self._embedder.model)
        return self._embedder

    @property
    def llm(self) -> LLMProvider:
        if self._llm is None:
            self._llm = build_llm_provider(self.cfg)
        return self._llm

    def llm_allowed_for(self, privacy_levels: list[str]) -> bool:
        """Cloud providers never see SENSITIVE (or configured) content."""
        if not self.llm.cloud:
            return True
        blocked = {x.upper() for x in self.cfg.privacy.cloud_blocked_levels}
        return not any(p.upper() in blocked for p in privacy_levels)

    def close(self) -> None:
        self.db.close()
