# 0003 — Unnumbered sections stay honest: slug keys, never fabricated ordinals

TI prints section numbers; ADI, Qorvo, and Hittite-era parts don't. The
pipeline's identity machinery (file stems, plot IDs, spec/INDEX keys,
`pagemap` matching) is number-centric, so multi-vendor support forced a
choice: synthesize ordinal numbers (1, 2, 3…) from outline order, or keep
`number == ""` everywhere the source omits it and key on slugified titles.

We chose **honest unnumbered + slug keys**: no identifier appears in the
corpus that isn't in the source document. Files are `general-description.md`
rather than `4-5-general-description.md`; sections carry pages from outline
ranges; INDEX/plots/specs key on slug where numbers are absent; the PDF
structure ladder for page assignment works by outline position and title,
not numbers. (Synthesizing ordinals would also collide the day a future
part prints real numbers, and would silently rename published corpus files
for no benefit.)

Hard to reverse once corpora are published (file names are part identity),
surprising without context (the TI parts are all numbered, so empty-number
sections read as a bug), and a genuine trade-off against cosmetic parity
with numbered files.
