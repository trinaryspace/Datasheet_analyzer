"""The MCP server itself: thirteen tools, two resources, local stdio only.

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
| `find_plots` | part or project | the plot catalog, filtered by text, section, tags **or axis** |
| `get_figure` | part | one figure **as an image content block** |
| `ask` | part or project | one cited, budget-bounded answer pack |
| `find_pin` | part or project | pins by designator, name, description or type |
| `find_register` | part or project | registers by name, address or bit field |
| `get_card` | part | one task-shaped design card, every value cited |
| `compare_parts` | named parts | two or more parts aligned on one parameter or card |

The last four are phase 6's **derived** artifacts, and they carry one extra
rule the extracted ones do not need: nothing on them is generated. Every value
is printed text copied verbatim, a number computed from it by a named pure
function, or a label from a checked-in lexicon — and each ships with the
record and printed page it came from, so a client can check a derived number
the same way it checks an extracted one (AGENTS.md invariant 8, ADR 0007). A
field that could not be filled is null and says why.

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
from datasheet_analyzer.derive.cards import load_or_build_card
from datasheet_analyzer.derive.compare import compare_parts
from datasheet_analyzer.derive.pins import find_pins, load_part_pins, no_pins_message
from datasheet_analyzer.derive.pins import type_counts as pin_type_counts
from datasheet_analyzer.derive.registers import (
    find_registers,
    load_part_registers,
    no_bit_fields_message,
    no_registers_message,
)
from datasheet_analyzer.mcp_server.responses import (
    ASK_BUDGET_FLOOR,
    CAP_SETTING,
    SCHEMAS,
    capped_markdown,
    card_rows,
    citations_of,
    comparison_rows,
    envelope,
    error_response,
    finalize,
    fit_list,
    fit_text,
    response_tokens,
)
from datasheet_analyzer.models import CARD_KINDS
from datasheet_analyzer.projects import (
    INDEX_FILENAME as PROJECT_INDEX_FILENAME,
)
from datasheet_analyzer.projects import (
    ProjectError,
    is_built,
    list_projects,
    load_project,
    project_dir,
)
from datasheet_analyzer.retrieve import (
    INDEX_FILENAME,
    Retriever,
    discover_parts,
)
from datasheet_analyzer.retrieve.scope import resolve_part, resolve_scope

SERVER_NAME = "datasheet-analyzer"
#: Resource URIs, also the templates a client may fill in itself.
PART_INDEX_URI = "dsa://part/{part}/" + INDEX_FILENAME
PROJECT_INDEX_URI = "dsa://project/{name}/" + PROJECT_INDEX_FILENAME


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
            "`find_plots` to narrow. For design work there are derived views: "
            "`find_pin` during schematic capture, `find_register` for bring-up, "
            "`get_card` for a task-shaped summary (power, thermal, interface, "
            "limits) and `compare_parts` to choose between devices. Every value "
            "carries a page citation and a confidence grade; open the printed "
            "page when a grade is `low`. Nothing on a derived view is "
            "generated — a field that could not be filled is null and says why. "
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
                "get_index",
                error,
                max_tokens=cap,
                part=part,
                revision="",
                file="",
                text="",
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
                "search",
                error,
                max_tokens=cap,
                part=part,
                project=project,
                hits=[],
                count=0,
                total=0,
            )
        unavailable = scope.search_unavailable()
        if unavailable:
            return error_response(
                "search",
                unavailable,
                max_tokens=cap,
                part=part,
                project=project,
                hits=[],
                count=0,
                total=0,
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
                "find_spec",
                error,
                max_tokens=cap,
                part=part,
                project=project,
                hits=[],
                suggestions=[],
                count=0,
                total=0,
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
        near_y: str = "",
    ) -> dict[str, Any]:
        """Filter the plot catalog by caption/conditions text, section or tags.

        The narrowing step before `get_figure`: each hit carries the figure's
        caption, its citation, its grade and the corpus-relative image path to
        pass to `get_figure`.

        **Axis filters (phase 6).** `x_label` / `y_label` are case-insensitive
        substrings of the axis titles the figure prints; `near_x` / `near_y`
        take a quantity ("3.5GHz", "-40") and keep only figures whose printed
        axis range covers it, converting SI prefixes on both sides. Together
        they narrow hundreds of figures to the one worth opening *before* a
        vision token is spent. A figure whose axes could not be read is not a
        match for an axis filter — its `axes.confidence` says why.
        """
        scope, error = _scope(part, project)
        if scope is None:
            return error_response(
                "find_plots",
                error,
                max_tokens=cap,
                part=part,
                project=project,
                hits=[],
                count=0,
                total=0,
            )
        payload = envelope("find_plots", max_tokens=cap, part=part, project=project)
        payload["hits"] = [
            hit.as_dict()
            for hit in scope.plots(
                q=q,
                section=section,
                tags=list(tags or []),
                x_label=x_label,
                y_label=y_label,
                near_x=near_x,
                near_y=near_y,
            )
        ]
        return fit_list(payload, "hits", cap)

    # --- derived artifacts (phase 6) -----------------------------------------

    @server.tool(name="find_pin", meta=declared("find_pin"))
    def find_pin(
        part: str = "", project: str = "", q: str = "", pin_type: str = ""
    ) -> dict[str, Any]:
        """Look up pins by designator, signal name or description, or by type.

        The table a designer lives inside during schematic capture. `q` is
        matched against the designator ("A1"), the name ("VDD18") and the
        description; `pin_type` filters on the lexicon label
        (`power|ground|analog|digital|clock|rf|nc|reserved|unknown`) and
        `unknown` is a legitimate thing to ask for — those are the pins this
        tool would not label, and hiding them would hide the lexicon's gaps.

        A part whose datasheet prints no pin table this tool could read is
        named in `parts_without_pins` and carries a `warning`: "no pin table
        was published" and "this device has no pins" are different findings.
        """
        scope, error = _scope(part, project)
        if scope is None:
            return error_response(
                "find_pin",
                error,
                max_tokens=cap,
                part=part,
                project=project,
                hits=[],
                counts={},
                parts_without_pins=[],
                count=0,
                total=0,
            )
        hits, without, warnings = _pins_for(scope, q=q, pin_type=pin_type)
        payload = envelope("find_pin", max_tokens=cap, part=part, project=project)
        payload["hits"] = [hit.as_dict() for hit in hits]
        payload["counts"] = pin_type_counts(hit.record for hit in hits)
        payload["parts_without_pins"] = without
        payload["warning"] = " ".join(warnings)
        return fit_list(payload, "hits", cap)

    @server.tool(name="find_register", meta=declared("find_register"))
    def find_register(
        part: str = "", project: str = "", name: str = "", addr: str = "", field: str = ""
    ) -> dict[str, Any]:
        """Look up registers by name, address, or bit-field name.

        The bring-up table: address, name, reset value and access, each cited
        to the page that printed it. `addr` resolves by parsed value, so
        `0x1A04`, `0x1a04` and `6660` are one question.

        `bit_fields` reports whether any published register for this scope
        carries a bit breakdown at all. It is `false` for every corpus today,
        and `field` therefore matches nothing — that is a recorded shortcoming,
        not an empty answer, and the `warning` says so rather than letting an
        empty result read as "this register has no fields".
        """
        scope, error = _scope(part, project)
        if scope is None:
            return error_response(
                "find_register",
                error,
                max_tokens=cap,
                part=part,
                project=project,
                hits=[],
                parts_without_registers=[],
                bit_fields=False,
                count=0,
                total=0,
            )
        hits, without, warnings, has_fields = _registers_for(
            scope, name=name, addr=addr, field=field
        )
        payload = envelope("find_register", max_tokens=cap, part=part, project=project)
        payload["hits"] = [hit.as_dict() for hit in hits]
        payload["parts_without_registers"] = without
        payload["bit_fields"] = has_fields
        payload["warning"] = " ".join(warnings)
        return fit_list(payload, "hits", cap)

    @server.tool(name="get_card", meta=declared("get_card"))
    def get_card(part: str, card: str) -> dict[str, Any]:
        """Build one task-shaped view over a part: power, thermal, interface, limits.

        A card answers a design question that is otherwise a scavenger hunt
        across several sections — "what rails does this need and how much
        current?" — by composing records that already exist. **Nothing on a
        card is generated:** every value is either printed text copied
        verbatim, a number computed from it by a named pure function, or a
        label from a checked-in lexicon, and every one carries the record and
        page it came from. A field that could not be filled is null and says
        why in `null_reason`.

        An empty card is a real answer: this part genuinely does not print
        that data. Cards are per part; to put two parts side by side use
        `compare_parts` with the same `card`.
        """
        scope, error = _part_scope(part)
        if scope is None:
            return error_response("get_card", error, max_tokens=cap, part=part, **_EMPTY_CARD)
        if card not in CARD_KINDS:
            return error_response(
                "get_card",
                f"unknown card {card!r} — expected one of {', '.join(CARD_KINDS)}",
                max_tokens=cap,
                part=scope.part,
                **{**_EMPTY_CARD, "card": card},
            )
        built = load_or_build_card(
            scope.part_dir, scope.part, card, card_version=settings.card_version
        )
        payload = envelope("get_card", max_tokens=cap, part=scope.part)
        payload["card"] = built.card
        payload["card_version"] = built.card_version
        payload["schema_version"] = built.schema_version
        payload["generated_at"] = built.generated_at.isoformat()
        payload["rows"] = card_rows(built)
        payload["unresolved"] = list(built.unresolved)
        payload["warnings"] = list(built.warnings)
        payload["sources"] = list(built.sources)
        payload["warning"] = " ".join(built.warnings)
        return fit_list(payload, "rows", cap)

    @server.tool(name="compare_parts", meta=declared("compare_parts"))
    def compare_parts_tool(parts: list[str], symbol: str = "", card: str = "") -> dict[str, Any]:
        """Put two or more parts side by side on one parameter or one card.

        Rows are aligned by alias-resolved symbol; each row carries both
        verbatim values with both page cites, and an SI delta **only where
        both sides parsed numerically**. A parameter one part prints and
        another does not is reported in `missing_from`, never dropped, and
        `parse_coverage` names the rows that could not be compared and why.
        This is the part-selection question answered in one call.
        """
        comparison, reason = compare_parts(
            list(parts or []), symbol=symbol, card=card, parts_dir=settings.parts_dir
        )
        if comparison is None:
            return error_response(
                "compare_parts", reason, max_tokens=cap, **_empty_comparison(parts, card, symbol)
            )
        payload = envelope("compare_parts", max_tokens=cap)
        payload["parts"] = list(comparison.parts)
        payload["baseline"] = comparison.baseline
        payload["mode"] = comparison.mode
        payload["card"] = comparison.card
        payload["symbol"] = comparison.symbol
        payload["resolved_symbol"] = comparison.resolved_symbol
        payload["schema_version"] = comparison.schema_version
        payload["generated_at"] = comparison.generated_at.isoformat()
        payload["rows"] = comparison_rows(comparison)
        payload["coverage"] = comparison.coverage.model_dump(mode="json")
        payload["parse_coverage"] = [
            {
                "part": entry.part_number,
                "considered": entry.considered,
                "parsed": entry.parsed,
                "unparsed": list(entry.unparsed),
            }
            for entry in comparison.parse_coverage
        ]
        payload["unresolved"] = list(comparison.unresolved)
        payload["warnings"] = list(comparison.warnings)
        payload["warning"] = " ".join(comparison.warnings)
        return fit_list(payload, "rows", cap)

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
                f"no section matching {ref!r} in part {scope.part} — list them with `get_index`",
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

        Bound to this server's settings and otherwise nothing but a call into
        `retrieve.scope.resolve_scope` — the one implementation the CLI, this
        server and the web application share. It chooses a scope and nothing
        else; both branches hand back an object from `retrieve/`, which is why
        this server can format an answer without knowing how one is found.
        """
        return resolve_scope(part, project, settings=settings)

    def _part_scope(part: str):
        """`(Retriever, "")` for one built part, or `(None, reason)`."""
        return resolve_part(part, settings=settings)

    def _part_summary(part_dir: Path) -> dict[str, Any]:
        """One row of `list_parts`, read off the manifest the publisher wrote."""
        scope = Retriever.for_part(part_dir)
        manifest = scope.index.manifest
        if manifest is None:
            return {
                "part": part_dir.name,
                "built": False,
                "revision": "",
                "vendor": "",
                "backends": [],
                "sections": 0,
                "specs": 0,
                "plots": 0,
                "tokens": 0,
                "searchable": False,
                "spec_confidence": {},
                "plot_confidence": {},
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
            return {"name": name, "parts": [], "interfaces": "", "built": False, "error": str(exc)}
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
    "section": "",
    "title": "",
    "file": "",
    "page_start": None,
    "page_end": None,
    "citation": "",
    "confidence": "unknown",
    "matched_via": "",
    "text": "",
}

