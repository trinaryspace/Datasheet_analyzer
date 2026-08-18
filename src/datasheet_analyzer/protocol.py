"""The corpus agent protocol — one rule text, three destinations.

Phases 1–4 built a corpus that rewards a *disciplined* reader: index first,
never bulk-read, quote the unit, cite the page, believe the grade. That
discipline lived as prose inside `INDEX.md` and, in practice, inside whoever
was driving the corpus. This module promotes it to an artifact that ships
*with the data*:

- `parts/<PART>/AGENT.md`, written at publish beside `INDEX.md`;
- `projects/<NAME>/AGENT.md`, written when the project index is built;
- `.claude/skills/datasheet-corpus/SKILL.md`, checked into this repo so an
  agent working here adopts the protocol without being told.

**The rule text is written once, here.** `RULES` and `CONFIDENCE_ROWS` are the
canonical strings; every destination renders those exact strings and adds only
its own worked examples. Three copies of a protocol is three protocols the
moment one is edited, so `tests/unit/test_protocol.py` asserts that each
canonical line appears verbatim in all three — and that the checked-in
`SKILL.md` is byte-for-byte what `build_skill_markdown()` renders.

Two smaller rules of the same kind:

- **`AGENT.md` is bounded like `INDEX.md` is.** A file an agent loads *every*
  time must be cheap enough to load every time, so it is measured against
  `AGENT_DOC_TOKEN_BUDGET` and the measured size is recorded in the manifest
  (`CorpusStats.agent_doc_tokens`) rather than claimed in a report. Unlike
  `INDEX.md` it does not degrade under pressure: it is a fixed text, and the
  budget is a ceiling on what may be written into it here.
- **The file carries its protocol version** (`PROTOCOL_MARKER`). That is what
  lets `agent_doc_current()` tell a corpus published before this protocol
  existed from one published under it, so the batch skip gate republishes it
  once instead of skipping forever — the same publish-cache-key rule
  `search_index.json` already carries.
"""

from __future__ import annotations

from pathlib import Path

#: Written beside `INDEX.md` (a part) and `PROJECT_INDEX.md` (a project).
AGENT_FILENAME = "AGENT.md"

#: Bumped when the protocol text changes in a way an already-published corpus
#: must not keep serving. Embedded in every emitted file as `PROTOCOL_MARKER`,
#: which `agent_doc_current()` reads — invalidation by embedded version field,
#: as invariant 6 requires.
PROTOCOL_VERSION = "1"
PROTOCOL_MARKER = f"<!-- dsa-agent-protocol: v{PROTOCOL_VERSION} -->"

#: Ceiling on an emitted `AGENT.md`. Small on purpose: this file is loaded
#: alongside `INDEX.md` (3000 tok) and `PROJECT_INDEX.md` (4000 tok), and a
#: protocol that costs as much as the map it explains would not be followed.
#: Measured on landing: 1420 tokens for a part, 1496 for a three-part project,
#: 1596 for the worst case the renderers allow (a long project name and twelve
#: long part numbers). The ceiling leaves that case room rather than sitting on
#: it — this is a bound on a fixed text, not a budget something degrades under.
AGENT_DOC_TOKEN_BUDGET = 1700

#: Member parts named in a project's `AGENT.md` header before it defers to
#: `PROJECT_INDEX.md` — a 40-part design must not push a fixed text over its
#: budget on the strength of its part list alone.
_GLANCE_PARTS = 12

#: The in-repo skill, discoverable by this name.
SKILL_NAME = "datasheet-corpus"
SKILL_RELPATH = f".claude/skills/{SKILL_NAME}/SKILL.md"
SKILL_DESCRIPTION = (
    "Answer hardware questions from a built datasheet corpus (parts/ and "
    "projects/) with page-cited, confidence-graded answers. Use whenever a "
    "question is about a datasheet, a part number, a spec value, a plot or a "
    "project's parts — and before reading any file under parts/."
)

