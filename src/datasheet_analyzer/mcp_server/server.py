"""The MCP server itself: nine tools, two resources, local stdio only.

**This is a front end.** It holds no retrieval logic — no corpus walk, no
parsing of corpus artifacts, no hand-built citation string. Every lookup goes
through `retrieve/`, every citation comes from `Citation`, every JSON hit shape
comes from the hit's own `as_dict()`, and the answer pack is the one `dsa ask`
already builds. That is the seam the phase exists to enforce: the CLI and this
server can disagree about *formatting* and can never disagree about what the
corpus says. `tests/unit/test_mcp_server.py::TestMcpServerIsFormatOnly` fails
the moment retrieval creeps back in here.

| Tool | Scope | Returns |
|---|---|---|
| `list_parts` | — | built parts: revision, vendor, section/spec/plot counts, grade mix |
| `list_projects` | — | projects, their members and whether each is built |
| `get_index` | part | the part's `INDEX.md` |
| `search` | part or project | BM25 hits, each cited by construction |
| `find_spec` | part or project | spec records through the alias ladder |
| `read_section` | part | one section's verbatim markdown, budgeted |
| `find_plots` | part or project | the plot catalog, filtered |
| `get_figure` | part | one figure **as an image content block** |
| `ask` | part or project | one cited, budget-bounded answer pack |

Resources `dsa://part/<PART>/INDEX.md` and
`dsa://project/<NAME>/PROJECT_INDEX.md` let a client pin an index into context
without spending a tool call. Both are registered as templates *and* as
concrete resources for what exists on disk at start-up, so a client's resource
list shows the corpora that are actually there — and an empty parts directory
lists nothing rather than failing.

Scope decisions, recorded in the Phase 5 plan: local stdio, no HTTP, no auth,
no multi-tenancy. Everything a caller can reach is under `parts_dir` /
`projects_dir`, and `Retriever.corpus_path` is the only thing that turns a
caller's string into a filesystem path.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any

from mcp.server import MCPServer
from mcp.server.mcpserver.resources import FunctionResource
from mcp.types import CallToolResult, ImageContent, TextContent

from datasheet_analyzer.config import PIPELINE_VERSION, Settings, get_settings
from datasheet_analyzer.mcp_server.responses import (
    ASK_BUDGET_FLOOR,
    CAP_SETTING,
    SCHEMAS,
    capped_markdown,
    citations_of,
    envelope,
    error_response,
    finalize,
    fit_list,
    fit_text,
    response_tokens,
)
from datasheet_analyzer.projects import (
    INDEX_FILENAME as PROJECT_INDEX_FILENAME,
)
from datasheet_analyzer.projects import (
    ProjectError,
    is_built,
    list_projects,
    load_project,
    part_dirs,
    project_dir,
)
from datasheet_analyzer.retrieve import (
    INDEX_FILENAME,
    ProjectRetriever,
    Retriever,
    discover_parts,
)

SERVER_NAME = "datasheet-analyzer"
#: Resource URIs, also the templates a client may fill in itself.
PART_INDEX_URI = "dsa://part/{part}/" + INDEX_FILENAME
PROJECT_INDEX_URI = "dsa://project/{name}/" + PROJECT_INDEX_FILENAME

_SCOPE_ERROR = (
    "name exactly one of `part` or `project` — a lookup has to know what it "
    "is asking, and defaulting to 'everything' would make the scope of an "
    "answer implicit"
)


def build_server(settings: Settings | None = None) -> MCPServer:
    """The configured server, with every tool and resource registered.

    Takes its settings by argument so a test can point one server at a
    temporary corpus tree without touching the environment — the same reason
    the pipeline takes them rather than reading globals.
    """
    settings = settings or get_settings()
    cap = settings.mcp_max_tokens
    server = MCPServer(
        name=SERVER_NAME,
        version=PIPELINE_VERSION,
        instructions=(
            "Token-efficient, citation-verified IC datasheet corpora. Start "
            "with `list_parts` or the `dsa://part/<PART>/INDEX.md` resource, "
            "then `ask` for one cited answer, or `search` / `find_spec` / "
            "`find_plots` to narrow. Every value carries a page citation and "
            "a confidence grade; open the printed page when a grade is `low`. "
            f"Every response is capped at {cap} tokens (DSA_MCP_MAX_TOKENS) "
            "and says so when it truncated."
        ),
    )

    def declared(tool: str) -> dict[str, Any]:
        """The tool's declared response schema, shipped in its `_meta`."""
        return {"response_schema": SCHEMAS[tool]}

    # --- catalog -------------------------------------------------------------

    @server.tool(name="list_parts", meta=declared("list_parts"))
    def list_parts() -> dict[str, Any]:
        """List every part corpus: revision, vendor, counts, confidence mix.

        A part that is present but not built is listed with `built: false`
        rather than hidden, so a half-built corpus is visible instead of
        looking like a part that was never acquired.
        """
        payload = envelope("list_parts", max_tokens=cap)
        payload["parts"] = [_part_summary(d) for d in discover_parts(settings.parts_dir)]
        return fit_list(payload, "parts", cap)

    @server.tool(name="list_projects", meta=declared("list_projects"))
    def list_projects_tool() -> dict[str, Any]:
        """List every project: its member parts, their roles, and whether built."""
        payload = envelope("list_projects", max_tokens=cap)
        payload["projects"] = [
            _project_summary(name) for name in list_projects(settings.projects_dir)
        ]
        return fit_list(payload, "projects", cap)

    @server.tool(name="get_index", meta=declared("get_index"))
    def get_index(part: str) -> dict[str, Any]:
        """Read a part's INDEX.md — the always-loadable map of its corpus.

        The cheapest way to orient on a device: section list, page ranges and
        one-line descriptions, already inside a token budget.
        """
        scope, error = _part_scope(part)
        if scope is None:
            return error_response(
                "get_index", error, max_tokens=cap, part=part,
                revision="", file="", text="",
            )
        payload = envelope("get_index", max_tokens=cap, part=scope.part)
        payload["revision"] = _revision(scope)
        payload["file"] = INDEX_FILENAME
        payload["text"] = scope.index_markdown()
        return fit_text(payload, "text", cap)

    # --- lookups -------------------------------------------------------------

    @server.tool(name="search", meta=declared("search"))
    def search(query: str, part: str = "", project: str = "", limit: int = 5) -> dict[str, Any]:
        """Full-text search over a part or a whole project.

        Ranked with BM25 over the index built at publish. Every hit carries its
        section, page range and a snippet — cited by construction, so never
        attribute a page yourself. Returns an error when the corpus has no
        current index: that is "could not look", not "not in the datasheet".
        """
        scope, error = _scope(part, project)
        if scope is None:
            return error_response(
                "search", error, max_tokens=cap, part=part, project=project,
                hits=[], count=0, total=0,
            )
        unavailable = scope.search_unavailable()
        if unavailable:
            return error_response(
                "search", unavailable, max_tokens=cap, part=part, project=project,
                hits=[], count=0, total=0,
            )
        payload = envelope("search", max_tokens=cap, part=part, project=project)
        # A design where only *some* members are searchable can still answer;
        # what it must not do is let the result read as the whole design. That
        # is a warning, not an error: the call succeeded, the coverage did not.
        payload["warning"] = getattr(scope, "search_gap", lambda: "")()
        payload["hits"] = [hit.as_dict() for hit in scope.search(query, limit=limit)]
        return fit_list(payload, "hits", cap)

    @server.tool(name="find_spec", meta=declared("find_spec"))
    def find_spec(
        part: str = "", project: str = "", symbol: str = "", name: str = "", section: str = ""
    ) -> dict[str, Any]:
        """Look up parametric spec records by symbol or by a designer's words.

        Runs the alias ladder (exact symbol, alias phrase, alias prefix family,
        substring, fuzzy); each hit names the rung it matched on in
        `matched_via` and carries its page citation and confidence grade. No
        match returns an empty list plus nearest candidates — never a guess.
        """
        scope, error = _scope(part, project)
        if scope is None:
            return error_response(
                "find_spec", error, max_tokens=cap, part=part, project=project,
                hits=[], suggestions=[], count=0, total=0,
            )
        hits = scope.specs(symbol=symbol, name=name, section=section)
        payload = envelope("find_spec", max_tokens=cap, part=part, project=project)
        payload["hits"] = [hit.as_dict() for hit in hits]
        term = (symbol or name).strip()
        payload["suggestions"] = [] if hits else scope.suggest_specs(term)
        return fit_list(payload, "hits", cap)

    @server.tool(name="find_plots", meta=declared("find_plots"))
    def find_plots(
        part: str = "",
        project: str = "",
        q: str = "",
        section: str = "",
        tags: list[str] | None = None,
        x_label: str = "",
        y_label: str = "",
        near_x: str = "",
    ) -> dict[str, Any]:
        """Filter the plot catalog by caption/conditions text, section, tags or axes.

        The narrowing step before `get_figure`: each hit carries the figure's
        caption, its citation, its grade and the corpus-relative image path to
        pass to `get_figure`.

        `x_label` / `y_label` / `near_x` filter on the figure's **axis catalog**
        (phase 6, ticket 08) — the printed axis titles, and "the x axis covers
        this printed value" for `near_x` ("3.5GHz"), scaled to the axis's own
        printed unit. Every hit also reports its `axis_confidence` and, when a
        reading exists, its `axes` block, so a client can spend one vision call
        on the right figure instead of five on the wrong ones. Because those
        three select on a *derived* value, a corpus whose figures print their
        axes as pixels answers with a `warning` naming the population that could
        not be considered — an empty axis-filtered list is never evidence that no
        such figure exists.
        """
        scope, error = _scope(part, project)
        if scope is None:
            return error_response(
                "find_plots", error, max_tokens=cap, part=part, project=project,
                hits=[], count=0, total=0,
            )
        payload = envelope("find_plots", max_tokens=cap, part=part, project=project)
        payload["hits"] = [
            hit.as_dict()
            for hit in scope.plots(
                q=q, section=section, tags=list(tags or []),
                x_label=x_label, y_label=y_label, near_x=near_x,
            )
        ]
        # `warning` rather than `error`: the call was answered, and what is
        # incomplete is the population it could filter — the same distinction a
        # project member with no search index gets. Empty for a lookup that
        # filtered on no axis at all.
        payload["warning"] = scope.plot_axis_gap_for(
            x_label=x_label, y_label=y_label, near_x=near_x
        )
        return fit_list(payload, "hits", cap)

    @server.tool(name="read_section", meta=declared("read_section"))
    def read_section(part: str, ref: str, max_tokens: int = 0) -> dict[str, Any]:
        """Read one section verbatim, bounded by `max_tokens`.

        `ref` is a section number ("4.3"), a corpus-relative file path, or a
        title substring. The text is the corpus's own markdown; a confidence
        grade is not reported for it, because a grade belongs to an extracted
        record and this is quoted text. Truncation is always announced.
        """
        scope, error = _part_scope(part)
        if scope is None:
            return error_response(
                "read_section", error, max_tokens=cap, part=part, **_EMPTY_SECTION
            )
        hit = scope.resolve_section(ref)
        if hit is None:
            return error_response(
                "read_section",
                f"no section matching {ref!r} in part {scope.part} — list them "
                "with `get_index`",
                max_tokens=cap,
                part=scope.part,
                **_EMPTY_SECTION,
            )
        payload = envelope("read_section", max_tokens=cap, part=scope.part)
        payload["section"] = hit.section.number
        payload["title"] = hit.section.title
        payload["file"] = hit.section.file
        payload["page_start"] = hit.citation.page_start
        payload["page_end"] = hit.citation.page_end
        payload["citation"] = hit.citation.label
        payload["confidence"] = hit.confidence
        payload["matched_via"] = hit.matched_via
        payload["citations"] = [hit.citation.label]
        payload["text"] = scope.section_text(hit.section)
        return fit_text(payload, "text", cap, requested=max_tokens)

    @server.tool(name="get_figure", meta=declared("get_figure"))
    def get_figure(part: str, file: str) -> CallToolResult:
        """Return one cataloged figure as an image content block.

        `file` is the corpus-relative path a `find_plots` hit reported. The
        image travels with the record's caption, citation and grade, because a
        picture presented without the page it came from is not evidence. Paths
        outside the part directory are refused, and a file no plot record
        claims is refused too — an uncited image is not an answer.
        """
        scope, error = _part_scope(part)
        if scope is None:
            return _figure_error("get_figure", error, part=part, cap=cap)

        # Path safety is checked first and on the *caller's* string, so an
        # attempt to leave the part directory is refused for that reason and
        # told so — not silently re-labelled "no such figure".
        if scope.corpus_path(file) is None:
            return _figure_error(
                "get_figure",
                f"refused {file!r}: a figure path must stay inside the part "
                f"directory (relative, no '..', no absolute paths)",
                part=scope.part,
                cap=cap,
            )
        hit = scope.plot_for_file(file)
        if hit is None:
            return _figure_error(
                "get_figure",
                f"no cataloged figure {file!r} in part {scope.part} — narrow "
                "the catalog with `find_plots` and pass a hit's `file`",
                part=scope.part,
                cap=cap,
            )
        # Read what the *catalog* recorded, not what the caller typed: the
        # bytes returned must be the ones the citation above refers to.
        path = scope.corpus_path(hit.file)
        if path is None:
            return _figure_error(
                "get_figure",
                f"the catalog records an unusable path for {hit.record.id} "
                f"({hit.file!r}) — rebuild the part",
                part=scope.part,
                cap=cap,
            )
        try:
            blob = path.read_bytes()
        except OSError as exc:
            return _figure_error(
                "get_figure",
                f"figure {hit.file} is cataloged but not on disk ({exc}) — "
                f"rebuild the part to render its images",
                part=scope.part,
                cap=cap,
            )

        payload = envelope("get_figure", max_tokens=cap, part=scope.part)
        payload["figure"] = {
            "part": scope.part,
            "file": hit.file,
            "mime_type": _mime_type(path),
            "bytes": len(blob),
            "id": hit.record.id,
            "caption": hit.record.caption,
            "figure_number": hit.record.figure_number,
            "section": hit.citation.section,
            "page_start": hit.citation.page_start,
            "page_end": hit.citation.page_end,
            "citation": hit.citation.label,
            "confidence": hit.confidence,
        }
        payload["citations"] = citations_of([payload["figure"]])
        payload = finalize(payload, cap)
        # The image block is atomic — see `responses`: trimming base64 makes a
        # corrupt PNG, not a shorter one, so the cap governs the JSON beside it.
        return CallToolResult(
            content=[
                _json_block(payload),
                ImageContent(
                    type="image",
                    data=base64.b64encode(blob).decode("ascii"),
                    mime_type=payload["figure"]["mime_type"],
                ),
            ],
            structured_content=payload,
        )

    @server.tool(name="ask", meta=declared("ask"))
    def ask(question: str, part: str = "", project: str = "", budget: int = 0) -> dict[str, Any]:
        """One question in, one cited answer pack out.

        Routes deterministically — spec ladder, then figures, then full text —
        with no model in the decision, and reports which route answered. Every
        row carries its citation and grade; the pack states its own budget and
        announces anything it had to drop.
        """
        scope, error = _scope(part, project)
        if scope is None:
            return error_response(
                "ask", error, max_tokens=cap, part=part, project=project, pack=None
            )
        return _ask_within_cap(
            scope,
            question,
            budget or settings.ask_budget,
            part=part,
            project=project,
            cap=cap,
        )

    # --- resources -----------------------------------------------------------

    @server.resource(
        PART_INDEX_URI,
        name="part-index",
        description="A part's always-loadable INDEX.md",
        mime_type="text/markdown",
    )
    def part_index(part: str) -> str:
        return _part_index_text(part)

    @server.resource(
        PROJECT_INDEX_URI,
        name="project-index",
        description="A project's always-loadable PROJECT_INDEX.md",
        mime_type="text/markdown",
    )
    def project_index(name: str) -> str:
        return _project_index_text(name)

    def _part_index_text(part: str) -> str:
        scope, error = _part_scope(part)
        if scope is None:
            return error
        return capped_markdown(scope.index_markdown(), cap)

    def _project_index_text(name: str) -> str:
        try:
            project = load_project(name, settings.projects_dir)
        except ProjectError as exc:
            return str(exc)
        path = project_dir(project.name, settings.projects_dir) / PROJECT_INDEX_FILENAME
        try:
            return capped_markdown(path.read_text(encoding="utf-8"), cap)
        except OSError:
            return (
                f"no {PROJECT_INDEX_FILENAME} for project {project.name} — "
                f"build it with `dsa project build {project.name}`"
            )

    # Concrete resources for what exists right now, so a client's resource list
    # shows the corpora on disk instead of only a template it must fill in
    # itself. Zero parts lists zero resources — an empty list, never a failure.
    for part_dir in discover_parts(settings.parts_dir):
        name = part_dir.name
        server.add_resource(
            FunctionResource.from_function(
                fn=(lambda n=name: _part_index_text(n)),
                uri=PART_INDEX_URI.format(part=name),
                name=f"{name} index",
                description=f"{name}: {INDEX_FILENAME}",
                mime_type="text/markdown",
            )
        )
    for name in list_projects(settings.projects_dir):
        server.add_resource(
            FunctionResource.from_function(
                fn=(lambda n=name: _project_index_text(n)),
                uri=PROJECT_INDEX_URI.format(name=name),
                name=f"{name} project index",
                description=f"{name}: {PROJECT_INDEX_FILENAME}",
                mime_type="text/markdown",
            )
        )

    # --- scope resolution ----------------------------------------------------

    def _scope(part: str, project: str):
        """`(Retriever | ProjectRetriever, "")`, or `(None, reason)`.

        The MCP twin of `cli._scope`: it chooses a scope and nothing else.
        Both branches hand back an object from `retrieve/`, which is why this
        server can format an answer without knowing how one is found.
        """
        part, project = (part or "").strip(), (project or "").strip()
        if bool(part) == bool(project):
            return None, _SCOPE_ERROR
        if project:
            try:
                loaded = load_project(project, settings.projects_dir)
            except ProjectError as exc:
                return None, str(exc)
            return (
                ProjectRetriever.for_parts(
                    loaded.name, part_dirs(loaded, settings.parts_dir)
                ),
                "",
            )
        return _part_scope(part)

    def _part_scope(part: str):
        """`(Retriever, "")` for one built part, or `(None, reason)`."""
        part = (part or "").strip()
        if not part:
            return None, "name a `part`"
        if not is_built(part, settings.parts_dir):
            return None, (
                f"no corpus for part {part} under {settings.parts_dir} — build "
                f"it first: `dsa build <pdf> --part {part}`"
            )
        return Retriever.for_part(settings.parts_dir / part), ""

    def _part_summary(part_dir: Path) -> dict[str, Any]:
        """One row of `list_parts`, read off the manifest the publisher wrote."""
        scope = Retriever.for_part(part_dir)
        manifest = scope.index.manifest
        if manifest is None:
            return {
                "part": part_dir.name, "built": False, "revision": "", "vendor": "",
                "backends": [], "sections": 0, "specs": 0, "plots": 0, "tokens": 0,
                "searchable": False, "spec_confidence": {}, "plot_confidence": {},
            }
        stats = manifest.stats
        return {
            "part": manifest.part_number or part_dir.name,
            "built": True,
            "revision": _revision(scope),
            "vendor": manifest.vendor,
            "backends": list(
                dict.fromkeys(st.backend for st in manifest.extraction_stats.values() if st.backend)
            ),
            "sections": stats.n_sections,
            "specs": stats.n_specs,
            "plots": stats.n_plot_files,
            "tokens": stats.total_tokens,
            "searchable": not scope.search_unavailable(),
            "spec_confidence": dict(stats.spec_confidence),
            "plot_confidence": dict(stats.plot_confidence),
        }

    def _project_summary(name: str) -> dict[str, Any]:
        try:
            project = load_project(name, settings.projects_dir)
        except ProjectError as exc:
            return {"name": name, "parts": [], "interfaces": "", "built": False,
                    "error": str(exc)}
        return {
            "name": project.name,
            "parts": [
                {
                    "part": member.part_number,
                    "role": member.role,
                    "built": is_built(member.part_number, settings.parts_dir),
                }
                for member in project.parts
            ],
            "interfaces": project.interfaces,
            "built": (
                project_dir(project.name, settings.projects_dir) / PROJECT_INDEX_FILENAME
            ).exists(),
            "error": "",
        }

    return server


