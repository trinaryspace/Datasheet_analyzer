# 00 — Freeze every contract

**Wave:** 0
**Blocked by:** nothing (requires `feat/phase5-retrieval` merged)
**Status:** ready-for-agent

**Owns:**
- `src/datasheet_analyzer/models.py`
- `src/datasheet_analyzer/config.py`
- `src/datasheet_analyzer/app/__init__.py`, `app/contracts.py`, `app/main.py`, `app/routers/__init__.py`
- `src/datasheet_analyzer/library/__init__.py`
- `web/package.json`, `web/vite.config.ts`, `web/tsconfig.json`, `web/index.html`
- `web/src/main.tsx`, `web/src/App.tsx`, `web/src/api/types.ts`, `web/src/api/client.ts`
- `tests/unit/test_contracts.py`

**What to build:** Every type, setting, endpoint shape and function signature
that the other 21 tickets code against. Nothing here has behaviour beyond
validation and routing — implementations raise `NotImplementedError` and are
filled in by their owning ticket. Twenty-one agents start the moment this
lands, so a missing signature blocks all of them: be exhaustive, and prefer an
over-specified contract to a gap.

**The one hard constraint:** `SourceDocument` **must not change shape**. It is
embedded in `RawDocument`, which is serialized into
`.cache/extract/<hash>__<backend>.json`; a new required field breaks
validation of every cached extraction. Applicability and labels therefore live
on a new `LibraryDocument` that wraps it. Do not bump
`PdfLayoutBackend.output_version`.

### Models (`models.py`, additive only)

```python
class Applicability(BaseModel):
    kind: Literal["parts", "family", "all"] = "all"
    parts: list[str] = []          # kind == "parts"
    family: str = ""               # kind == "family", e.g. "AFE79xx"
    evidence: str = ""             # how it was decided; never blank in practice
    def covers(self, part_number: str) -> bool: ...
    @property
    def label(self) -> str: ...    # "AD9081", "AFE79xx", "all parts"

class LibraryDocument(BaseModel):
    source: SourceDocument
    applicability: Applicability = Applicability()
    labels: list[str] = []
    added_at: datetime

class JobState(str, Enum):
    QUEUED / EXTRACTING / STRUCTURING / ENRICHING / PUBLISHING / DONE / FAILED / SKIPPED

class AnalyzeJob(BaseModel):
    id: str; pdf_path: str; part_number: str
    applicability: Applicability; state: JobState
    error: str = ""; started_at / finished_at: datetime | None

class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]; text: str
    citations: list[CitationOut] = []; created_at: datetime

class ChatSession(BaseModel):
    id: str; title: str; scope: ScopeRef
    messages: list[ChatMessage] = []; created_at / updated_at: datetime
```

### Settings (`config.py`)

`library_dir` (`DSA_LIBRARY_DIR`, `./library`), `sessions_dir`
(`DSA_SESSIONS_DIR`, `./sessions`), `chat_model` (`DSA_CHAT_MODEL`,
`claude-opus-5`), `chat_max_tokens` (`DSA_CHAT_MAX_TOKENS`, 16000),
`chat_tool_max_tokens` (`DSA_CHAT_TOOL_MAX_TOKENS`, 8000), `serve_host`
(`DSA_SERVE_HOST`, `127.0.0.1`), `serve_port` (`DSA_SERVE_PORT`, 8765),
`analyze_workers` (`DSA_ANALYZE_WORKERS`, 4). Add
`LIBRARY_SCHEMA_VERSION = "1"`; bump `PLOTS_SCHEMA_VERSION` to `"2"` (ticket 04
makes `PlotRecord.file` library-relative). `library_dir` and `sessions_dir` are
absolutized by `resolve()` like the existing two.

### HTTP surface (`app/contracts.py`)

One Pydantic request and response model per endpoint. The endpoint table is the
module docstring and is the single source of truth for tickets 06–20.

| Method | Path | Request | Response | Ticket |
|---|---|---|---|---|
| GET | `/api/parts` | — | `PartsOut` | 06 |
| GET | `/api/projects` | — | `ProjectsOut` | 06 |
| POST | `/api/analyze/scan` | `ScanIn{directory}` | `ScanOut{proposals[]}` | 08 |
| POST | `/api/analyze/start` | `StartIn{directory, proposals[]}` | `StartOut{run_id}` | 07 |
| GET | `/api/analyze/{run_id}/events` | — | SSE of `JobEvent` | 07 |
| GET | `/api/library` | — | `LibraryOut{documents[]}` | 09 |
| PATCH | `/api/library/{content_hash}` | `LibraryPatchIn{applicability?, labels?}` | `LibraryDocumentOut` | 09 |
| POST | `/api/chat/resolve-scope` | `ResolveIn{question}` | `ScopeResolution` | 12 |
| POST | `/api/chat/{session_id}/message` | `MessageIn{question, scope?}` | SSE of `ChatEvent` | 12 |
| GET | `/api/sessions` | — | `SessionsOut` | 15 |
| POST | `/api/sessions` | `SessionCreateIn` | `SessionOut` | 15 |
| GET | `/api/sessions/{id}` | — | `SessionOut` | 15 |
| GET | `/api/sessions/{id}/export` | — | `text/markdown` | 15 |
| GET | `/api/locate` | query `part, doc_hash, page, needle` | `LocateOut` | 13 |
| GET | `/api/pdf/{content_hash}` | — | `application/pdf` | 14 |

