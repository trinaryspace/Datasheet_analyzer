# 02 — Axis filters are unreachable from the CLI

**What to build:** The four `plots` flags Phase 6 ticket 08 promised and never
wired.

**Measured:** `query.find_plots()` and `Retriever.plots()` both already accept
`x_label`, `y_label`, `near_x`, `near_y` — implemented, documented, tested, and
reachable from MCP. `dsa plots` exposes `--q`, `--section`, `--tag`, `--json`
and nothing else, so the plan's own worked example (`--near-x 3.5GHz --y-label
Gain`) works from an agent and not from a shell. `cli.py` was frozen by Phase 6
ticket 01 and ticket 08 could not touch it; the wiring was simply never done
afterwards.

`_cmd_plots` also drops `caption` and `conditions`, which `find_plots` accepts
independently of `q`. Wire the four axis flags; leave `caption`/`conditions`
alone and record them in the report as a deliberate omission if you agree they
are redundant with `--q`, or add them if you do not. Say which, either way.

**Fix:** four `add_argument` calls and four pass-throughs. No new logic. This
ticket adds no behaviour that is not already under test one layer down; what it
adds is *reachability*.

**Blocked by:** 01 — both change `cli.py`. Start when 01 has landed.

**Status:** done

- [x] `--x-label`, `--y-label`, `--near-x`, `--near-y` on the `plots` parser,
      with help text that says these match what the figure *prints on its
      axes*, not what its caption says
- [x] Passed straight through to `scope.plots(...)`; no filtering logic in
      `cli.py`
- [x] The `--json` payload's `query` block reports them, like `q`/`section`/
      `tags` — a machine reader must be able to see what narrowed the result
- [x] The plan's worked example runs against a real built part and returns the
      expected figure; the figure and the count go in the report
- [x] A figure whose axes could not be read stays ruled *out* by an axis
      filter, matching `find_plots`'s documented direction — assert it
- [x] Help text for `dsa plots --help` reviewed end to end

**Owns:** `src/datasheet_analyzer/cli.py` (the `plots` parser and `_cmd_plots`
only), `tests/unit/test_plots_cli.py`

---

Source: `.scratch/extraction-fidelity/SPEC.md`