# --- helpers (no scope, no settings) -----------------------------------------

#: The body keys `read_section` still owes a caller when it cannot answer.
_EMPTY_SECTION: dict[str, Any] = {
    "section": "", "title": "", "file": "", "page_start": None,
    "page_end": None, "citation": "", "confidence": "unknown", "matched_via": "",
    "text": "",
}


def _revision(scope: Retriever) -> str:
    """The datasheet revision this corpus was built from; `""` when unknown."""
    manifest = scope.index.manifest
    if manifest is None or not manifest.documents:
        return ""
    return manifest.documents[0].revision


#: Image types by extension — **data, not the host's configuration**, the same
#: rule the vendor brand lexicon and the alias lexicon follow.
#: `mimetypes.guess_type` seeds itself from the Windows registry
#: (`HKCR\.png\Content Type`), so the type a client sees for the very same PNG
#: would depend on the machine the server happens to run on — a box still
#: carrying the historical `image/x-png` would mislabel the image block.
#: Invariant #4 forbids relying on machine state, and an image block is part of
#: the product, not part of the host. These are the extensions
#: `publish/plots.py` writes or downloads (`.png` rendered, `.gif`/`.jpg`/
#: `.jpeg`/`.svg` fetched); anything else is honestly opaque bytes.
FIGURE_MIME_TYPES: dict[str, str] = {
    ".png": "image/png",
    ".gif": "image/gif",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".svg": "image/svg+xml",
    ".webp": "image/webp",
}


