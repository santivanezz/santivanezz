"""Acceptance tests from the SERGIO BRAIN specification (section 70)."""
import time
from pathlib import Path

from conftest import write

from sergio_brain.security import find_secrets, redact
from sergio_brain.server import BrainAPI


def test_01_new_note_is_indexed(engine, vault):
    write(vault, "Nueva.md", "# Nueva\nUna nota sobre Kanban y flujo de trabajo.\n")
    assert engine.indexer.index_path("Nueva.md") is True
    assert engine.db.one("SELECT id FROM documents WHERE path='Nueva.md'")
    assert engine.search.search("Kanban")[0]["path"] == "Nueva.md"


def test_02_modified_note_is_updated_incrementally(engine, vault):
    assert engine.indexer.index_path("Conceptos/Lean.md") is False  # unchanged -> skipped
    p = vault / "Conceptos/Lean.md"
    p.write_text(p.read_text(encoding="utf-8") + "\nNuevo párrafo sobre Kaizen.\n", encoding="utf-8")
    assert engine.indexer.index_path("Conceptos/Lean.md") is True
    versions = engine.db.query("SELECT id FROM document_versions WHERE document_id=(SELECT id FROM documents WHERE path='Conceptos/Lean.md')")
    assert len(versions) == 2
    assert any(r["path"] == "Conceptos/Lean.md" for r in engine.search.search("Kaizen"))


def test_03_related_note_relation_detected(engine, vault):
    doc = engine.db.one("SELECT id FROM documents WHERE path='Reuniones/Reunion Dashboard 2026-09-15.md'")
    related = engine.graph.related_documents(doc["id"])
    titles = [r["title"] for r in related]
    assert "Dashboard Ventas" in titles
    link = engine.db.one("SELECT 1 FROM relations WHERE relation='LINKS_TO' AND source_id=? ", (doc["id"],))
    assert link is not None


def test_04_ask_retrieves_with_sources(engine):
    res = engine.assistant.ask("¿Qué tengo sobre Erlang C?", use_llm=False)
    assert "Erlang C" in res["answer"]
    assert res["sources"][0]["title"] == "Erlang C"
    assert res["evidence"] == "I FOUND"
    nothing = engine.assistant.ask("¿Qué opina mi abuela del fútbol de Islandia?", use_llm=False)
    assert nothing["answer"].startswith("Not enough evidence in Boveda Sergio.")


def test_05_contradiction_detected(engine):
    contradictions = engine.intel.contradictions()
    assert contradictions, "expected at least one contradiction"
    subjects = {(c["statement_a"], c["statement_b"]) for c in contradictions}
    assert any("enero" in a and "marzo" in b for a, b in subjects)
    # neither note is deleted or modified
    assert (engine.vault.root / "Proyectos/Dashboard Ventas/Dashboard Ventas.md").exists()


def test_06_temporal_change_detected(engine, vault):
    p = vault / "Proyectos/Dashboard Ventas/Dashboard Ventas.md"
    p.write_text(p.read_text(encoding="utf-8").replace("implementado en enero", "implementado en abril"), encoding="utf-8")
    engine.indexer.index_path("Proyectos/Dashboard Ventas/Dashboard Ventas.md")
    doc = engine.db.one("SELECT id FROM documents WHERE path='Proyectos/Dashboard Ventas/Dashboard Ventas.md'")
    ch = engine.intel.what_changed(doc["id"])
    assert ch["changed"] is True
    assert any("abril" in l for l in ch["added"])
    assert any("enero" in l for l in ch["removed"])


def test_07_capture_reaches_inbox(engine):
    res = engine.inbox.capture("Power Automate permite automatizar flujos entre SharePoint y Teams sin código.", capture_type="clipboard")
    assert res["saved"] is True
    assert res["path"].startswith(engine.cfg.layout.inbox_folder)
    assert (engine.vault.root / res["path"]).exists()
    assert engine.db.one("SELECT id FROM documents WHERE path=?", (res["path"],))
    trivial = engine.inbox.capture("ok", capture_type="clipboard")
    assert trivial["saved"] is False and trivial["classification"] == "TRIVIAL"


