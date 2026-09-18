"""Command line interface: sergio-brain <command>."""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from . import __version__
from .config import Config, default_config_path, load_config, save_config


def _engine(args):
    from .engine import Engine
    cfg_path = Path(args.config) if getattr(args, "config", None) else None
    cfg = load_config(cfg_path)
    if getattr(args, "vault", None):
        cfg.vault_path = args.vault
    return Engine(cfg)


def _print(obj, as_json: bool):
    if as_json:
        print(json.dumps(obj, ensure_ascii=False, indent=2, default=str))
    elif isinstance(obj, str):
        print(obj)
    else:
        print(json.dumps(obj, ensure_ascii=False, indent=2, default=str))


def cmd_doctor(args):
    from .doctor import run_doctor, format_doctor
    rep = run_doctor(args.vault)
    _print(rep if args.json else format_doctor(rep), args.json)


def cmd_init(args):
    from .doctor import find_vault
    cfg_path = Path(args.config) if args.config else default_config_path()
    cfg = load_config(cfg_path) if cfg_path.exists() else Config()
    vault = args.vault
    if not vault:
        hits = find_vault()
        if not hits:
            print("No se encontró 'Boveda Sergio'. Usa: sergio-brain init --vault <ruta>")
            sys.exit(2)
        vault = str(hits[0])
    if not Path(vault).exists():
        print(f"La ruta no existe: {vault}")
        sys.exit(2)
    cfg.vault_path = str(Path(vault).resolve())
    if args.data_dir:
        cfg.data_dir = args.data_dir
    if args.ai_mode:
        cfg.ai.mode = args.ai_mode
    if args.llm:
        cfg.ai.llm_provider = args.llm
    p = save_config(cfg, cfg_path)
    cfg.ensure_dirs()
    print(f"Configuración escrita en {p}\nBóveda: {cfg.vault_path}\nDatos: {cfg.data}\nLa bóveda NO ha sido modificada.")


def cmd_audit(args):
    from .audit import audit_vault, format_audit
    cfg = load_config(Path(args.config) if args.config else None)
    if not (args.vault or cfg.vault_path):
        print("Bóveda no configurada; usa --vault o sergio-brain init")
        sys.exit(2)
    root = Path(args.vault or cfg.vault_path)
    if not root.exists():
        print("Bóveda no encontrada; usa --vault o sergio-brain init")
        sys.exit(2)
    rep = audit_vault(root)
    if args.out:
        Path(args.out).write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
    _print(rep if args.json else format_audit(rep), args.json)


def cmd_index(args):
    e = _engine(args)
    if not args.no_backup and not e.backups.list():
        print("Primera indexación: creando snapshot de seguridad...")
        print(e.backups.snapshot("before-first-index"))
    t0 = time.time()
    stats = e.indexer.index_all(force=args.force, progress=lambda s: print(f"  ... {s['scanned']} notas", flush=True))
    stats["seconds"] = round(time.time() - t0, 1)
    _print(stats, args.json)


def cmd_search(args):
    e = _engine(args)
    res = e.search.search(args.query, k=args.k, mode=args.mode)
    if args.json:
        _print([{k: v for k, v in r.items() if k != "content"} for r in res], True)
        return
    for r in res:
        print(f"[{r['score']:.2f}] {r['title']}  ({r['path']})" + (f"  › {r['heading']}" if r["heading"] else ""))
        print("      " + " ".join(r["snippet"].split())[:160])


def cmd_ask(args):
    e = _engine(args)
    res = e.assistant.ask(args.question, k=args.k, use_llm=not args.no_llm)
    if args.json:
        _print(res, True)
        return
    print(res["answer"])
    print()
    print(f"[{res['evidence']} · {res['mode']} · {res['duration_ms']} ms]")
    if res.get("llm_error"):
        print(f"(LLM no usado: {res['llm_error']})")
    if res["sources"]:
        print("Sources:")
        for s in res["sources"][:8]:
            print(f"  - [[{s['title']}]] ({s['path']}) {s['score']}")


