import os
from pathlib import Path

import pytest

from sergio_brain.config import Config
from sergio_brain.engine import Engine


def write(root: Path, rel: str, text: str) -> Path:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


@pytest.fixture
def vault(tmp_path: Path) -> Path:
    v = tmp_path / "Boveda Sergio"
    (v / ".obsidian").mkdir(parents=True)
    write(v, "Proyectos/Dashboard Ventas/Dashboard Ventas.md", """---
project: Dashboard Ventas
tags: [proyecto/dashboard-ventas, trabajo]
date: 2026-09-10
---
# Dashboard Ventas

Objetivo: construir un dashboard en Power BI para el área comercial.

El proyecto usa Python para la extracción de datos y Power Query para la transformación.
El proyecto será implementado en enero.

Tengo que revisar el modelo de datos con Carlos antes del 2026-09-25.
Decidí utilizar Power Query en lugar de VBA porque es más mantenible.

Ver [[Erlang C]] para el dimensionamiento del call center.
""")
    write(v, "Reuniones/Reunion Dashboard 2026-09-15.md", """---
tags: [meeting, trabajo]
people: [Carlos, Ana]
project: Dashboard Ventas
---
# Reunión Dashboard 15 Sep

Con Carlos y Ana revisamos el avance del [[Dashboard Ventas]].

El proyecto migró a TypeScript para el frontend de reportes.
El proyecto será implementado en marzo.

- [ ] Enviar el informe a Ana
- [x] Preparar la demo
Acordamos usar DAX para las medidas.
Hoy aprendí que Power Query no soporta bien tablas mayores a 1M de filas.
""")
    write(v, "Conceptos/Erlang C.md", """---
tags: [concepto, estudio]
---
# Erlang C

Erlang C se utiliza para calcular la probabilidad de espera en un call center dado un número de agentes y una tasa de llegadas.
Se usa en dimensionamiento de personal y en planificación de capacidad.
""")
    write(v, "Conceptos/Lean.md", "# Lean\nLean es una filosofía de mejora continua orientada a eliminar desperdicios en los procesos y flujos de trabajo.\nLa automatización de procesos repetitivos reduce el desperdicio.\n")
    write(v, "Conceptos/BPM.md", "# BPM\nBPM (Business Process Management) es la disciplina de modelar, ejecutar y mejorar procesos de negocio.\nLa mejora continua de procesos y flujos de trabajo elimina desperdicios y automatiza tareas repetitivas.\n")
    write(v, "Notas secretas.md", "# Config\npassword: SuperSecreta123\napi_key = sk-ant-abcdefghijklmnopqrstuvwxyz1234567890\n")
    write(v, "Privada.md", "---\ntags: [do_not_index]\n---\n# Privada\nEsto nunca debe indexarse. PALABRACLAVESECRETA\n")
    return v


@pytest.fixture
def engine(vault: Path, tmp_path: Path) -> Engine:
    cfg = Config(vault_path=str(vault), data_dir=str(tmp_path / "data"))
    cfg.ai.embedding_provider = "hashed"
    e = Engine(cfg)
    e.indexer.index_all(force=False)
    yield e
    e.close()