def test_08_import_document(engine, tmp_path):
    from sergio_brain.documents import DocumentImporter
    f = tmp_path / "manual.txt"
    f.write_text("Manual de Six Sigma. DMAIC significa Definir, Medir, Analizar, Mejorar y Controlar.", encoding="utf-8")
    res = DocumentImporter(engine).import_file(f, summarize=False)
    assert res["imported"] is True
    assert any("manual" in r["path"].lower() for r in engine.search.search("DMAIC"))
    src = engine.db.one("SELECT source_path FROM sources WHERE source_note=?", (res["path"],))
    assert src and src["source_path"].endswith("manual.txt")


def test_09_task_detected(engine):
    tasks = engine.memory.open_tasks()
    texts = [t["content"] for t in tasks]
    assert any("Enviar el informe a Ana" in t for t in texts)
    assert any("revisar el modelo de datos" in t for t in texts)
    due = [t for t in tasks if "revisar el modelo" in t["content"]][0]
    assert due["due_date"] == "2026-09-25"
    done = engine.db.one("SELECT status FROM memories WHERE memory_type='TASK' AND content='Preparar la demo'")
    assert done["status"] == "done"


def test_10_decision_detected(engine):
    decisions = engine.memory.list_memories("DECISION")
    assert any("Power Query en lugar de VBA" in d["content"] for d in decisions)
    d = [x for x in decisions if "VBA" in x["content"]][0]
    assert "mantenible" in d["metadata"].get("reason", "")
    assert d["metadata"].get("alternatives") == ["VBA"]
    assert any("Hoy aprendí" in l["content"] for l in engine.memory.list_memories("LEARNING"))


def test_11_why_do_i_know_this(engine):
    res = engine.intel.why_do_i_know("¿Por qué tengo que revisar el modelo de datos?")
    assert res["chain"]
    top = res["chain"][0]
    assert top["title"] == "Dashboard Ventas"
    assert any(m["memory_type"] == "TASK" for m in top["memories"])
    assert "Dashboard Ventas" in res["summary"]


def test_12_what_changed_query(engine, vault):
    p = vault / "Conceptos/BPM.md"
    p.write_text(p.read_text(encoding="utf-8") + "\nProceso B reemplaza al Proceso A desde 2026.\n", encoding="utf-8")
    engine.indexer.index_path("Conceptos/BPM.md")
    res = engine.intel.what_changed_query("BPM proceso")
    assert any(d.get("changed") for d in res["documents"])


def test_13_offline_local_functions(engine, monkeypatch):
    import socket

    def no_network(*a, **k):
        raise OSError("network disabled")
    monkeypatch.setattr(socket, "create_connection", no_network)
    assert engine.search.search("Erlang")
    assert engine.assistant.ask("Erlang C", use_llm=True)["answer"]
    assert engine.embedder.cloud is False


def test_14_llm_unavailable_no_data_loss(engine):
    from sergio_brain.providers.base import LLMProvider, LLMResult

    class Broken(LLMProvider):
        name = "broken"
        cloud = False

        def available(self):
            return True

        def complete(self, system, user, max_tokens=2000):
            raise ConnectionError("boom")
    engine._llm = Broken()
    before = engine.db.stats()
    try:
        engine.assistant.ask("¿Qué tengo sobre Erlang C?")
    except ConnectionError:
        pass
    res = engine.inbox.capture("Texto importante que no debe perderse aunque falle el LLM.", capture_type="manual")
    assert res["saved"] is True
    assert engine.db.stats()["documents"] >= before["documents"]


def test_15_backup_and_recovery(engine, vault, tmp_path):
    snap = engine.backups.snapshot("test")
    assert Path(snap["file"]).exists() and snap["files"] >= 6
    inc = engine.backups.incremental()
    assert inc["files"] >= 6
    write(vault, "Extra.md", "# Extra\nnuevo\n")
    inc2 = engine.backups.incremental()
    assert inc2["files"] == 1
    dest = tmp_path / "restore"
    res = engine.backups.restore(snap["file"], dest)
    assert (dest / "Conceptos/Erlang C.md").exists()
    assert res["files"] >= 6
    # the live vault was untouched by restore-to-folder
    assert (vault / "Extra.md").exists()


# ----------------------------------------------------------------- additional unit tests