#: The same debt for `get_card`: a refusal is a payload in the declared shape,
#: so every body key is present and empty rather than absent.
_EMPTY_CARD: dict[str, Any] = {
    "card": "",
    "card_version": "",
    "schema_version": "",
    "generated_at": "",
    "rows": [],
    "unresolved": [],
    "warnings": [],
    "sources": [],
    "count": 0,
    "total": 0,
}


def _empty_comparison(parts: list[str], card: str, symbol: str) -> dict[str, Any]:
    """A refused `compare_parts`, still carrying what the caller asked for."""
    return {
        "parts": [p for p in list(parts or []) if p],
        "baseline": "",
        "mode": "",
        "card": card,
        "symbol": symbol,
        "resolved_symbol": "",
        "schema_version": "",
        "generated_at": "",
        "rows": [],
        "coverage": {"considered": 0, "compared": 0, "reasons": []},
        "parse_coverage": [],
        "unresolved": [],
        "warnings": [],
        "count": 0,
        "total": 0,
    }


def _part_roots(scope) -> list[tuple[Path, str]]:
    """`[(directory, part)]` for a scope, whether it is one part or a design.

    The derived artifacts are read off a part directory rather than through a
    retriever, so this is the one place the two scope shapes are flattened —
    and a project keeps membership order, exactly as every other project-wide
    lookup does.
    """
    members = getattr(scope, "members", None)
    if members is None:
        return [(scope.part_dir, scope.part)]
    return [(m.part_dir, m.part) for m in members]


