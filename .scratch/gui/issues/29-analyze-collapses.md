# 29 — Analyze collapses when there is nothing to do

**Owns:** `web/src/routes/analyze/route.tsx`, `web/src/routes/analyze/PickStep.tsx`,
`web/src/routes/analyze/analyze.css`, `tests/web/analyze.test.ts`

**Problem.** Pick → Review → Build is right the first time and wrong every
time after. A rescan of a current directory should say so and stop.

**Build.** Using ticket 26's states, after a scan:

- every proposal `current` → a done state naming the count, no Review step,
  and a **Rebuild anyway** escape that forces the build.
- otherwise → Review as today, but sorted so what will rebuild is first, with
  a summary line ("38 current, 2 will rebuild — 1 stale, 1 changed").

The escape matters: the gate can be wrong about a corpus a user knows is bad,
and a UI with no override makes them delete directories by hand.

- [ ] A scan where everything is current shows the done state and no review table
- [ ] Rebuild anyway from that state starts a run for every proposal
- [ ] A mixed scan lists rebuildable rows first and summarises both counts
- [ ] The prefilled directory comes from the active project when there is one
