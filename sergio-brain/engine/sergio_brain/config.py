"""Configuration for SERGIO BRAIN.

The configuration lives in a TOML file. Default location:
    Windows: %APPDATA%\\SergioBrain\\config.toml
    Linux/macOS: ~/.config/sergio-brain/config.toml

Environment variable SERGIO_BRAIN_CONFIG overrides the path.
Secrets (API keys) are NEVER stored in this file; they are read from
environment variables (ANTHROPIC_API_KEY, OPENAI_API_KEY).
"""
from __future__ import annotations

import os
import sys
import tomllib
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

APP_NAME = "SergioBrain"


def default_config_dir() -> Path:
    if os.environ.get("SERGIO_BRAIN_HOME"):
        return Path(os.environ["SERGIO_BRAIN_HOME"])
    if sys.platform.startswith("win"):
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
        return base / APP_NAME
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "sergio-brain"


def default_config_path() -> Path:
    if os.environ.get("SERGIO_BRAIN_CONFIG"):
        return Path(os.environ["SERGIO_BRAIN_CONFIG"])
    return default_config_dir() / "config.toml"


@dataclass
class PrivacyConfig:
    # Notes with any of these tags/frontmatter values are never indexed.
    do_not_index_tags: list[str] = field(default_factory=lambda: ["do_not_index", "private/no-index"])
    # Notes with these tags are indexed locally but never sent to a cloud LLM.
    do_not_send_to_cloud_tags: list[str] = field(default_factory=lambda: ["sensitive", "do_not_send_to_cloud"])
    # Folders (relative to the vault) that are never processed.
    do_not_process_folders: list[str] = field(default_factory=lambda: [".obsidian", ".trash", ".git", "SERGIO BRAIN/Backups"])
    # Default privacy level for notes without explicit `privacy:` frontmatter.
    default_level: str = "PERSONAL"  # PUBLIC | PERSONAL | WORK | SENSITIVE
    # Privacy levels that are never sent to a cloud provider.
    cloud_blocked_levels: list[str] = field(default_factory=lambda: ["SENSITIVE"])
    # Redact detected secrets before sending anything to an LLM.
    redact_secrets: bool = True


@dataclass
class AIConfig:
    # LOCAL_ONLY: never call a cloud API. HYBRID: local embeddings, cloud LLM if configured. CLOUD: cloud for both.
    mode: str = "LOCAL_ONLY"
    llm_provider: str = "none"          # none | claude | openai | ollama
    llm_model: str = "claude-opus-5"
    ollama_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.1"
    openai_model: str = "gpt-4o-mini"
    embedding_provider: str = "auto"     # auto | hashed | local | ollama | openai
    embedding_model: str = "paraphrase-multilingual-MiniLM-L12-v2"
    ollama_embedding_model: str = "nomic-embed-text"
    openai_embedding_model: str = "text-embedding-3-small"
    max_context_chars: int = 12000
    # Estimated USD per 1M tokens for cost display (input, output). Adjust per provider.
    cost_input_per_million: float = 5.0
    cost_output_per_million: float = 25.0


@dataclass
class ServerConfig:
    host: str = "127.0.0.1"
    port: int = 8765
    # Optional shared token; the Obsidian plugin sends it as X-Brain-Token.
    token: str = ""


@dataclass
class VaultLayout:
    brain_folder: str = "SERGIO BRAIN"     # generated notes live here (dashboard, reviews)
    inbox_folder: str = "SERGIO BRAIN/Inbox"
    daily_folder: str = "SERGIO BRAIN/Daily"
    reviews_folder: str = "SERGIO BRAIN/Reviews"
    imports_folder: str = "SERGIO BRAIN/Imports"
    backups_folder: str = "SERGIO BRAIN/Backups"
    daily_note_format: str = "%Y-%m-%d"


@dataclass
class Config:
    vault_path: str = ""
    data_dir: str = ""
    privacy: PrivacyConfig = field(default_factory=PrivacyConfig)
    ai: AIConfig = field(default_factory=AIConfig)
    server: ServerConfig = field(default_factory=ServerConfig)
    layout: VaultLayout = field(default_factory=VaultLayout)
    watch_poll_seconds: float = 2.0
    debounce_seconds: float = 1.5
    chunk_size: int = 900
    chunk_overlap: int = 120
    stale_days: int = 90
    outdated_days: int = 180
    language: str = "es"

    # ----- paths -----
    @property
    def vault(self) -> Path:
        return Path(self.vault_path).expanduser()

    @property
    def data(self) -> Path:
        if self.data_dir:
            return Path(self.data_dir).expanduser()
        return default_config_dir() / "data"

    @property
    def db_path(self) -> Path:
        return self.data / "sergio_brain.sqlite"

    @property
    def log_dir(self) -> Path:
        return self.data / "logs"

    @property
    def backup_dir(self) -> Path:
        return self.data / "backups"

    def ensure_dirs(self) -> None:
        for p in (self.data, self.log_dir, self.backup_dir):
            p.mkdir(parents=True, exist_ok=True)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _merge(dc: Any, data: dict[str, Any]) -> Any:
    for key, value in data.items():
        if not hasattr(dc, key):
            continue
        current = getattr(dc, key)
        if hasattr(current, "__dataclass_fields__") and isinstance(value, dict):
            _merge(current, value)
        else:
            setattr(dc, key, value)
    return dc


def load_config(path: Path | None = None) -> Config:
    path = path or default_config_path()
    cfg = Config()
    if path.exists():
        with open(path, "rb") as fh:
            data = tomllib.load(fh)
        _merge(cfg, data)
    env_vault = os.environ.get("SERGIO_BRAIN_VAULT")
    if env_vault:
        cfg.vault_path = env_vault
    env_data = os.environ.get("SERGIO_BRAIN_DATA")
    if env_data:
        cfg.data_dir = env_data
    return cfg


def _toml_value(v: Any) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return repr(v)
    if isinstance(v, list):
        return "[" + ", ".join(_toml_value(x) for x in v) + "]"
    s = str(v).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{s}"'


def dump_config(cfg: Config) -> str:
    """Serialize config to TOML (small hand-rolled writer; stdlib has no TOML writer)."""
    out: list[str] = ["# SERGIO BRAIN configuration. Secrets go in environment variables, never here.", ""]
    d = cfg.to_dict()
    scalars = {k: v for k, v in d.items() if not isinstance(v, dict)}
    for k, v in scalars.items():
        out.append(f"{k} = {_toml_value(v)}")
    for section, values in d.items():
        if isinstance(values, dict):
            out.append("")
            out.append(f"[{section}]")
            for k, v in values.items():
                out.append(f"{k} = {_toml_value(v)}")
    return "\n".join(out) + "\n"


def save_config(cfg: Config, path: Path | None = None) -> Path:
    path = path or default_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dump_config(cfg), encoding="utf-8")
    return path