def test_secrets_never_indexed(engine):
    row = engine.db.one("SELECT content FROM chunks WHERE document_id=(SELECT id FROM documents WHERE path='Notas secretas.md')")
    assert "SuperSecreta123" not in row["content"]
    assert "sk-ant-" not in row["content"]
    assert "[REDACTED" in row["content"]
    assert engine.db.one("SELECT COUNT(*) AS n FROM document_versions WHERE content LIKE '%SuperSecreta123%'")["n"] == 0
    hits = find_secrets("token: ghp_abcdefghijklmnopqrstuvwxyz0123456789 y -----BEGIN RSA PRIVATE KEY-----\nabc\n-----END RSA PRIVATE KEY-----")
    assert {h.kind for h in hits} >= {"github_token", "private_key"}
    assert "[REDACTED:private_key]" in redact("-----BEGIN PRIVATE KEY-----\nxx\n-----END PRIVATE KEY-----")[0]


def test_do_not_index_respected(engine):
    assert engine.db.one("SELECT id FROM documents WHERE path='Privada.md' AND deleted=0") is None
    assert not engine.search.search("PALABRACLAVESECRETA")


def test_sensitive_not_sent_to_cloud(engine):
    from sergio_brain.providers.base import LLMProvider

    class Cloud(LLMProvider):
        name = "cloud"
        cloud = True

        def available(self):
            return True
    engine._llm = Cloud()
    assert engine.llm_allowed_for(["PERSONAL"]) is True
    assert engine.llm_allowed_for(["PERSONAL", "SENSITIVE"]) is False


def test_serendipity_and_suggestions(engine):
    sug = engine.graph.suggestions()
    kinds = {s["kind"] for s in sug}
    assert "SERENDIPITY" in kinds
    ser = [s for s in sug if s["kind"] == "SERENDIPITY"][0]
    assert {d["title"] for d in ser["documents"]} == {"BPM", "Lean"}
    # accepted suggestion via feedback
    engine.memory.record_feedback("suggestion", ser["id"], "USEFUL")
    assert engine.db.one("SELECT status FROM suggested_links WHERE id=?", (ser["id"],))["status"] == "accepted"


def test_memory_score_explains(engine):
    doc = engine.db.one("SELECT * FROM documents WHERE path='Proyectos/Dashboard Ventas/Dashboard Ventas.md'")
    score, reason = engine.memory.score_document(dict(doc))
    assert 0 < score <= 1
    assert "porque" in reason or "Importancia" in reason


def test_reviews_generate_notes(engine):
    engine.reviews.daily_memory()
    engine.reviews.morning_briefing()
    engine.reviews.weekly_review()
    engine.reviews.monthly_review()
    engine.reviews.command_center()
    engine.reviews.brain_health_note()
    brain = engine.vault.root / engine.cfg.layout.brain_folder
    assert (brain / "SERGIO BRAIN.md").exists()
    assert (brain / "Brain Health.md").exists()
    assert any(p.name.startswith("Morning Briefing") for p in (brain / "Reviews").iterdir())
    text = (brain / "SERGIO BRAIN.md").read_text(encoding="utf-8")
    assert "## TODAY" in text and "## CONTRADICTIONS" in text
    daily = engine.reviews.daily_note_path()
    assert daily.exists() and "sergio-brain:start:daily" in daily.read_text(encoding="utf-8")


def test_managed_block_preserves_user_content(engine, vault):
    p = write(vault, "Mi nota.md", "# Mi nota\nContenido mío que debe conservarse.\n")
    engine.writer.update_managed_block(p, "test", "bloque 1")
    engine.writer.update_managed_block(p, "test", "bloque 2")
    text = p.read_text(encoding="utf-8")
    assert "Contenido mío que debe conservarse." in text
    assert "bloque 2" in text and "bloque 1" not in text
    edits = vault / engine.cfg.layout.backups_folder / "edits"
    assert any(edits.iterdir())


def test_generated_notes_never_overwrite_user_notes(engine, vault):
    p = write(vault, "SERGIO BRAIN/SERGIO BRAIN.md", "# Mío\nEsto lo escribí yo.\n")
    engine.reviews.command_center()
    assert p.read_text(encoding="utf-8").startswith("# Mío")
    others = [x for x in (vault / "SERGIO BRAIN").glob("SERGIO BRAIN *.md")]
    assert others, "a suffixed file should have been created instead"


def test_deleted_note_soft_deleted(engine, vault):
    (vault / "Conceptos/Lean.md").unlink()
    engine.indexer.index_all()
    row = engine.db.one("SELECT deleted FROM documents WHERE path='Conceptos/Lean.md'")
    assert row["deleted"] == 1
    assert engine.db.one("SELECT COUNT(*) AS n FROM document_versions WHERE document_id=(SELECT id FROM documents WHERE path='Conceptos/Lean.md')")["n"] >= 1


