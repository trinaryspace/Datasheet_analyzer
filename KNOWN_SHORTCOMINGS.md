# KNOWN_SHORTCOMINGS.md

What this repo does **not** do, or does only partly, recorded where a reader
will find it. An entry here is a measured limit with the reason it stands, not a
TODO list: the point of the file is that a gap in a derived artifact should be a
fact the project carries rather than something a user discovers.

Each entry says what was attempted, what it produces today, and what would have
to change. Numbers are measured, and the test that measures them is named.

---

## Register bit fields (phase 6, ticket 06)

Ticket 06 was commissioned with permission to **fail closed** — to ship nothing
and record why — because a driver written against a wrong bit range
misconfigures silicon silently. It ships: 28 of LMX1204's 35 registers publish a
validated bit-field set in each of its two documents (116 fields each), every
published field's printed quartet (bit range, name, access, reset) verified
against the text of the page it cites, and a hand-verified sample of five
registers matching field for field
(`tests/integration/test_phase6_registers.py::TestBitFieldAccuracy`).

These are the limits that came with it.

### 1. Seven of 35 registers publish no bit fields

Per document, and identically in both. They keep their summary record with
`fields: []` and a `fields_reason`, so a lookup finds the register and is told
what is missing.

| Registers | Why |
|---|---|
| R7, R8, R9, R16, R72, R86 | The layout floor's reconstruction gate rejected their field tables, so no grid reached the bit-field reader at all. Measured on `LMX1204_registermap.pdf`: 7 of 38 table candidates rejected — five as *rows do not span columns*, two as *columns not stable across rows* — and six of those seven are per-register field tables. |
| R90 | Its printed field table states `15:8` and then `15:0` (SNAU269A p.24, SNAS800B p.54). That is a typo in the document: the second range should be `7:0`. The two ranges overlap on bits 15:8, so the **whole** set is refused with a recorded reason rather than the corpus guessing which was meant. |

**What would change it.** The six rejections are an *extraction* finding, not a
bit-field one — the fix belongs in `extract/pdf_layout.py`, where those grids
fail the gate, and it would benefit every table of every part (which is what
ticket 05's three layout fixes did). R90 cannot be fixed here at all: the
document is wrong, and inventing `7:0` for it would be exactly the confident,
plausible, unverifiable value ADR 0005 forbids.

### 2. The bit-diagram route has no real-document gate

Two printed shapes carry bit fields. The **bit column** (`Bit | Field | Type |
Reset | Description`, the range printed as text) is what both reference
documents use, and it is what the accuracy gate measures. The **bit diagram** (a
bit-position header row `7 6 5 4 3 2 1 0` with field names spanning columns
under it) is implemented — the ticket requires the range to be derived
geometrically from the header row's cell boundaries — but **no document in this
repo prints one**, so it is gated on synthetic PDFs read by the real layout
floor plus hand-built grids
(`tests/unit/test_bitfields.py::TestTheDiagramRouteIsGeometric`), never on a
vendor's own page.

Two properties keep that honest until a real one arrives: the route only fires
for a table whose caption or preamble names the register it describes, and its
output still has to tile that register's width with no overlap and no overflow
or it is refused whole. It also publishes **no per-field access or reset**,
because a diagram prints neither in the header run it was read from.

One reading is an assumption rather than a measurement: an empty bit column
continues the field to its left, which is what a cell spanning four columns
looks like once the layout floor has reduced it to text in the band its words
start in. Columns before the *first* named cell continue nothing and are
reported as unaccounted rather than folded backwards.

**What would change it.** A register map that prints bit diagrams, committed to
`tests/fixtures/pdf/`, with a hand-verified sample held to the same 100% bar.

### 3. A field description can carry the line printed under its table

The layout floor's table region sometimes extends past the last field row and
picks up the navigation line TI prints beneath it (`R12 is shown in Table 1-13.
Return to the Summary Table.`). Where that line prints no field name it is read
as the continuation of the last field's description, so a handful of
descriptions end with text that is not part of the field's description.

Bit ranges, names, access and resets are unaffected — those come from a row's
own cells, and a line with no readable bit range never becomes a field (the
count of such lines is reported in the register set's warnings). Filtering the
line by its wording would put a vendor's phrasing in the code, which this repo
does not do; the fix is a tighter region end in `extract/pdf_layout.py`.

### 4. A register with no printed hex reset word publishes no fields

The register width is read from the reset word the document prints
(`[Reset = 0x0000]` → four hex digits → 16 bits), because it is the only width
statement a TI programmer's guide makes and it is *printed*. A document that
states a reset in decimal, or states none, therefore publishes no fields for
that register even when its field table read cleanly — a field list that cannot
be checked against a register width is unverifiable, and this ticket's whole
stance is that unverifiable bit ranges do not ship. A document printing
`[Reset = 0x0]` for a 16-bit register reads as 4 bits wide, its top fields
overflow, and the set is refused with a reason.

**What would change it.** A width stated somewhere else printed — a summary
column, or a bit-position header row (already used when a diagram provides one).
Deriving it from the fields themselves is deliberately not done: a width taken
from the ranges it is supposed to validate makes the validation vacuous.