#: **The protocol.** These strings are canonical: every destination renders
#: them verbatim, and the drift test compares against them.
RULES: tuple[str, ...] = (
    (
        "**Index first.** Read `INDEX.md`, decide which section or symbol "
        "answers the question, then fetch exactly that. Never walk `docs/` to "
        "find out what is in it — the index exists so you do not have to."
    ),
    (
        "**Never bulk-read.** A section costs thousands of tokens; a spec row "
        "costs tens. Ask for the row, the plot record or the snippet, and read "
        "a whole section only when the answer really is prose."
    ),
    (
        "**Prefer `ask`.** One call routes the question, returns cited rows, "
        "one supporting excerpt and a verify line, all inside a stated budget. "
        "Drop to `query` / `search` / `plots` when you already know which path "
        "you want."
    ),
    (
        "**Quote values with their units.** A number without its unit is not "
        "an answer. Copy the unit exactly as the corpus holds it — both ohm "
        "glyphs are preserved deliberately, so do not normalize them away."
    ),
    (
        "**Cite the page, every time.** Every hit carries its own citation "
        "(`p.N`, `p.N-M`, `§N, p.N`). Pass it through verbatim; never count, "
        "infer or adjust a page number yourself."
    ),
    (
        "**Check the confidence grade.** Every spec and plot record carries "
        "`high`, `medium`, `low` or `unknown`. It grades the *extraction*, "
        "never the datasheet, and it is never a reason to hide, reorder or "
        "soften a row."
    ),
    (
        "**On `low` or `unknown`, send the designer to the printed page.** "
        "Give the value and the citation, then say plainly that the extraction "
        "was weak and that the printed page is the authority."
    ),
    (
        "**A no-match is an answer.** When nothing matches, say so and offer "
        "the nearest terms the corpus does hold. Never fill the gap from "
        "memory: a value that is not in the corpus is not in the answer."
    ),
    (
        "**Repeat every notice.** Truncation always arrives announced, naming "
        "the budget or cap that caused it. Pass that notice on rather than "
        "presenting a trimmed answer as a complete one."
    ),
)

#: The confidence table, canonical rows (rendered under a shared header).
CONFIDENCE_HEADER: tuple[str, ...] = (
    "| Grade | What the extractor saw | What you do |",
    "|---|---|---|",
)
CONFIDENCE_ROWS: tuple[str, ...] = (
    (
        "| `high` | exact printed page, table reconstructed from its own "
        "declared columns, value present | quote it and cite the page |"
    ),
    (
        "| `medium` | the page is a section range, or the row printed no value "
        "| quote it, cite the range, and say the page is a range |"
    ),
    (
        "| `low` | the grid was rescued by a coarser split, or a unit the "
        "lexicon expected is missing | quote it, cite it, and tell the "
        "designer to open the printed page |"
    ),
    (
        "| `unknown` | not graded — verbatim section text, or a corpus built "
        "before grading | trust the text, not a grade that was never computed |"
    ),
)

#: The fallback sentence, spelled out once (rule 7's normative long form).
FALLBACK_RULE = (
    "A `low` or `unknown` grade never means the row is wrong and never means "
    "you may withhold it. It means: quote the value, quote the unit, give the "
    "citation, and in the same breath tell the designer to open that printed "
    "page in the PDF to confirm it. The corpus is the fast path; the printed "
    "page is the authority."
)


def rules_block() -> list[str]:
    """The numbered rule list, identical in every destination."""
    return ["## The protocol", ""] + [f"{i}. {r}" for i, r in enumerate(RULES, 1)] + [""]


def confidence_block() -> list[str]:
    """The confidence table plus the fallback rule, identical everywhere."""
    return [
        "## Confidence and fallback",
        "",
        *CONFIDENCE_HEADER,
        *CONFIDENCE_ROWS,
        "",
        FALLBACK_RULE,
        "",
    ]


def _cli_block(
    flag: str, value: str, *, pack_header: str, answer: str, label: str = ""
) -> list[str]:
    """Access path 1: the `dsa` CLI, scoped by `--part` or `--project`.

    `pack_header`, `answer` and `label` are what a pack renders differently
    for a design than for one part (the header names the project and its
    members; every answer row and every verify line is labelled with the part
    it came from), so the worked example shows the caller what it will
    actually receive rather than a shape it will not.
    """
    scope = f"{flag} {value}"
    return [
        "## Access path 1 — the `dsa` CLI",
        "",
        "```bash",
        f'dsa ask {scope} "max junction temperature" --budget 3000   # start here',
        f"dsa query {scope} --symbol TJ --json          # exact rows, rung + grade",
        f'dsa search {scope} "sysref setup" --limit 3   # cited sections',
        f'dsa plots {scope} --q "output power" --json   # figure catalog',
        "```",
        "",
        "Worked example — a question in a designer's words, a cited answer out:",
        "",
        "```bash",
        f'$ dsa ask {scope} "what is the maximum junction temperature?"',
        "```",
        "",
        "```text",
        pack_header,
        "### Answer",
        answer,
        "### Supporting excerpt  (§<n> <title>, p.<page>)",
        "<verbatim text from the corpus>",
        "### Verify",
        f"{label}Printed page <page> of <document>.  Confidence: high.",
        "```",
        "",
        (
            "Report the value **with its unit** and the `§<n>, p.<page>` exactly as "
            "printed. Had the grade read `low`, the same answer goes out with "
            '"the extraction here was weak — confirm on printed p.<page>". `dsa ask` '
            "exits 2 when the corpus has no search index: that is a finding about "
            "the corpus (rebuild it), never an answer about the part."
        ),
        "",
    ]


