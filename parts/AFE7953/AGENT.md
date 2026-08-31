# AFE7953 — agent protocol

<!-- dsa-agent-protocol: v1 -->

This is a **retrieval corpus**, not a document. `INDEX.md` beside this file is the map; this file is the protocol. Both are small enough to load every time — do that instead of exploring `docs/`.

## This corpus

- part **AFE7953** — revision SBASAN1A
- 39 sections, 536 spec records, 492 figure files
- map: `INDEX.md` — sections: `docs/<doc>/sections/*.md` — table twins: `docs/<doc>/tables/*.csv`
- documents: `docs/datasheet-52d435c0/`

## The protocol

1. **Index first.** Read `INDEX.md`, decide which section or symbol answers the question, then fetch exactly that. Never walk `docs/` to find out what is in it — the index exists so you do not have to.
2. **Never bulk-read.** A section costs thousands of tokens; a spec row costs tens. Ask for the row, the plot record or the snippet, and read a whole section only when the answer really is prose.
3. **Prefer `ask`.** One call routes the question, returns cited rows, one supporting excerpt and a verify line, all inside a stated budget. Drop to `query` / `search` / `plots` when you already know which path you want.
4. **Quote values with their units.** A number without its unit is not an answer. Copy the unit exactly as the corpus holds it — both ohm glyphs are preserved deliberately, so do not normalize them away.
5. **Cite the page, every time.** Every hit carries its own citation (`p.N`, `p.N-M`, `§N, p.N`). Pass it through verbatim; never count, infer or adjust a page number yourself.
6. **Check the confidence grade.** Every spec and plot record carries `high`, `medium`, `low` or `unknown`. It grades the *extraction*, never the datasheet, and it is never a reason to hide, reorder or soften a row.
7. **On `low` or `unknown`, send the designer to the printed page.** Give the value and the citation, then say plainly that the extraction was weak and that the printed page is the authority.
8. **A no-match is an answer.** When nothing matches, say so and offer the nearest terms the corpus does hold. Never fill the gap from memory: a value that is not in the corpus is not in the answer.
9. **Repeat every notice.** Truncation always arrives announced, naming the budget or cap that caused it. Pass that notice on rather than presenting a trimmed answer as a complete one.

## Confidence and fallback

| Grade | What the extractor saw | What you do |
|---|---|---|
| `high` | exact printed page, table reconstructed from its own declared columns, value present | quote it and cite the page |
| `medium` | the page is a section range, or the row printed no value | quote it, cite the range, and say the page is a range |
| `low` | the grid was rescued by a coarser split, or a unit the lexicon expected is missing | quote it, cite it, and tell the designer to open the printed page |
| `unknown` | not graded — verbatim section text, or a corpus built before grading | trust the text, not a grade that was never computed |

A `low` or `unknown` grade never means the row is wrong and never means you may withhold it. It means: quote the value, quote the unit, give the citation, and in the same breath tell the designer to open that printed page in the PDF to confirm it. The corpus is the fast path; the printed page is the authority.

## Access path 1 — the `dsa` CLI

```bash
dsa ask --part AFE7953 "max junction temperature" --budget 3000   # start here
dsa query --part AFE7953 --symbol TJ --json          # exact rows, rung + grade
dsa search --part AFE7953 "sysref setup" --limit 3   # cited sections
dsa plots --part AFE7953 --q "output power" --json   # figure catalog
```

Worked example — a question in a designer's words, a cited answer out:

```bash
$ dsa ask --part AFE7953 "what is the maximum junction temperature?"
```

```text
## AFE7953 — <revision>
### Answer
TJ  Operating junction temperature: <value> <unit> (max) — §<n>, p.<page>  [high]
### Supporting excerpt  (§<n> <title>, p.<page>)
<verbatim text from the corpus>
### Verify
Printed page <page> of <document>.  Confidence: high.
```

Report the value **with its unit** and the `§<n>, p.<page>` exactly as printed. Had the grade read `low`, the same answer goes out with "the extraction here was weak — confirm on printed p.<page>". `dsa ask` exits 2 when the corpus has no search index: that is a finding about the corpus (rebuild it), never an answer about the part.

## Access path 2 — MCP tools (`dsa serve --mcp`)

Tools: `list_parts`, `list_projects`, `get_index`, `search`, `find_spec`, `read_section`, `find_plots`, `get_figure`, `ask`, and the derived views `find_pin`, `find_register`, `get_card`, `compare_parts`. Resources: `dsa://part/<PART>/INDEX.md`, `dsa://project/<NAME>/PROJECT_INDEX.md`.

Worked example — the same question, then the figure behind it (call, then the shape that comes back):

```text
ask       {"part": "AFE7953", "question": "max junction temperature", "budget": 3000}
  -> {"pack": {...}, "citations": ["§<n>, p.<page>"], "tokens": 180, "truncated": false}
find_plots {"part": "AFE7953", "q": "output power"}
  -> {"hits": [{"caption": "...", "citation": "§<n>, p.<page>", "file": "figures/<name>.png", "confidence": "medium"}], "total": 7}
get_figure {"part": "<PART>", "file": "figures/<name>.png"}
  -> the PNG itself, as an image content block, beside the JSON that cites it
```

`find_spec` names the ladder rung in `matched_via` and returns `suggestions` rather than a guess; `read_section`, `get_index` and `get_figure` are part-scoped, and `get_figure` only returns a file the plot catalog claims. Every response carries `citations`, a `confidence` per hit, and `notice` + `truncated` when the `DSA_MCP_MAX_TOKENS` cap bit — `over_cap` means even the citation floor did not fit, so raise the cap instead of reading it as a short answer.
