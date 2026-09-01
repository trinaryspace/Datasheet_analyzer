"""Rendering errata links: the report, the section banner, the pack warning.

Three surfaces, one module, for the reason `protocol.py` gives: a warning that
exists in two of the three places it can still change a decision is the failure
this ticket is about. `ERRATA.md` is what a person reads, the **banner** is what
a section file carries at publish so nobody can read the affected page without
seeing it, and `pack_warning` is the inline line an answer pack carries when its
supporting record is targeted.

Two rules the renderers share:

- **The unlinked heading is a constant** (`UNLINKED_HEADING`), not a string a
  caller composes. An item the matcher could not place is published under it,
  every time, and the test that asserts it fails if the section ever stops being
  emitted.
- **Display truncation is marked and never authoritative.** A banner quotes the
  head of an item so a page carries the warning without carrying the whole
  errata document; the complete verbatim text is in `errata_links.json` and in
  `ERRATA.md`, and the ellipsis says which is which.
"""

from __future__ import annotations

from datasheet_analyzer.models import ErrataLink, ErrataLinkSet, ErrataTarget

#: The published artifacts of this ticket, beside the part's `INDEX.md`.
ERRATA_LINKS_FILENAME = "errata_links.json"
ERRATA_MARKDOWN_FILENAME = "ERRATA.md"

#: The heading an item with no target is published under. A constant because
#: the criterion is about the heading existing, so the renderer and the test
#: must read the same string.
UNLINKED_HEADING = "## Unlinked errata"
LINKED_HEADING = "## Linked errata"

#: What a bannered section file opens its warning with. The publisher inserts
#: it and `retrieve` never parses it back — the JSON is the machine surface —
#: but a stable marker lets a reader (and a test) find it.
BANNER_MARKER = "> **⚠ Errata:**"

#: Longest item head a banner or a pack warning quotes before eliding.
BANNER_QUOTE_CHARS = 200
PACK_QUOTE_CHARS = 120


def quote_head(text: str, limit: int) -> str:
    """The head of an item, on one line, elided at `limit` characters with `…`.

    Line breaks are collapsed rather than truncated at, because `pdf_text`
    publishes one paragraph per printed *line*: an item's own sentence is spread
    across several of them, and quoting only the first would show a reader the
    marker (`Advisory 3`) and nothing else. The ellipsis is what makes this quote
    non-authoritative — the verbatim text is in `errata_links.json` and in
    `ERRATA.md`, and a banner points at it rather than replacing it.
    """
    head = " ".join((text or "").split())
    if len(head) <= limit:
        return head
    return head[: limit - 1].rstrip() + "…"


def pack_warning(link: ErrataLink) -> str:
    """The inline warning an answer pack carries beside a targeted record.

    Deliberately one line and deliberately attached to the *answer row* rather
    than to the pack: it must be dropped only if the row it qualifies is
    dropped, exactly as a citation is. A reader who sees the value must see that
    an erratum names it.
    """
    item = link.item
    head = quote_head(item.text, PACK_QUOTE_CHARS)
    return f"⚠ errata {item.id} ({item.pages}): {head}"


def section_banner(links: list[ErrataLink], targets: dict[str, ErrataTarget]) -> str:
    """The block a targeted section file carries under its source comment.

    `targets` maps an item id to the target that selected this section, so the
    banner can say *what* matched — a banner that only says "an erratum affects
    this section" is unactionable, and a wrong one is undiagnosable.
    """
    if not links:
        return ""
    count = len(links)
    noun = "erratum" if count == 1 else "errata items"
    head = (
        f"{BANNER_MARKER} this section is named by {count} {noun} — "
        f"see `{ERRATA_MARKDOWN_FILENAME}` for the full text."
    )
    lines = [head]
    for link in links:
        target = targets.get(link.item.id)
        matched = f" [matched on {target.matched_on}]" if target else ""
        grade = f", {target.confidence.value}" if target else ""
        lines.append(
            f"> - {link.item.id} (errata {link.item.pages}{grade}): "
            f"{quote_head(link.item.text, BANNER_QUOTE_CHARS)}{matched}"
        )
    return "\n".join(lines)


def insert_banner(markdown: str, banner: str) -> str:
    """Put `banner` directly under a section file's `<!-- source: … -->` line.

    Under it rather than above it, so the file still opens with its title and
    its provenance comment — the layout `structure/corpus.py` documents as
    stable for agents to parse — and above the first paragraph, so the warning
    cannot be missed by anyone reading the section at all.
    """
    if not banner:
        return markdown
    lines = markdown.split("\n")
    for i, line in enumerate(lines):
        if line.startswith("<!-- source:"):
            head, tail = lines[: i + 1], lines[i + 1 :]
            return "\n".join(head + ["", banner] + tail)
    return "\n".join([banner, ""] + lines)


def render_errata(link_set: ErrataLinkSet) -> str:
    """`ERRATA.md` — every item this part carries, placed or not.

    Linked items first, then the unlinked ones under their own heading. Nothing
    is filtered: the count in the opening line is the sum of both lists, so a
    reader can check by arithmetic that no item went missing between the errata
    document and this file.
    """
    part = link_set.part_number or "(unknown part)"
    out: list[str] = [f"# {part} — errata"]
    docs = ", ".join(link_set.errata_docs) or "(none)"
    out.append("")
    out.append(
        f"{link_set.n_items} errata item(s) from {docs}: "
        f"{len(link_set.links)} linked to a published record, "
        f"{len(link_set.unlinked)} unlinked."
    )
    if link_set.empty_reason:
        out += ["", f"**No items:** {link_set.empty_reason}"]
    for note in link_set.notes:
        out += ["", f"_{note}_"]

    if link_set.links:
        out += ["", LINKED_HEADING]
        for link in link_set.links:
            out += _render_link(link, with_targets=True)
    # The heading is emitted whenever there is anything to put under it, and
    # never composed by a caller: an item the matcher could not place must be
    # findable in exactly one documented place.
    if link_set.unlinked:
        out += [
            "",
            UNLINKED_HEADING,
            "",
            (
                "_These items were published in full but could not be matched "
                "to a section, spec, pin or register by any deterministic rule. "
                "Read them by hand — nothing here has been dropped._"
            ),
        ]
        for link in link_set.unlinked:
            out += _render_link(link, with_targets=False)
    return "\n".join(out) + "\n"


def _render_link(link: ErrataLink, *, with_targets: bool) -> list[str]:
    item = link.item
    head = f"### {item.id} — {item.marker or '(no printed marker)'}"
    out = ["", head, "", f"Errata document: {item.doc}, {item.pages}", "", "```"]
    out += item.text.split("\n")
    out += ["```"]
    if with_targets:
        out += ["", "| kind | target | matched on | confidence | id |", "|---|---|---|---|---|"]
        for target in link.targets:
            page = f"p.{target.page}" if target.page is not None else "p.?"
            label = target.label or target.id or "(unlabelled)"
            out.append(
                f"| {target.kind.value} | {label} ({page}) | {target.matched_on} "
                f"| {target.confidence.value} | `{target.id}` |"
            )
    for note in link.notes:
        out += ["", f"_{note}_"]
    return out