Key shapes: `ScopeRef{kind: "part"|"project", name: str}`;
`ScopeResolution{scope: ScopeRef|None, confident: bool, candidates: list[ScopeRef], question: str}`
(`scope is None and candidates` means ask the user — never guess);
`DocProposal{pdf_path, filename, part_number, applicability, evidence, page_count}`;
`JobEvent{run_id, job_id, part_number, state, detail, at}`;
`ChatEvent{type: "token"|"tool"|"citation"|"scope"|"done"|"error", ...}`;
`LocateOut{found: bool, page: int, rects: list[RectOut], reason: str}` where
`RectOut{x0,y0,x1,y1}` in PDF points and `found=False` carries a human reason
and an empty `rects`; `CitationOut` mirrors `retrieve.results.Citation`
verbatim plus its `pages` and `label` properties as fields.

### Function signatures to stub

Create the module and the signature; body is `raise NotImplementedError`.

- `library/store.py`: `class LibraryStore` with `for_settings(settings) -> LibraryStore`, `get(content_hash) -> LibraryDocument | None`, `put(doc) -> None`, `all() -> list[LibraryDocument]`, `for_part(part_number) -> list[LibraryDocument]`, `set_applicability(content_hash, applicability) -> LibraryDocument`, `set_labels(content_hash, labels) -> LibraryDocument`
- `acquire/applicability.py`: `infer(pdf_path: Path, *, first_page_text: str, known_parts: list[str], client: LLMClient | None) -> DocProposal`
- `publish/writer.py`: extend `write_corpus(...)` with a keyword-only `shared_docs_dir: Path | None = None`; when set, document artifacts are written there once and referenced
- `app/deps.py`: `get_settings_dep()`, `get_library()`, `get_retriever(scope: ScopeRef)`, `get_job_registry()`, `get_session_store()`
- `app/scope_resolver.py`: `resolve(question: str, *, parts: list[str], projects: list[str]) -> ScopeResolution`
- `app/locate.py`: `locate(pdf_path: Path, page: int, needle: str) -> LocateOut`
- `app/tools.py`: the nine tool callables mirroring the MCP tool list, each `(**kwargs) -> dict`
- `app/sessions.py`: `class SessionStore` with `create/get/list/append/export_markdown`

### Structural conventions this ticket establishes

- `app/main.py` builds the FastAPI app and **auto-discovers routers**: iterate
  `app/routers/*.py`, import each, `include_router(module.router)`. No later
  ticket edits `main.py`.
- `app/routers/__init__.py` exists and is empty.
- `web/src/App.tsx` discovers routes with `import.meta.glob('./routes/*/route.tsx', {eager: true})`.
  No later ticket edits `App.tsx`.
- `web/src/api/types.ts` mirrors every contract model by hand, and
  `client.ts` exposes one typed function per endpoint plus an SSE helper.
- `web/package.json` scripts: `dev`, `build`, `typecheck`, `test`.

- [ ] `Applicability`, `LibraryDocument`, `JobState`, `AnalyzeJob`, `ChatMessage`, `ChatSession` exist in `models.py` and round-trip through `model_dump_json` / validation
- [ ] `SourceDocument` is byte-identical to before; an existing `.cache/extract/*.json` fixture still deserializes into `RawDocument`
- [ ] `Applicability.covers()` returns True for an exact part, for a part matching a `family` prefix with `xx`/`x` wildcards, and for every part when `kind == "all"`
- [ ] Every setting listed above exists with the stated env var and default; `resolve()` absolutizes `library_dir` and `sessions_dir`
- [ ] `PLOTS_SCHEMA_VERSION == "2"` and `LIBRARY_SCHEMA_VERSION == "1"`
- [ ] Every request and response model in the endpoint table exists in `app/contracts.py` and validates a hand-written example
- [ ] `ScopeResolution` can represent all three states: confident, ambiguous-with-candidates, and no-match
- [ ] `LocateOut` can represent a miss (`found=False`, empty `rects`, non-empty `reason`)
- [ ] Every stub module imports cleanly and every stubbed function raises `NotImplementedError`
- [ ] `app/main.py` auto-discovers routers: a test drops a throwaway router file into `app/routers/` and asserts its path is mounted
- [ ] `web/` scaffold installs and `npm run typecheck` passes with `web/src/api/types.ts` present
- [ ] `web/src/api/types.ts` has one exported type per contract model, checked by a test that compares the exported names against a list
- [ ] `ruff check` and `ruff format --check` clean on every owned Python file
