"""Document intelligence: extract text from PDF/DOCX/XLSX/PPTX/TXT/CSV/MD and
import it into the vault as a note that keeps a reference to the original file."""
from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from .extractors import keywords, extract_entities


def extract_text(path: Path) -> tuple[str, dict[str, Any]]:
    ext = path.suffix.lower()
    meta: dict[str, Any] = {"format": ext.lstrip("."), "size": path.stat().st_size}
    if ext in (".txt", ".md", ".markdown"):
        return path.read_text(encoding="utf-8", errors="replace"), meta
    if ext == ".csv":
        rows = []
        with open(path, newline="", encoding="utf-8", errors="replace") as fh:
            for i, row in enumerate(csv.reader(fh)):
                rows.append(" | ".join(row))
                if i > 500:
                    rows.append("... (truncado)")
                    break
        meta["rows"] = len(rows)
        return "\n".join(rows), meta
    if ext == ".pdf":
        try:
            from pypdf import PdfReader
        except ImportError as exc:
            raise RuntimeError("pip install pypdf  (extra: sergio-brain[docs])") from exc
        reader = PdfReader(str(path))
        meta["pages"] = len(reader.pages)
        return "\n\n".join((p.extract_text() or "") for p in reader.pages), meta
    if ext == ".docx":
        try:
            import docx
        except ImportError as exc:
            raise RuntimeError("pip install python-docx") from exc
        d = docx.Document(str(path))
        parts = [p.text for p in d.paragraphs]
        for t in d.tables:
            for row in t.rows:
                parts.append(" | ".join(c.text for c in row.cells))
        return "\n".join(parts), meta
    if ext in (".xlsx", ".xlsm"):
        try:
            import openpyxl
        except ImportError as exc:
            raise RuntimeError("pip install openpyxl") from exc
        wb = openpyxl.load_workbook(str(path), read_only=True, data_only=True)
        parts = []
        for ws in wb.worksheets:
            parts.append(f"## Hoja: {ws.title}")
            for i, row in enumerate(ws.iter_rows(values_only=True)):
                parts.append(" | ".join("" if v is None else str(v) for v in row))
                if i > 300:
                    parts.append("... (truncado)")
                    break
        meta["sheets"] = len(wb.worksheets)
        return "\n".join(parts), meta
    if ext == ".pptx":
        try:
            from pptx import Presentation
        except ImportError as exc:
            raise RuntimeError("pip install python-pptx") from exc
        prs = Presentation(str(path))
        parts = []
        for i, slide in enumerate(prs.slides, 1):
            parts.append(f"## Diapositiva {i}")
            for shape in slide.shapes:
                if shape.has_text_frame:
                    parts.append(shape.text_frame.text)
        meta["slides"] = len(prs.slides)
        return "\n".join(parts), meta
    raise RuntimeError(f"unsupported format: {ext}")


class DocumentImporter:
    def __init__(self, engine):
        self.e = engine

    def import_file(self, path: Path, summarize: bool = True, privacy: str = "PERSONAL") -> dict[str, Any]:
        path = Path(path)
        text, meta = extract_text(path)
        text = text.strip()
        if not text:
            return {"imported": False, "message": "no se pudo extraer texto"}
        summary = self.e.assistant.summarize(text, purpose=f"resumen del documento {path.name}", privacy=privacy) if summarize else None
        ents = extract_entities(text[:20000], [], [], {})[:15]
        kws = keywords(text, 12)
        try:
            rel_original = path.resolve().relative_to(self.e.vault.root.resolve()).as_posix()
        except ValueError:
            rel_original = None
        body = [f"# {path.stem}", ""]
        body.append(f"Documento original: `{path}`" if not rel_original else f"Documento original: [[{rel_original}]]")
        body.append("")
        if summary:
            body += ["## Resumen (AI_INFERENCE)", summary, ""]
        body += ["## Entidades detectadas", ", ".join(f"{n} ({t})" for n, t, _ in ents) or "(ninguna)", "",
                 "## Keywords", ", ".join(kws), "", "## Contenido extraído", "", text[:60000]]
        if len(text) > 60000:
            body.append("\n... (contenido truncado en la nota; el índice conserva el texto completo)")
        fm = {"type": "import", "source_type": meta["format"], "source_path": str(path), "privacy": privacy, "tags": ["import", meta["format"]], **{k: v for k, v in meta.items() if k not in ("format",)}}
        note_path = self.e.writer.write_generated(self.e.cfg.layout.imports_folder, path.stem, "\n".join(body), fm)
        rel = note_path.relative_to(self.e.vault.root).as_posix()
        self.e.indexer.index_path(rel)
        doc = self.e.db.one("SELECT id FROM documents WHERE path=?", (rel,))
        self.e.db.execute("INSERT INTO sources(document_id, source_type, source_path, source_note, capture_method, processing_date, metadata) VALUES(?,?,?,?,?,?,?)",
                          (doc["id"] if doc else None, meta["format"], str(path), rel, "import", __import__("time").time(), json.dumps(meta)))
        self.e.events.emit("FILE_IMPORTED", {"path": rel, "original": str(path)})
        return {"imported": True, "path": rel, "chars": len(text), "meta": meta, "summary": bool(summary)}