def _mcp_block(key: str, value: str) -> list[str]:
    """Access path 2: the MCP tools, scoped by a `part` or `project` argument."""
    scope = f'"{key}": "{value}"'
    return [
        "## Access path 2 — MCP tools (`dsa serve --mcp`)",
        "",
        (
            "Tools: `list_parts`, `list_projects`, `get_index`, `search`, `find_spec`, "
            "`read_section`, `find_plots`, `get_figure`, `ask`, and the derived "
            "views `find_pin`, `find_register`, `get_card`, `compare_parts`. "
            "Resources: "
            "`dsa://part/<PART>/INDEX.md`, `dsa://project/<NAME>/PROJECT_INDEX.md`."
        ),
        "",
        (
            "Worked example — the same question, then the figure behind it "
            "(call, then the shape that comes back):"
        ),
        "",
        "```text",
        f'ask       {{{scope}, "question": "max junction temperature", "budget": 3000}}',
        (
            '  -> {"pack": {...}, "citations": ["§<n>, p.<page>"], "tokens": 180, '
            '"truncated": false}'
        ),
        f'find_plots {{{scope}, "q": "output power"}}',
        (
            '  -> {"hits": [{"caption": "...", "citation": "§<n>, p.<page>", '
            '"file": "figures/<name>.png", "confidence": "medium"}], "total": 7}'
        ),
        'get_figure {"part": "<PART>", "file": "figures/<name>.png"}',
        "  -> the PNG itself, as an image content block, beside the JSON that cites it",
        "```",
        "",
        (
            "`find_spec` names the ladder rung in `matched_via` and returns "
            "`suggestions` rather than a guess; `read_section`, `get_index` and "
            "`get_figure` are part-scoped, and `get_figure` only returns a file the "
            "plot catalog claims. Every response carries `citations`, a "
            "`confidence` per hit, and `notice` + `truncated` when the "
            "`DSA_MCP_MAX_TOKENS` cap bit — `over_cap` means even the citation "
            "floor did not fit, so raise the cap instead of reading it as a short "
            "answer."
        ),
        "",
    ]


def _header(title: str, lead: list[str]) -> list[str]:
    return [f"# {title}", "", PROTOCOL_MARKER, "", *lead, ""]


def build_part_agent_markdown(
    part_number: str,
    *,
    revision: str = "",
    doc_dirs: list[str] | None = None,
    n_sections: int = 0,
    n_specs: int = 0,
    n_plot_files: int = 0,
) -> str:
    """`parts/<PART>/AGENT.md` — the protocol, scoped to one part.

    The facts at the top are the few an agent needs before its first call
    (what this part is, where its files are, how much is in them); everything
    else is the shared protocol text. Nothing here is derived a second time:
    the counts are the manifest's own.
    """
    dirs = list(doc_dirs or [])
    glance = [
        f"- part **{part_number}**" + (f" — revision {revision}" if revision else ""),
        f"- {n_sections} sections, {n_specs} spec records, {n_plot_files} figure files",
        (
            "- map: `INDEX.md` — sections: `docs/<doc>/sections/*.md` — "
            "table twins: `docs/<doc>/tables/*.csv`"
        ),
    ]
    if dirs:
        glance.append("- documents: " + ", ".join(f"`docs/{d}/`" for d in dirs))
    body = _header(
        f"{part_number} — agent protocol",
        [
            (
                "This is a **retrieval corpus**, not a document. `INDEX.md` beside this "
                "file is the map; this file is the protocol. Both are small enough to "
                "load every time — do that instead of exploring `docs/`."
            ),
        ],
    )
    body += ["## This corpus", "", *glance, ""]
    body += rules_block()
    body += confidence_block()
    body += _cli_block(
        "--part",
        part_number,
        pack_header=f"## {part_number} — <revision>",
        answer=(
            "TJ  Operating junction temperature: <value> <unit> (max) — "
            "§<n>, p.<page>  [high]"
        ),
    )
    body += _mcp_block("part", part_number)
    return "\n".join(body)


