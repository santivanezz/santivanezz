"""Backups: snapshot (zip of vault + DB), incremental (only changed files by hash),
restore and rollback. Never deletes anything in the vault; restore writes into a
separate folder unless --in-place is given, and even then keeps the current
files as a pre-restore snapshot."""
from __future__ import annotations

import hashlib
import json
import shutil
import time
import zipfile
from pathlib import Path
from typing import Any


def _sha(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


class BackupManager:
    def __init__(self, engine):
        self.e = engine
        self.cfg = engine.cfg
        self.dir = self.cfg.backup_dir
        self.dir.mkdir(parents=True, exist_ok=True)

    def _manifest_path(self) -> Path:
        return self.dir / "manifest.json"

    def _load_manifest(self) -> dict[str, Any]:
        p = self._manifest_path()
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {"files": {}, "snapshots": []}

    def _save_manifest(self, m: dict[str, Any]) -> None:
        self._manifest_path().write_text(json.dumps(m, indent=1, ensure_ascii=False), encoding="utf-8")

    def _vault_files(self):
        for p in self.e.vault.iter_all_files():
            rel = p.relative_to(self.e.vault.root).as_posix()
            if rel.startswith(self.cfg.layout.backups_folder) or "/.git/" in ("/" + rel):
                continue
            yield rel, p

    def snapshot(self, label: str = "snapshot", include_db: bool = True) -> dict[str, Any]:
        stamp = time.strftime("%Y%m%d-%H%M%S")
        name = f"{stamp}-{label}.zip"
        target = self.dir / name
        n = 0
        with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as zf:
            for rel, p in self._vault_files():
                zf.write(p, "vault/" + rel)
                n += 1
            if include_db and self.cfg.db_path.exists():
                # consistent copy of the SQLite DB
                tmp = self.dir / f".db-{stamp}.sqlite"
                import sqlite3
                src = sqlite3.connect(str(self.cfg.db_path))
                dst = sqlite3.connect(str(tmp))
                src.backup(dst)
                dst.close()
                src.close()
                zf.write(tmp, "db/sergio_brain.sqlite")
                tmp.unlink(missing_ok=True)
        m = self._load_manifest()
        m["snapshots"].append({"file": name, "label": label, "created_at": time.time(), "files": n, "kind": "snapshot"})
        self._save_manifest(m)
        self.e.events.emit("BACKUP_CREATED", {"file": name, "files": n})
        return {"file": str(target), "files": n}

    def incremental(self) -> dict[str, Any]:
        m = self._load_manifest()
        known = m.get("files", {})
        stamp = time.strftime("%Y%m%d-%H%M%S")
        name = f"{stamp}-incremental.zip"
        changed = 0
        with zipfile.ZipFile(self.dir / name, "w", zipfile.ZIP_DEFLATED) as zf:
            for rel, p in self._vault_files():
                h = _sha(p)
                if known.get(rel) != h:
                    zf.write(p, "vault/" + rel)
                    known[rel] = h
                    changed += 1
        if changed == 0:
            (self.dir / name).unlink(missing_ok=True)
            return {"file": None, "files": 0}
        m["files"] = known
        m["snapshots"].append({"file": name, "label": "incremental", "created_at": time.time(), "files": changed, "kind": "incremental"})
        self._save_manifest(m)
        self.e.events.emit("BACKUP_CREATED", {"file": name, "files": changed, "incremental": True})
        return {"file": str(self.dir / name), "files": changed}

    def list(self) -> list[dict[str, Any]]:
        return self._load_manifest().get("snapshots", [])

    def restore(self, backup_file: str, destination: Path | None = None, in_place: bool = False) -> dict[str, Any]:
        src = Path(backup_file) if Path(backup_file).exists() else self.dir / backup_file
        if not src.exists():
            raise FileNotFoundError(src)
        if in_place:
            self.snapshot("pre-restore")
            dest = self.e.vault.root
        else:
            dest = destination or (self.dir / f"restore-{time.strftime('%Y%m%d-%H%M%S')}")
        dest.mkdir(parents=True, exist_ok=True)
        n = 0
        db_restored = False
        with zipfile.ZipFile(src) as zf:
            for info in zf.infolist():
                if info.is_dir():
                    continue
                if info.filename.startswith("vault/"):
                    out = dest / info.filename[len("vault/"):]
                    out.parent.mkdir(parents=True, exist_ok=True)
                    with zf.open(info) as fh, open(out, "wb") as oh:
                        shutil.copyfileobj(fh, oh)
                    n += 1
                elif info.filename.startswith("db/") and in_place:
                    self.e.db.close()
                    bak = self.cfg.db_path.with_suffix(f".pre-restore-{int(time.time())}.sqlite")
                    if self.cfg.db_path.exists():
                        shutil.copy2(self.cfg.db_path, bak)
                    with zf.open(info) as fh, open(self.cfg.db_path, "wb") as oh:
                        shutil.copyfileobj(fh, oh)
                    db_restored = True
        return {"restored_to": str(dest), "files": n, "db_restored": db_restored}

    def rollback_last_edit(self, note_rel_path: str) -> dict[str, Any]:
        """Restore the previous content of a note edited by SERGIO BRAIN (managed blocks keep pre-edit copies)."""
        edits = self.e.vault.root / self.cfg.layout.backups_folder / "edits"
        stem = Path(note_rel_path).stem
        candidates = sorted(edits.glob(f"{stem}.*.md")) if edits.exists() else []
        if not candidates:
            return {"rolled_back": False, "message": "no hay copias previas"}
        last = candidates[-1]
        target = self.e.vault.root / note_rel_path
        self.snapshot("pre-rollback")
        shutil.copy2(last, target)
        return {"rolled_back": True, "from": str(last)}