def _pins_for(scope, *, q: str, pin_type: str) -> tuple[list, list[str], list[str]]:
    """`(hits, parts_without_pins, warnings)` for one part or a whole design.

    A part that published no pin table is *named*, not skipped: an empty hit
    list from a corpus that never read a pin table would read as "this device
    has no pins", which is never true of a real device.
    """
    hits: list = []
    without: list[str] = []
    warnings: list[str] = []
    for root, part in _part_roots(scope):
        part_pins = load_part_pins(root, part)
        if not part_pins.sets:
            without.append(part)
            continue
        warnings.extend(part_pins.warnings)
        hits.extend(find_pins(part_pins, q=q, pin_type=pin_type))
    return hits, without, [*warnings, *(no_pins_message(p) for p in without)]


def _registers_for(
    scope, *, name: str, addr: str, field: str
) -> tuple[list, list[str], list[str], bool]:
    """`(hits, parts_without_registers, warnings, any_bit_fields)`.

    `any_bit_fields` is what tells a caller that asked for a bit field apart
    from a caller that asked for one nobody has: the first is an empty result,
    the second is a recorded gap, and the warning says which this is.
    """
    hits: list = []
    without: list[str] = []
    answered: list[str] = []
    warnings: list[str] = []
    has_fields = False
    for root, part in _part_roots(scope):
        part_registers = load_part_registers(root, part)
        if not part_registers.sets:
            without.append(part)
            continue
        answered.append(part)
        has_fields = has_fields or part_registers.has_bit_fields
        warnings.extend(part_registers.warnings)
        hits.extend(find_registers(part_registers, name=name, addr=addr, field=field))
    if field and not has_fields:
        warnings.extend(no_bit_fields_message(p) for p in answered)
    return hits, without, [*warnings, *(no_registers_message(p) for p in without)], has_fields


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