def build_project_agent_markdown(
    project_name: str, part_numbers: list[str] | None = None
) -> str:
    """`projects/<NAME>/AGENT.md` — the same protocol, scoped to a design.

    One addition a part cannot have: a project answer must name the part it
    came from, and "no member could be searched" is not the same finding as
    "nothing in this design says that".
    """
    parts = list(part_numbers or [])
    example = parts[0] if parts else "<PART>"
    # The member list is a courtesy here, not the product (`PROJECT_INDEX.md`
    # is), so a large design names the first few and points at the index
    # rather than pushing a fixed-size protocol over its budget.
    listed = ", ".join(parts[:_GLANCE_PARTS])
    if len(parts) > _GLANCE_PARTS:
        listed += f", … (+{len(parts) - _GLANCE_PARTS} more in `PROJECT_INDEX.md`)"
    glance = [
        f"- project **{project_name}** — "
        + (f"{len(parts)} parts: {listed}" if parts else "no parts yet"),
        (
            "- map: `PROJECT_INDEX.md` — then the member part's own `INDEX.md` and "
            "`AGENT.md`"
        ),
    ]
    body = _header(
        f"{project_name} — agent protocol",
        [
            (
                "This is a **design**: several part corpora asked as one. "
                "`PROJECT_INDEX.md` beside this file is the map; this file is the "
                "protocol, and it is the same protocol each member part carries."
            ),
        ],
    )
    body += ["## This project", "", *glance, ""]
    body += rules_block()
    body += [
        "Two more, because this scope spans parts:",
        "",
        (
            "- **Name the part in every answer.** Each hit already carries its part; "
            "pass that through rather than merging two devices into one claim."
        ),
        (
            "- **A gap is not an absence.** When a member could not be searched, the "
            "result says so — report the gap instead of concluding the design does "
            "not have the thing."
        ),
        "",
    ]
    body += confidence_block()
    body += _cli_block(
        "--project",
        project_name,
        pack_header=f"## {project_name} — project ({listed or '<PART>'})",
        answer=(
            f"[{example}] TJ  Operating junction temperature: <value> <unit> "
            "(max) — §<n>, p.<page>  [high]"
        ),
        label=f"{example} — ",
    )
    body += _mcp_block("project", project_name)
    return "\n".join(body)


def build_skill_markdown() -> str:
    """`.claude/skills/datasheet-corpus/SKILL.md` — the in-repo skill.

    Rendered from the same constants as the shipped `AGENT.md` files, which is
    what makes "the skill and the corpus say the same thing" a property of the
    code rather than a promise. The checked-in file is asserted equal to this
    render, so drift fails the suite instead of surviving it.
    """
    body = [
        "---",
        f"name: {SKILL_NAME}",
        f"description: {SKILL_DESCRIPTION}",
        "---",
        "",
        "# Datasheet corpus — retrieval protocol",
        "",
        PROTOCOL_MARKER,
        "",
        (
            "A built corpus lives under `parts/<PART>/` (and a design under "
            "`projects/<NAME>/`). Each one ships this same protocol as its own "
            f"`{AGENT_FILENAME}`; this skill is that text, in the workspace, so it "
            "applies before you have opened anything."
        ),
        "",
        (
            "**Orient first:** `dsa status` lists parts and projects; "
            "`parts/<PART>/INDEX.md` is the map of one; `parts/<PART>/AGENT.md` is "
            "this protocol scoped to that part."
        ),
        "",
    ]
    body += rules_block()
    body += confidence_block()
    body += _cli_block(
        "--part",
        "<PART>",
        pack_header="## <PART> — <revision>",
        answer=(
            "TJ  Operating junction temperature: <value> <unit> (max) — "
            "§<n>, p.<page>  [high]"
        ),
    )
    body += _mcp_block("part", "<PART>")
    body += [
        "## What not to do",
        "",
        (
            "- Do not `grep`/`cat` your way through `docs/**/sections/*.md`: the "
            "search index exists, it is cited by construction, and a hand-attributed "
            "page is exactly the error the corpus was built to prevent."
        ),
        (
            "- Do not answer a datasheet question from your own knowledge of the "
            "part. If the corpus does not hold it, say the corpus does not hold it."
        ),
        (
            "- Do not edit anything under `parts/` or `projects/` by hand — they are "
            "build outputs, rewritten whole on the next build."
        ),
        "",
    ]
    return "\n".join(body)


def write_agent_doc(directory: Path, text: str) -> Path:
    """Write `<directory>/AGENT.md`; return the path."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / AGENT_FILENAME
    path.write_text(text, encoding="utf-8")
    return path


def agent_doc_current(directory: Path) -> bool:
    """Whether `<directory>/AGENT.md` was written by *this* protocol version.

    The publish-cache-key check for the agent doc, called by the batch skip
    gate. A missing file, an unreadable one, or one carrying an older marker
    all read as stale: a corpus published before this protocol existed must
    republish once rather than skip forever with no protocol beside it.
    """
    path = Path(directory) / AGENT_FILENAME
    try:
        return PROTOCOL_MARKER in path.read_text(encoding="utf-8")
    except OSError:
        return False
