"""File watcher with debounce. Uses watchdog if installed, else a polling scanner."""
from __future__ import annotations

import os
import threading
import time
from pathlib import Path

from .events import Debouncer


class VaultWatcher:
    def __init__(self, engine):
        self.e = engine
        self.cfg = engine.cfg
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._debouncer = Debouncer(self.cfg.debounce_seconds, self._on_settled)
        self._snapshot: dict[str, float] = {}

    def _on_settled(self, rel: str) -> None:
        abs_path = self.e.vault.root / rel
        if abs_path.exists():
            self.e.jobs.enqueue("index_note", {"path": rel})
        else:
            self.e.jobs.enqueue("remove_note", {"path": rel})
        self.e.jobs.enqueue("analyze", {}, delay=10)

    def notify(self, rel: str) -> None:
        rel = rel.replace("\\", "/")
        if rel.lower().endswith(".md") and not self.e.vault.is_excluded(rel):
            self._debouncer.trigger(rel)

    # ------------------------------------------------------------ polling
    def _scan(self) -> dict[str, float]:
        out: dict[str, float] = {}
        for p in self.e.vault.iter_markdown():
            try:
                out[p.relative_to(self.e.vault.root).as_posix()] = p.stat().st_mtime
            except OSError:
                continue
        return out

    def _poll_loop(self) -> None:
        self._snapshot = self._scan()
        while not self._stop.is_set():
            time.sleep(self.cfg.watch_poll_seconds)
            try:
                current = self._scan()
            except Exception as exc:  # noqa: BLE001
                self.e.log.error("watcher scan failed: %s", exc)
                continue
            for rel, mt in current.items():
                if self._snapshot.get(rel) != mt:
                    self.notify(rel)
            for rel in set(self._snapshot) - set(current):
                self.notify(rel)
            self._snapshot = current
            try:
                self.e.jobs.run_once()
            except Exception as exc:  # noqa: BLE001
                self.e.log.error("job run failed: %s", exc)

    def _watchdog_loop(self) -> bool:
        try:
            from watchdog.events import FileSystemEventHandler
            from watchdog.observers import Observer
        except ImportError:
            return False
        watcher = self

        class Handler(FileSystemEventHandler):
            def on_any_event(self, event):
                if event.is_directory:
                    return
                for p in (getattr(event, "src_path", None), getattr(event, "dest_path", None)):
                    if p:
                        try:
                            watcher.notify(Path(p).relative_to(watcher.e.vault.root).as_posix())
                        except ValueError:
                            pass

        obs = Observer()
        obs.schedule(Handler(), str(self.e.vault.root), recursive=True)
        obs.start()
        try:
            while not self._stop.is_set():
                time.sleep(1.0)
                try:
                    self.e.jobs.run_once()
                except Exception as exc:  # noqa: BLE001
                    self.e.log.error("job run failed: %s", exc)
        finally:
            obs.stop()
            obs.join()
        return True

    def start(self, prefer_watchdog: bool = True) -> None:
        def run():
            if prefer_watchdog and self._watchdog_loop():
                return
            self._poll_loop()
        self._thread = threading.Thread(target=run, name="vault-watcher", daemon=True)
        self._thread.start()
        self.e.log.info("watcher started on %s", self.e.vault.root)

    def stop(self) -> None:
        self._stop.set()
        self._debouncer.flush()
        if self._thread:
            self._thread.join(timeout=5)
