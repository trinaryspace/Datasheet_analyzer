# 0002 — Vendor-neutral layout core replaces the "no layout analysis" stance

The project documented a hard stance: "layout analysis of dense parametric
tables from raw PDF text is the failure mode this project avoids" — TCP/IP
was born from TI's unparseable PDF layouts, and `pdf_text` exists as honest
paragraph-only degradation. Supporting vendors without a parseable HTML
viewer (older TI, ADI, Qorvo, and any vendor N+1) requires tables from PDF
geometry, so the stance is superseded with guardrails rather than a brain
transplant.

The layout core (`pdf_layout` backend) is deterministic and self-verifying:
tables are caption-anchored hypotheses built from ruling bands + all-word
x-clustering, scored by **reconstruction fidelity** — the accepted grid must
re-produce the page's own word stream, or it is rejected (and retried with
coarser splits; recorded with reasons in the manifest). That gate is the
functional replacement for "we don't parse layout": we now parse layout,
but nothing unverified survives. No ML (torch is forbidden; nondeterminism
would break the content-hash cache and silent cell corruption is the exact
failure class the project exists to avoid).

Hard to reverse (rewrites the fidelity story and extraction invariants),
surprising without context (docstrings in `pdf_structure.py` still teach
the old doctrine), and a real trade-off (we chose universal offline
fidelity + verification over per-vendor HTML fidelity). AGENTS.md and the
`pdf_structure.py` doctrine text must be rewritten when it lands.
