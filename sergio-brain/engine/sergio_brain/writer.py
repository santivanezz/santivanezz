"""Safe writes into the vault.

Rules (ZERO DATA LOSS):
  * Never overwrite a note that SERGIO BRAIN did not create, unless `update_section`
    is used, which only replaces a clearly delimited managed block.
  * Every generated note declares `sergio_brain: generated` in frontmatter.
  * Names never collide: if a file exists and is not ours, a timestamp suffix is used.
"""
from __future__ import annotations

import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from .config import Config

MANAGED_START = "<!-- sergio-brain:start:{name} -->"
MANAGED_END = "<!-- sergio-brain:end:{name} -->"


def safe_filename(name: str) -> str:
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', " ", name).strip()
    name = re.sub(r"\s+", " ", name)
    return name[:120] or "Untitled"


def frontmatter_block(fm: dict[str, Any]) -> str:
    lines = ["---"]
    for k, v in fm.items():
        if v is None:
            continue
        if isinstance(v, list):
            lines.append(f"{k}:")
            for x in v:
                lines.append(f"  - {x}")
        elif isinstance(v, bool):
            lines.append(f"{k}: {'true' if v else 'false'}")
        else:
            s = str(v)
            if re.search(r"[:#\[\]{}&*!|>'\"%@`]", s) or s.strip() != s:
                s = '"' + s.replace('"', '\\"') + '"'
            lines.append(f"{k}: {s}")
    lines.append("---")
    return "\n".join(lines) + "\n"


class VaultWriter:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.root = cfg.vault

    def is_ours(self, path: Path) -> bool:
        if not path.exists():
            return True
        head = path.read_text(encoding="utf-8", errors="replace")[:600]
        return "sergio_brain: generated" in head or "sergio_brain: managed" in head

    def unique_path(self, folder: str, title: str) -> Path:
        d = self.root / folder
        d.mkdir(parents=True, exist_ok=True)
        base = safe_filename(title)
        p = d / f"{base}.md"
        if p.exists():
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            p = d / f"{base} {stamp}.md"
        return p

    def write_generated(self, folder: str, title: str, body: str, fm: dict[str, Any] | None = None,
                        overwrite_if_ours: bool = False) -> Path:
        d = self.root / folder
        d.mkdir(parents=True, exist_ok=True)
        p = d / f"{safe_filename(title)}.md"
        if p.exists() and not (overwrite_if_ours and self.is_ours(p)):
            p = self.unique_path(folder, title)
        meta = {"sergio_brain": "generated", "generated_at": datetime.now().isoformat(timespec="seconds")}
        if fm:
            meta.update(fm)
        p.write_text(frontmatter_block(meta) + "\n" + body.rstrip() + "\n", encoding="utf-8")
        return p

    def update_managed_block(self, path: Path, name: str, content: str, create_with_title: str | None = None) -> Path:
        """Replace (or append) a managed block inside an existing note without touching the rest."""
        start = MANAGED_START.format(name=name)
        end = MANAGED_END.format(name=name)
        block = f"{start}\n{content.rstrip()}\n{end}"
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            fm = {"sergio_brain": "managed", "created": datetime.now().strftime("%Y-%m-%d")}
            head = frontmatter_block(fm) + (f"\n# {create_with_title}\n" if create_with_title else "")
            path.write_text(head + "\n" + block + "\n", encoding="utf-8")
            return path
        text = path.read_text(encoding="utf-8", errors="replace")
        pattern = re.compile(re.escape(start) + r"[\s\S]*?" + re.escape(end))
        if pattern.search(text):
            new = pattern.sub(lambda _m: block, text)
        else:
            new = text.rstrip() + "\n\n" + block + "\n"
        if new != text:
            backup_dir = self.root / self.cfg.layout.backups_folder / "edits"
            backup_dir.mkdir(parents=True, exist_ok=True)
            (backup_dir / f"{path.stem}.{int(time.time())}.md").write_text(text, encoding="utf-8")
            path.write_text(new, encoding="utf-8")
        return path

    def append_to_note(self, path: Path, text: str) -> Path:
        """Append text to a note (never removes anything)."""
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as fh:
            if path.stat().st_size > 0 if path.exists() else False:
                fh.write("\n")
            fh.write(text.rstrip() + "\n")
        return path
