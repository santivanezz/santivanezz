# DECISIONS (Technology Decision Records)

| Technology | Reason | Alternatives | Trade-offs |
|---|---|---|---|
| **Python 3.10+** para el motor | ecosistema de NLP/embeddings, SQLite en stdlib, tú ya lo usas | Node/TS único stack | dos lenguajes (plugin TS + motor Py); a cambio, acceso a sentence-transformers y pypdf |
| **SQLite + FTS5** | un archivo, transaccional, full-text integrado, cero servidores | Postgres, DuckDB | sin concurrencia multi-máquina (no hace falta) |
| **Vectores en SQLite + numpy** | miles de notas → decenas de miles de chunks: producto matricial en ms; sin dependencia extra | FAISS, LanceDB, Chroma | por encima de ~500k chunks habría que cambiar `VectorIndex` (punto único) |
| **Grafo en tablas SQL** | relaciones simples, consultas con JOIN, sin otro almacén | NetworkX, Neo4j | análisis de grafo avanzado sería más cómodo en NetworkX; hoy no aporta valor |
| **Embeddings hashed como fallback** | funciona offline sin descargar nada, determinista, permite instalar y probar en minutos | exigir sentence-transformers | calidad semántica menor; `auto` usa el local si está instalado |
| **sentence-transformers multilingual MiniLM** como local recomendado | multilingüe (es/en), 118 MB, CPU-friendly | modelos mayores (bge-m3), embeddings de nube | menos preciso que bge-m3; mucho más ligero |
| **Servidor HTTP stdlib** en vez de FastAPI | ~20 endpoints JSON en localhost; cero dependencias; arranque instantáneo | FastAPI+uvicorn | sin OpenAPI automático ni validación pydantic; documentado en ARCHITECTURE.md |
| **Watcher por polling + watchdog opcional** | polling cada 2 s es suficiente y robusto en OneDrive; watchdog si está | solo watchdog | latencia de 2 s en el peor caso; el plugin notifica al instante de todas formas |
| **Extracción heurística (regex ES/EN) primero, LLM opcional después** | determinista, offline, auditable, sin coste; etiquetada `AI_INFERENCE`/`USER_ASSERTION` | LLM para todo | menor recall en frases atípicas; fase 2 añade LLM opcional |
| **Contradicciones por sujeto + aspecto (tecnología/fecha/número)** | reduce falsos positivos; explica el porqué | NLI con modelo | detecta solo patrones explícitos; nunca decide cuál es verdad |
| **RRF (reciprocal rank fusion)** para combinar señales | robusto sin calibrar escalas entre BM25 y coseno | pesos lineales | menos ajustable finamente |
| **Anthropic SDK oficial** para Claude; urllib para OpenAI/Ollama | seguir la guía oficial; Ollama/OpenAI son un POST simple | shims OpenAI-compatibles | dependencia opcional `anthropic` |
| **TOML + variables de entorno** | legible, stdlib (`tomllib`), secretos fuera del archivo | YAML/JSON | escritura TOML hecha a mano (mínima) |
| **Notas generadas en `SERGIO BRAIN/` con marca `sergio_brain: generated`** | zero data loss verificable; el usuario ve todo en Obsidian | DB-only | más archivos en la bóveda (carpeta dedicada) |
| **Obsidian plugin con `requestUrl`** | evita CORS/Electron; funciona en escritorio | fetch directo | solo escritorio (`isDesktopOnly`) |
| **Extensión MV3 mínima** | capturas explícitas, sin permisos de historial | sin extensión | requiere modo desarrollador o publicación en la store |