def cmd_serve(args):
    from .server import BrainServer, Scheduler
    from .watcher import VaultWatcher
    e = _engine(args)
    server = BrainServer(e, args.host, args.port)
    server.start()
    watcher = VaultWatcher(e)
    watcher.start()
    sched = Scheduler(e)
    if not args.no_scheduler:
        sched.start()
    print(f"SERGIO BRAIN sirviendo en http://{server.host}:{server.port}  (Ctrl+C para salir)")
    if args.index:
        print("Indexación inicial...", e.indexer.index_all())
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        watcher.stop()
        sched.stop()
        server.stop()


def cmd_capture(args):
    e = _engine(args)
    if args.clipboard:
        res = e.inbox.capture_clipboard(force=args.force)
    else:
        text = args.text or sys.stdin.read()
        res = e.inbox.capture(text, capture_type="manual", title=args.title, url=args.url, force=args.force)
    _print(res, args.json)


def cmd_import(args):
    from .documents import DocumentImporter
    e = _engine(args)
    _print(DocumentImporter(e).import_file(Path(args.file), summarize=not args.no_summary), args.json)


def cmd_backup(args):
    e = _engine(args)
    if args.list:
        _print(e.backups.list(), args.json)
    elif args.restore:
        _print(e.backups.restore(args.restore, Path(args.to) if args.to else None, in_place=args.in_place), args.json)
    elif args.incremental:
        _print(e.backups.incremental(), args.json)
    else:
        _print(e.backups.snapshot(args.label or "manual"), args.json)


def cmd_review(args):
    e = _engine(args)
    if args.period == "daily":
        out = e.reviews.daily_memory()
    elif args.period == "weekly":
        out = e.reviews.weekly_review()
    elif args.period == "monthly":
        out = e.reviews.monthly_review()
    elif args.period == "briefing":
        out = e.reviews.morning_briefing()
    elif args.period == "consolidate":
        out = e.reviews.daily_consolidation()["summary"]
    else:
        out = e.reviews.command_center()
    print(out)


def cmd_health(args):
    e = _engine(args)
    if args.json:
        _print(e.reviews.brain_health(), True)
    else:
        print(e.reviews.brain_health_note())


def cmd_tasks(args):
    e = _engine(args)
    tasks = e.memory.open_tasks()
    if args.json:
        _print(tasks, True)
        return
    for t in tasks:
        flag = "⚠ " if t["overdue"] else ""
        print(f"- [ ] {flag}{t['content'][:120]}  ({t['note_title']}, {t['age_days']}d" + (f", vence {t['due_date']}" if t.get("due_date") else "") + ")")


def cmd_timeline(args):
    e = _engine(args)
    items = e.intel.timeline(since=time.time() - args.days * 86400, project=args.project)
    if args.json:
        _print(items, True)
        return
    for it in items:
        print(f"{it['date']}  {it['kind']:14s} {it['title'][:90]}  ({it['note']})")


def cmd_why(args):
    e = _engine(args)
    res = e.intel.why_do_i_know(args.question)
    _print(res if args.json else res["summary"], args.json)


def cmd_changed(args):
    e = _engine(args)
    res = e.intel.what_changed_query(args.query)
    if args.json:
        _print(res, True)
        return
    for d in res["documents"]:
        print(f"## {d['document']['title'] if d.get('document') else '?'}: {d['message']}")
        if d.get("diff"):
            print(d["diff"][:3000])
    for s in res["superseded"]:
        print(f"SUPERSEDED: {s['subject']}: «{s['statement_a']}» → «{s['statement_b']}»")


def cmd_recall(args):
    e = _engine(args)
    items = e.intel.active_recall()
    _print(items if args.json else "\n".join(f"- {i['message']}" for i in items) or "Nada que recordar hoy.", args.json)


def cmd_project(args):
    e = _engine(args)
    _print(e.intel.project_memory(args.name), True)


def cmd_suggestions(args):
    e = _engine(args)
    _print(e.graph.suggestions(kind=args.kind), True)


