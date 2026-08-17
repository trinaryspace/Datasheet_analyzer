# 14 — PDF byte serving

**Wave:** 1
**Blocked by:** 00
**Status:** ready-for-agent

**Owns:**
- `src/datasheet_analyzer/app/routers/pdf.py`
- `tests/unit/test_pdf_serve.py`

**What to build:** `GET /api/pdf/{content_hash}` streams a source PDF to the
viewer pane. Small, but it is the one endpoint that hands raw filesystem bytes
to a browser, so its safety properties matter more than its size.

Resolve the path through the library — `content_hash` is a `SourceDocument`'s
identity, so the store is the lookup — never from a client-supplied path. A
hash that is not in the library is a 404, which makes path traversal
structurally impossible rather than filtered: there is no user-controlled path
component to sanitize.

`SourceDocument.path` is whatever string the CLI was given, often relative
(`"ad9081.pdf"`), so it is only meaningful against the working directory that
registered it. Resolve it, verify the resolved file exists and is a regular
file, and return a clear 404 naming the recorded path when it has moved — a
user who reorganized their folders needs to know which file went missing, not
a stack trace.

Support HTTP range requests. PDF.js fetches byte ranges to render page 47 of a
200-page document without downloading the first 46, and a 200 OK with the whole
body defeats that on exactly the documents where it matters most.

- [ ] A known `content_hash` returns the PDF with `Content-Type: application/pdf`
- [ ] An unknown hash returns 404
- [ ] A hash whose recorded path no longer exists returns 404 naming the recorded path
- [ ] A recorded path that resolves outside the expected roots is refused
- [ ] No request parameter can influence the path read from disk
- [ ] A `Range` request returns 206 with `Content-Range` and exactly the requested bytes
- [ ] An unsatisfiable range returns 416
- [ ] A request with no `Range` returns 200 and the whole file
- [ ] `Content-Length` is correct in all three cases
- [ ] Large files stream rather than loading fully into memory
- [ ] `Content-Disposition` is `inline` so the browser renders rather than downloads
- [ ] Tests use a temp library and a small synthetic PDF; no network
