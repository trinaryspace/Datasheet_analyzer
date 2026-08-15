# 08 — Plot axis catalog

**What to build:** Additive `PlotRecord` fields — `x_label, x_unit, x_min,
x_max, y_label, y_unit, y_min, y_max, axis_confidence` — extracted
geometrically and deterministically.

Tick labels cluster along the figure region's left and bottom edges; the axis
title is the text run parallel to that edge (rotated 90° for y, which PyMuPDF
reports via span direction); numeric tick sequences give min/max. **Anything
uncertain stays null** with `axis_confidence: low`.

This lets `find_plots --near-x 3.5GHz --y-label Gain` narrow 514 figures to
one before a single vision token is spent, and `get_figure` (Phase 5, ticket
07) hands back that one PNG for the agent to present to the designer.

Image *analysis* of the PNG is a future consumer of this catalog and is not
built here — but `plots.json` must be shaped so it can be added without a
migration.

**Blocked by:** — (independent of everything else in this phase; the right
work to pick up while waiting on the reference register-map PDF)

**Status:** ready-for-agent

- [ ] Axis metadata extracted for **≥60%** of AFE7950's 514 figures with
      `axis_confidence: high`; the remainder honestly null. The threshold is a
      floor to beat and record, not a target to fit to.
- [ ] Rotated y-axis titles are read correctly — asserted on a real figure and
      a synthetic one
- [ ] Log-scale axes are either handled or explicitly marked low-confidence,
      never linearly misreported
- [ ] `find_plots` gains axis filters (`--x-label`, `--y-label`, `--near-x`)
      that narrow correctly on a hand-checked example
- [ ] A figure whose axes cannot be read still appears in `plots.json` with
      caption and conditions intact — no plot is lost to a failed axis parse
- [ ] Coverage per part is recorded for the phase report
- [ ] Schema leaves room for a later digitization pass without a migration

---

Source: `.scratch/design-time-content/SPEC.md`