def cmd_contradictions(args):
    e = _engine(args)
    _print(e.intel.contradictions(), True)


def cmd_feedback(args):
    e = _engine(args)
    _print({"feedback_id": e.memory.record_feedback(args.target_type, args.target_id, args.verdict, args.note)}, True)


def cmd_plugin_install(args):
    import shutil
    cfg = load_config(Path(args.config) if args.config else None)
    vault = Path(args.vault or cfg.vault_path)
    if not vault.exists():
        print("Bóveda no configurada; usa --vault o sergio-brain init")
        sys.exit(2)
    src = Path(args.src) if args.src else Path(__file__).resolve().parents[2] / "plugin"
    if not (src / "main.js").exists():
        print(f"No encuentro plugin/main.js en {src}. Indica --src <carpeta plugin>")
        sys.exit(2)
    dest = vault / ".obsidian" / "plugins" / "sergio-brain"
    dest.mkdir(parents=True, exist_ok=True)
    for name in ("main.js", "manifest.json", "styles.css"):
        shutil.copy2(src / name, dest / name)
    print(f"Plugin copiado a {dest}\nEn Obsidian: Ajustes > Plugins de la comunidad > desactivar modo restringido > activar 'Sergio Brain'.")


def cmd_import_chats(args):
    from .ai_chats import AIChatMemory
    e = _engine(args)
    _print(AIChatMemory(e).import_file(Path(args.file), args.provider), True)


def cmd_import_memory(args):
    from .ai_chats import AIChatMemory
    e = _engine(args)
    text = Path(args.file).read_text(encoding="utf-8", errors="replace") if args.file else sys.stdin.read()
    _print(AIChatMemory(e).import_memory(args.provider, text), True)


