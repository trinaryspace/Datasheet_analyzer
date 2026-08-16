# 16 — App shell, theme, layout

**Wave:** 1
**Blocked by:** 00
**Status:** ready-for-agent

**Owns:**
- `web/src/shell/**`
- `web/src/styles/**`
- `tests/web/shell.test.ts`

**What to build:** The frame every screen renders inside: the two-pane split
that defines the application, navigation between screens, the design tokens,
and the shared primitives the other four frontend tickets import.

`web/src/App.tsx` and the API client already exist from ticket 00 — **do not
edit them**. Routes are discovered from `web/src/routes/*/route.tsx`, so this
ticket adds no routes; it provides what routes render into.

The split pane is the product. Chat left, PDF right, draggable divider,
collapsing to stacked below a narrow breakpoint. Its width must persist across
reloads, because an engineer settles on a ratio once and resents re-dragging
it. The right pane is empty until a citation is clicked, and its empty state
should say what will appear there rather than sitting blank.

Design tokens live in one stylesheet as CSS custom properties, with a complete
light palette on `:root`, a dark override under
`@media (prefers-color-scheme: dark)` guarded so an explicit light choice wins,
and a `[data-theme]` stamp so an in-app toggle wins in both directions. Every
component colour comes from a token — never a literal, and never a colour whose
only definition sits inside a media query.

Shared primitives this ticket owns and others import: `Button`, `Chip`,
`Panel`, `Spinner`, `EmptyState`, `ErrorState`, `ConfidenceBadge`,
`ApplicabilityControl`, and a `useSSE` hook wrapping the client's SSE helper
with reconnect and cleanup on unmount. `ConfidenceBadge` renders
`high | medium | low | unknown` — the values `retrieve/` already computes — and
its `low` state must be visually loud, because a low-confidence spec is exactly
when a user needs to open the page.

`ApplicabilityControl` lives here rather than in either screen that uses it.
Tickets 17 and 20 both edit applicability and run **concurrently**, so neither
can import from the other; a shared primitive is the only place it can live
without the two screens validating differently. It is a three-way control
matching the `Applicability` model exactly — specific parts, a family prefix,
or all parts — and it blocks an empty parts list or a blank family before the
value can reach the server.

- [ ] The split pane renders, drags, and restores its width after reload
- [ ] Below the breakpoint the panes stack and remain usable
- [ ] The right pane shows an informative empty state before any citation is clicked
- [ ] Light, dark and unset-system themes all render legible text on their own ground
- [ ] No component colour is defined only inside a media query or `[data-theme]` block
- [ ] The in-app theme toggle overrides the OS preference in both directions
- [ ] Every shared primitive is exported and covered by a render test
- [ ] `ConfidenceBadge` renders all four values and marks `low` distinctly
- [ ] `ApplicabilityControl` round-trips all three `Applicability` kinds and blocks an empty parts list and a blank family
- [ ] `useSSE` cleans up its connection on unmount and reconnects after a drop
- [ ] Keyboard focus is visible on every interactive element; the divider is keyboard-operable
- [ ] `prefers-reduced-motion` suppresses transitions
- [ ] `App.tsx` and `web/src/api/**` are not modified
- [ ] `npm run typecheck` and `npm test` pass