def _mime_type(path: Path) -> str:
    """The image type of a cataloged figure, read from its own extension."""
    return FIGURE_MIME_TYPES.get(path.suffix.lower(), "application/octet-stream")


def _json_block(payload: dict) -> TextContent:
    """The payload as the text block that travels beside an image."""
    return TextContent(type="text", text=json.dumps(payload, ensure_ascii=False, indent=2))


def _figure_error(tool: str, message: str, *, part: str, cap: int) -> CallToolResult:
    """A refused `get_figure`: the reason, in the declared shape, flagged."""
    payload = error_response(tool, message, max_tokens=cap, part=part, figure=None)
    return CallToolResult(content=[_json_block(payload)], structured_content=payload, is_error=True)


def _ask_within_cap(
    scope, question: str, budget: int, *, part: str, project: str, cap: int
) -> dict[str, Any]:
    """An answer pack that fits the response cap, shrunk by budget, not by edit.

    A pack protects its own citations against its own budget; the way to make
    one smaller is therefore to *ask for a smaller pack*, never to delete rows
    from the pack it returned — that would strip citations the pack had
    deliberately reserved. So the budget halves until the serialized response
    fits, and if the floor is still too big the response says `over_cap`
    instead of shipping a mutilated answer. A pack serializes to roughly twice
    its own budget (it carries its rendered markdown *and* its structured
    rows), so a cap of a few hundred tokens cannot hold one at all — and that
    is reported, not papered over.
    """
    wanted = max(budget, 1)
    attempt = min(wanted, cap)
    while True:
        pack = scope.ask(question, budget=attempt)
        payload = envelope("ask", max_tokens=cap, part=part, project=project)
        payload["pack"] = pack.as_dict()
        payload["citations"] = list(pack.citations)
        # `truncated` is the pack's own answer: a budget lowered to fit the
        # cap that still dropped nothing has truncated nothing, and saying
        # otherwise would train a caller to ignore the flag.
        payload["truncated"] = pack.truncated
        notes = []
        if attempt < wanted:
            notes.append(
                f"Pack budget reduced from {wanted} to {attempt} tokens to fit "
                f"the {cap}-token response cap ({CAP_SETTING})."
            )
        if pack.notice:
            notes.append(pack.notice)
        payload["notice"] = " ".join(notes)
        if response_tokens(payload) <= cap or attempt <= ASK_BUDGET_FLOOR:
            return finalize(payload, cap)
        attempt = max(ASK_BUDGET_FLOOR, attempt // 2)


def serve_stdio(settings: Settings | None = None) -> None:
    """Run the server on local stdio until the client disconnects.

    The only transport: no HTTP, no port, no auth (Phase 5 plan, Out of
    Scope). A client registers this process in its `mcp.json` and speaks to it
    over the pipe it already owns.
    """
    build_server(settings).run(transport="stdio")


__all__ = [
    "PART_INDEX_URI",
    "PROJECT_INDEX_URI",
    "SCHEMAS",
    "SERVER_NAME",
    "build_server",
    "serve_stdio",
]