def cmd_costs(args):
    e = _engine(args)
    _print(e.costs.summary(args.days), True)


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--config", help="ruta al config.toml")
    common.add_argument("--vault", help="ruta de la bóveda (sobrescribe config)")
    common.add_argument("--json", action="store_true", help="salida JSON")
    p = argparse.ArgumentParser(prog="sergio-brain", description="SERGIO BRAIN — Personal Memory Operating System", parents=[common])
    p.add_argument("--version", action="version", version=__version__)
    _sub = p.add_subparsers(dest="cmd", required=True)

    class _Sub:
        def add_parser(self, name, **kw):
            return _sub.add_parser(name, parents=[common], **kw)
    sub = _Sub()

    sub.add_parser("doctor", help="inspecciona el entorno y localiza Boveda Sergio").set_defaults(fn=cmd_doctor)
    s = sub.add_parser("init", help="crea la configuración (no modifica la bóveda)")
    s.add_argument("--data-dir"); s.add_argument("--ai-mode", choices=["LOCAL_ONLY", "HYBRID", "CLOUD"]); s.add_argument("--llm", choices=["none", "claude", "openai", "ollama"])
    s.set_defaults(fn=cmd_init)
    s = sub.add_parser("audit", help="auditoría de solo lectura de la bóveda"); s.add_argument("--out", help="guardar JSON en archivo"); s.set_defaults(fn=cmd_audit)
    s = sub.add_parser("index", help="indexación incremental"); s.add_argument("--force", action="store_true"); s.add_argument("--no-backup", action="store_true"); s.set_defaults(fn=cmd_index)
    s = sub.add_parser("search", help="búsqueda híbrida"); s.add_argument("query"); s.add_argument("-k", type=int, default=10); s.add_argument("--mode", default="hybrid", choices=["hybrid", "keyword", "semantic"]); s.set_defaults(fn=cmd_search)
    s = sub.add_parser("ask", help="pregunta al asistente"); s.add_argument("question"); s.add_argument("-k", type=int, default=8); s.add_argument("--no-llm", action="store_true"); s.set_defaults(fn=cmd_ask)
    s = sub.add_parser("serve", help="API local + watcher + scheduler"); s.add_argument("--host"); s.add_argument("--port", type=int); s.add_argument("--index", action="store_true", help="indexar al arrancar"); s.add_argument("--no-scheduler", action="store_true"); s.set_defaults(fn=cmd_serve)
    s = sub.add_parser("capture", help="captura al Inbox"); s.add_argument("text", nargs="?"); s.add_argument("--clipboard", action="store_true"); s.add_argument("--title"); s.add_argument("--url"); s.add_argument("--force", action="store_true"); s.set_defaults(fn=cmd_capture)
    s = sub.add_parser("import", help="importa un documento (pdf/docx/xlsx/pptx/txt/csv/md)"); s.add_argument("file"); s.add_argument("--no-summary", action="store_true"); s.set_defaults(fn=cmd_import)
    s = sub.add_parser("backup", help="snapshot / incremental / restore"); s.add_argument("--label"); s.add_argument("--incremental", action="store_true"); s.add_argument("--list", action="store_true"); s.add_argument("--restore", help="archivo zip"); s.add_argument("--to"); s.add_argument("--in-place", action="store_true"); s.set_defaults(fn=cmd_backup)
    s = sub.add_parser("review", help="daily | weekly | monthly | briefing | consolidate | dashboard"); s.add_argument("period", choices=["daily", "weekly", "monthly", "briefing", "consolidate", "dashboard"]); s.set_defaults(fn=cmd_review)
    sub.add_parser("health", help="Brain Health").set_defaults(fn=cmd_health)
    sub.add_parser("tasks", help="tareas abiertas detectadas").set_defaults(fn=cmd_tasks)
    s = sub.add_parser("timeline", help="línea temporal"); s.add_argument("--days", type=int, default=30); s.add_argument("--project"); s.set_defaults(fn=cmd_timeline)
    s = sub.add_parser("why", help="¿por qué sé esto?"); s.add_argument("question"); s.set_defaults(fn=cmd_why)
    s = sub.add_parser("changed", help="¿qué cambió?"); s.add_argument("query"); s.set_defaults(fn=cmd_changed)
    sub.add_parser("recall", help="recuerdos activos para hoy").set_defaults(fn=cmd_recall)
    s = sub.add_parser("project", help="memoria de un proyecto"); s.add_argument("name"); s.set_defaults(fn=cmd_project)
    s = sub.add_parser("suggestions", help="conexiones sugeridas"); s.add_argument("--kind", choices=["LINK", "CONSOLIDATE", "SERENDIPITY", "DUPLICATE"]); s.set_defaults(fn=cmd_suggestions)
    sub.add_parser("contradictions", help="posibles contradicciones").set_defaults(fn=cmd_contradictions)
    s = sub.add_parser("feedback", help="registrar feedback"); s.add_argument("target_type", choices=["memory", "suggestion", "contradiction", "answer", "document"]); s.add_argument("target_id"); s.add_argument("verdict", choices=["USEFUL", "NOT_USEFUL", "WRONG", "DUPLICATE", "IMPORTANT", "IGNORE"]); s.add_argument("--note"); s.set_defaults(fn=cmd_feedback)
    s = sub.add_parser("plugin-install", help="copia el plugin de Obsidian a la bóveda"); s.add_argument("--src"); s.set_defaults(fn=cmd_plugin_install)
    s = sub.add_parser("import-chats", help="importa exportaciones de ChatGPT / Claude / Gemini"); s.add_argument("file"); s.add_argument("--provider", default="auto", choices=["auto", "chatgpt", "claude", "gemini", "other"]); s.set_defaults(fn=cmd_import_chats)
    s = sub.add_parser("import-memory", help="importa la 'memoria sobre mí' de un asistente (texto pegado)"); s.add_argument("provider", choices=["chatgpt", "claude", "gemini", "other"]); s.add_argument("file", nargs="?"); s.set_defaults(fn=cmd_import_memory)
    s = sub.add_parser("costs", help="uso de APIs externas"); s.add_argument("--days", type=int, default=30); s.set_defaults(fn=cmd_costs)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        args.fn(args)
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
