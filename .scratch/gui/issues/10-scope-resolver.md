# 10 — Scope resolver

**Wave:** 1
**Blocked by:** 00
**Status:** ready-for-agent

**Owns:**
- `src/datasheet_analyzer/app/scope_resolver.py`
- `tests/unit/test_scope_resolver.py`

**What to build:** Turn a plain-language question into exactly one Part or
Project scope, or into a question back to the user. This is the mechanism ADR
0006 rests on: retrieval refuses an "all parts" scope on purpose, and the GUI
honours that not by making the user pick a scope but by resolving one and
showing it.

`resolve(question, *, parts, projects) -> ScopeResolution` is **deterministic —
no model call**. Part numbers are distinctive strings and the candidate list is
already enumerable, so this is matching, not inference. Order:

1. Exact case-insensitive match of a known part or project name as a whole
   token in the question. One match → confident.
2. Prefix or family match (`AFE795` against `AFE7950`, `AFE79xx` against both)
   → candidates, not confident.
3. Several matches at the same strength → candidates, not confident.
4. No match → `scope=None`, `candidates=[]`, and a `question` field asking
   which part is meant.

Never widen. There is no "search everything" fallback at any tier, and a
single built part is **not** a safe default — answering from the only part that
happens to exist is exactly the implicit scope the invariant forbids.

Token matching must not fire on substrings inside larger words: `AD908` must
not match a question mentioning `AD9081`, and a part named `LM741` must not
match `LM7410`. Use word-boundary matching over a normalized question.

- [ ] A question naming one known part resolves confidently to that part
- [ ] A question naming a known project resolves confidently to that project
- [ ] A question naming both a part and a project returns candidates and is not confident
- [ ] A prefix like `AFE795` against `AFE7950` and `AFE7952` returns both as candidates
- [ ] A question naming no known part returns `scope=None` with a question for the user
- [ ] With exactly one built part and a question that does not name it, the result is still not confident — no defaulting
- [ ] Matching is case-insensitive
- [ ] `AD908` does not match the part `AD9081`; `LM741` does not match `LM7410`
- [ ] A part number appearing inside a longer identifier in the question does not match
- [ ] Punctuation adjacent to a part number (`AD9081,` / `(AD9081)` / `AD9081's`) still matches
- [ ] `resolve` makes no model call and no filesystem access — parts and projects are passed in
- [ ] Every returned `ScopeResolution` validates against the contract model