def test_job_queue_retry(engine):
    calls = {"n": 0}

    def flaky(payload):
        calls["n"] += 1
        if calls["n"] < 2:
            raise RuntimeError("temporary")
    engine.jobs.register("flaky", flaky)
    jid = engine.jobs.enqueue("flaky", {"x": 1})
    engine.jobs.run_once()
    row = engine.db.one("SELECT status, attempts FROM processing_jobs WHERE id=?", (jid,))
    assert row["status"] == "pending" and row["attempts"] == 1
    engine.db.execute("UPDATE processing_jobs SET run_after=0 WHERE id=?", (jid,))
    engine.jobs.run_once()
    assert engine.db.one("SELECT status FROM processing_jobs WHERE id=?", (jid,))["status"] == "done"


def test_api_endpoints(engine):
    api = BrainAPI(engine)
    assert api.health()["ok"]
    assert api.search("Erlang")["results"]
    assert api.tasks()["tasks"]
    assert api.timeline(60)["timeline"]
    assert api.project("Dashboard Ventas")["project"]["name"] == "Dashboard Ventas"
    assert api.entities("Carlos")["entity"]["entity_type"] == "PERSON"
    assert api.graph()["nodes"]
    assert api.recall() is not None
    assert api.brain_health()["score"] >= 0
    assert api.feedback({"target_type": "document", "target_id": 1, "verdict": "IMPORTANT"})["ok"]
    assert api.notify_change("Conceptos/Erlang C.md")["queued"]
    assert engine.jobs.drain() >= 1


def test_http_server_roundtrip(engine):
    import json
    import urllib.request
    from sergio_brain.server import BrainServer
    srv = BrainServer(engine, "127.0.0.1", 0)
    port = srv.httpd.server_address[1]
    srv.start()
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=5) as r:
            assert json.loads(r.read())["ok"]
        req = urllib.request.Request(f"http://127.0.0.1:{port}/ask", data=json.dumps({"q": "Erlang C", "use_llm": False}).encode(), headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=5) as r:
            data = json.loads(r.read())
        assert data["sources"]
    finally:
        srv.stop()


def test_provider_abstraction(engine):
    from sergio_brain.config import Config
    from sergio_brain.providers.base import build_llm_provider, NoneProvider, ClaudeProvider
    cfg = Config()
    cfg.ai.llm_provider = "claude"
    cfg.ai.mode = "LOCAL_ONLY"
    assert isinstance(build_llm_provider(cfg), NoneProvider)  # cloud blocked in LOCAL_ONLY
    cfg.ai.mode = "HYBRID"
    assert isinstance(build_llm_provider(cfg), ClaudeProvider)
    cfg.ai.llm_provider = "ollama"
    assert build_llm_provider(cfg).name == "ollama"


def test_duplicate_detection_suggests_update(engine, vault):
    write(vault, "Conceptos/Erlang C 2.md", "# Erlang C 2\nErlang C se utiliza para calcular la probabilidad de espera en un call center dado un número de agentes y una tasa de llegadas.\n")
    engine.indexer.index_all()
    dups = engine.graph.suggestions(kind="DUPLICATE")
    assert dups and any({d["title"] for d in s["documents"]} >= {"Erlang C", "Erlang C 2"} for s in dups)
    existing = engine.memory.find_existing_for("Erlang C se utiliza para calcular la probabilidad de espera", "Erlang C")
    assert existing and existing[0]["suggestion"] == "UPDATE EXISTING NOTE"


def test_audit_is_read_only(vault):
    from sergio_brain.audit import audit_vault
    before = sorted(p.relative_to(vault).as_posix() + str(p.stat().st_mtime) for p in vault.rglob("*"))
    rep = audit_vault(vault)
    after = sorted(p.relative_to(vault).as_posix() + str(p.stat().st_mtime) for p in vault.rglob("*"))
    assert before == after
    assert rep["size"]["markdown_notes"] == 7
    assert rep["sensitive"]["notes_with_possible_secrets"] == 1
    assert rep["orphans"]["count"] >= 2


def test_doctor_runs(vault):
    from sergio_brain.doctor import run_doctor
    rep = run_doctor(str(vault))
    assert rep["vault"] == str(vault)
    assert rep["tools"]["python"]
