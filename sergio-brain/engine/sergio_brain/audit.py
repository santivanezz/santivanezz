"""`sergio-brain audit`: read-only audit of the existing vault (section 60 of the spec).
Nothing is modified. Output: a report (text + JSON) with size, files, types, structure,
folders, tags, properties, links/backlinks, duplicates, orphans, problem files and
possible sensitive data (counts only, never the secrets themselves)."""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
from collections import Counter
from pathlib import Path
from typing import Any

from .security import find_secrets
from .vault import parse_note, extract_links


def audit_vault(root: Path, max_bytes_hash: int = 5_000_000) -> dict[str, Any]:
    root = Path(root)
    t0 = time.time()
    ext_counter: Counter[str] = Counter()
    ext_bytes: Counter[str] = Counter()
    folder_counter: Counter[str] = Counter()
    total_size = 0
    total_files = 0
    notes: dict[str, dict[str, Any]] = {}
    hashes: dict[str, list[str]] = {}
    problems: list[dict[str, Any]] = []
    sensitive: list[dict[str, Any]] = []
    tag_counter: Counter[str] = Counter()
    prop_counter: Counter[str] = Counter()
    link_targets: Counter[str] = Counter()
    largest: list[tuple[int, str]] = []
    empty_notes: list[str] = []
    deepest = 0
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in (".git", ".trash")]
        rel_dir = Path(dirpath).relative_to(root).as_posix()
        depth = 0 if rel_dir == "." else len(rel_dir.split("/"))
        deepest = max(deepest, depth)
        if not rel_dir.startswith(".obsidian"):
            folder_counter[rel_dir if rel_dir != "." else "(raíz)"] += len([f for f in filenames if f.endswith(".md")])
        for fn in filenames:
            p = Path(dirpath) / fn
            try:
                st = p.stat()
            except OSError as exc:
                problems.append({"path": p.relative_to(root).as_posix(), "problem": f"no accesible: {exc}"})
                continue
            total_files += 1
            total_size += st.st_size
            ext = p.suffix.lower() or "(sin extensión)"
            ext_counter[ext] += 1
            ext_bytes[ext] += st.st_size
            largest.append((st.st_size, p.relative_to(root).as_posix()))
            if rel_dir.startswith(".obsidian"):
                continue
            if fn.lower().endswith(".md"):
                rel = p.relative_to(root).as_posix()
                try:
                    note = parse_note(p, root)
                except UnicodeDecodeError:
                    problems.append({"path": rel, "problem": "no es UTF-8"})
                    continue
                except OSError as exc:
                    problems.append({"path": rel, "problem": str(exc)})
                    continue
                if not note.body.strip():
                    empty_notes.append(rel)
                if st.st_size <= max_bytes_hash:
                    h = hashlib.sha256(note.raw.encode("utf-8", errors="replace")).hexdigest()
                    hashes.setdefault(h, []).append(rel)
                if re.search(r"[\x00-\x08]", note.raw[:2000]):
                    problems.append({"path": rel, "problem": "contiene caracteres binarios"})
                if len(fn) > 200:
                    problems.append({"path": rel, "problem": "nombre demasiado largo"})
                if fn.strip() != fn or "  " in fn:
                    problems.append({"path": rel, "problem": "espacios raros en el nombre"})
                for t in note.tags:
                    tag_counter[t] += 1
                for k in note.frontmatter:
                    prop_counter[k] += 1
                for l in note.links:
                    link_targets[l] += 1
                hits = find_secrets(note.raw)
                if hits:
                    sensitive.append({"path": rel, "kinds": sorted({h.kind for h in hits}), "count": len(hits)})
                notes[rel] = {"title": note.title, "stem": p.stem, "links": note.links, "words": note.word_count, "mtime": st.st_mtime, "tags": note.tags}
    # links / backlinks
    by_stem: dict[str, list[str]] = {}
    for rel, n in notes.items():
        by_stem.setdefault(n["stem"].lower(), []).append(rel)
    inbound: Counter[str] = Counter()
    broken: Counter[str] = Counter()
    for rel, n in notes.items():
        for l in n["links"]:
            key = os.path.basename(l).lower()
            if key.endswith(".md"):
                key = key[:-3]
            targets = by_stem.get(key)
            if targets:
                for t in targets:
                    inbound[t] += 1
            else:
                broken[l] += 1
    orphans = [rel for rel, n in notes.items() if inbound[rel] == 0 and not n["links"]]
    no_inbound = [rel for rel in notes if inbound[rel] == 0]
    dup_content = [v for v in hashes.values() if len(v) > 1]
    dup_names = [v for v in by_stem.values() if len(v) > 1]
    name_pattern = re.compile(r"(?i)\s+(\(\d+\)|copia|copy|final|v\d+|[2-9])\s*$")
    suspicious_names = [rel for rel, n in notes.items() if name_pattern.search(n["stem"]) and n["stem"].lower().count(" ") >= 1 and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", n["stem"])]
    now = time.time()
    ages = [now - n["mtime"] for n in notes.values()]
    stale = [rel for rel, n in notes.items() if now - n["mtime"] > 180 * 86400]
    largest.sort(reverse=True)
    words = [n["words"] for n in notes.values()]
    return {
        "vault": str(root), "audited_at": time.strftime("%Y-%m-%d %H:%M:%S"), "duration_s": round(time.time() - t0, 1),
        "size": {"total_files": total_files, "total_bytes": total_size, "markdown_notes": len(notes), "total_words": sum(words),
                 "avg_words_per_note": round(sum(words) / len(words), 1) if words else 0, "max_folder_depth": deepest},
        "types": {"by_extension": dict(ext_counter.most_common()), "bytes_by_extension": dict(ext_bytes.most_common())},
        "structure": {"folders": dict(sorted(folder_counter.items(), key=lambda kv: -kv[1])[:60]), "folder_count": len(folder_counter)},
        "tags": {"unique": len(tag_counter), "top": dict(tag_counter.most_common(40)), "notes_without_tags": sum(1 for n in notes.values() if not n["tags"])},
        "properties": {"unique": len(prop_counter), "top": dict(prop_counter.most_common(30))},
        "links": {"total_links": sum(link_targets.values()), "unique_targets": len(link_targets), "broken_links": dict(broken.most_common(30)),
                  "broken_count": sum(broken.values()), "most_linked": dict(inbound.most_common(20)), "notes_without_backlinks": len(no_inbound)},
        "duplicates": {"identical_content": dup_content[:50], "same_name_different_folder": dup_names[:50], "suspicious_names": suspicious_names[:50]},
        "orphans": {"count": len(orphans), "sample": orphans[:50]},
        "problem_files": problems[:100], "empty_notes": empty_notes[:50],
        "sensitive": {"notes_with_possible_secrets": len(sensitive), "sample": sensitive[:30], "note": "solo se reportan tipos y conteos; el contenido nunca se muestra ni se guarda"},
        "age": {"stale_180d": len(stale), "oldest_days": int(max(ages) / 86400) if ages else 0, "newest_days": int(min(ages) / 86400) if ages else 0},
        "largest_files": [{"bytes": b, "path": p} for b, p in largest[:15]],
    }


def format_audit(a: dict[str, Any]) -> str:
    s, l, d = a["size"], a["links"], a["duplicates"]
    L = [f"AUDITORÍA DE {a['vault']}  ({a['audited_at']}, {a['duration_s']}s)", "=" * 70,
         f"Archivos: {s['total_files']}  ({s['total_bytes'] / 1e6:.1f} MB)   Notas .md: {s['markdown_notes']}   Palabras: {s['total_words']}   Prof. máx: {s['max_folder_depth']}",
         "", "Tipos: " + ", ".join(f"{k} {v}" for k, v in list(a["types"]["by_extension"].items())[:12]),
         "", f"Carpetas ({a['structure']['folder_count']}), notas por carpeta (top):"] + [f"  {v:5d}  {k}" for k, v in list(a["structure"]["folders"].items())[:20]]
    L += ["", f"Tags únicos: {a['tags']['unique']}  notas sin tags: {a['tags']['notes_without_tags']}", "  top: " + ", ".join(f"#{k}({v})" for k, v in list(a["tags"]["top"].items())[:20])]
    L += ["", f"Properties únicas: {a['properties']['unique']}", "  top: " + ", ".join(f"{k}({v})" for k, v in list(a["properties"]["top"].items())[:15])]
    L += ["", f"Enlaces: {l['total_links']} (a {l['unique_targets']} destinos)  rotos: {l['broken_count']}  notas sin backlinks: {l['notes_without_backlinks']}",
          "  más enlazadas: " + ", ".join(f"{k}({v})" for k, v in list(l["most_linked"].items())[:8])]
    L += ["", f"Duplicados: contenido idéntico {len(d['identical_content'])} grupos; mismo nombre {len(d['same_name_different_folder'])} grupos; nombres sospechosos {len(d['suspicious_names'])}"]
    L += [f"Huérfanas (sin enlaces en ninguna dirección): {a['orphans']['count']}", f"Notas vacías: {len(a['empty_notes'])}", f"Archivos problemáticos: {len(a['problem_files'])}"]
    L += [f"Notas con posibles datos sensibles: {a['sensitive']['notes_with_possible_secrets']}  ({a['sensitive']['note']})"]
    for sx in a["sensitive"]["sample"][:10]:
        L.append(f"  - {sx['path']}: {', '.join(sx['kinds'])}")
    L += [f"Antigüedad: {a['age']['stale_180d']} notas sin tocar en 180 días; la más antigua {a['age']['oldest_days']} días"]
    L += ["", "Nada ha sido modificado."]
    return "\n".join(L)
