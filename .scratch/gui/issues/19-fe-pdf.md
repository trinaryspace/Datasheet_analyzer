# 19 — PDF pane and highlight overlay

**Wave:** 1
**Blocked by:** 00
**Status:** ready-for-agent

**Owns:**
- `web/src/routes/pdf/**`
- `tests/web/pdf.test.ts`

**What to build:** The right pane, and the reason the application exists. It
renders a source PDF with PDF.js, jumps to a cited page, and draws the
highlight returned by `/api/locate`.

Bundle PDF.js and its worker locally. Nothing may be fetched from a CDN — the
app is local-only and must work with no internet — so the worker is a bundled
asset, not a URL.

Pages load through `GET /api/pdf/{content_hash}`, which supports range
requests. Let PDF.js use them: opening page 47 of a 200-page datasheet must not
download the first 46, and that is exactly the document where it matters.

**The highlight overlay is a separate layer above the canvas.** Rects come from
`/api/locate` in PDF points, so converting to canvas pixels means applying the
current zoom and the page's rotation — get both wrong and the box lands
plausibly but incorrectly, which is worse than no box at all. Re-derive on
zoom and resize rather than caching pixel positions.

Honour the honest miss. `found: false` means open the page with no highlight
and show the server's `reason` quietly — never fall back to highlighting
something approximate. A box around the wrong row turns a verification step
into a lie, which is the one failure this feature cannot have.

- [ ] A PDF renders from `/api/pdf/{content_hash}` with a locally bundled worker
- [ ] No network request leaves the origin (assert no CDN URL appears in the bundle)
- [ ] Range requests are used — opening a late page does not fetch the whole file
- [ ] A citation click opens the right document at the right page
- [ ] Rects from `/api/locate` are drawn in the correct position at 100% zoom
- [ ] Highlights stay aligned across zoom changes, window resizes and rotated pages
- [ ] `found: false` opens the page with no highlight and surfaces the reason
- [ ] A missing or 404 PDF renders an error state naming the document, not a blank pane
- [ ] Page navigation, zoom and fit-width controls work independently of citations
- [ ] The current page and zoom survive a citation click into the same document
- [ ] The pane is keyboard navigable and the highlight is announced to assistive tech
- [ ] The pane reads its target from shared route state and does not import the chat pane
- [ ] Tests use a small fixture PDF and a mocked locate response; no live backend
