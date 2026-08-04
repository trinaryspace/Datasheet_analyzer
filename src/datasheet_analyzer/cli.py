"""CLI entrypoint: `dsa <command>`.

Commands:
  build <pdf> --part NAME   full pipeline: acquire -> extract -> corpus
  batch <dir>               build every PDF in a directory as its own part
  verify --part NAME        golden Q&A citation verification (deterministic)
  query --part NAME         deterministic spec lookup
  plots --part NAME         deterministic plot lookup
  status                    configuration + detected parts
  version                   print version
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from datasheet_analyzer.config import PIPELINE_VERSION, get_settings

log = logging.getLogger("dsa")


def _known_vendor_or_error(vendor: str) -> bool:
    from datasheet_analyzer.vendor import is_known_vendor, unknown_vendor_message

    if not vendor or is_known_vendor(vendor):
        return True
    print(unknown_vendor_message(vendor), file=sys.stderr)
    return False


def _cmd_add_doc(args: argparse.Namespace) -> int:
    from datasheet_analyzer.acquire import append_to_inventory, register_source
    from datasheet_analyzer.models import DocType

    if not _known_vendor_or_error(args.vendor or ""):
        return 2
    settings = get_settings()
    part_dir = settings.parts_dir / args.part
    dtype = DocType(args.type)
    source = register_source(
        Path(args.pdf),
        part_number=args.part,
        doc_type=dtype,
        nda=args.nda,
        vendor=args.vendor or None,
    )
    append_to_inventory([source], part_dir)
    print(f"registered {source.doc_type.value}: {Path(source.path).name}")
    print(
        f"  hash {source.content_hash[:8]} — {source.page_count} pages — "
        f"vendor {source.vendor}"
    )
    return 0


def _cmd_build(args: argparse.Namespace) -> int:
    from datasheet_analyzer.extract import BackendUnavailableError
    from datasheet_analyzer.pipeline import build_part

    if not _known_vendor_or_error(args.vendor or ""):
        return 2
    settings = get_settings()
    try:
        result = build_part(
            Path(args.pdf),
            part_number=args.part,
            settings=settings,
            vendor=args.vendor,
            use_cache=not args.no_cache,
            use_llm=not args.no_llm,
        )
    except BackendUnavailableError as exc:
        print(f"build error: {exc}", file=sys.stderr)
        return 2
    stats = result.manifest.stats
    print(f"corpus: {result.part_dir}")
    print(
        f"  {stats.n_sections} sections, {stats.n_tables} tables, "
        f"{stats.n_figures} figures, {stats.n_footnotes} footnotes, "
        f"{stats.n_specs} spec records, {stats.n_plot_files} plot files"
    )
    print(
        f"  corpus {stats.total_tokens} tokens; INDEX.md {stats.index_tokens} tokens "
        f"(budget {settings.index_token_budget})"
    )
    print(
        f"  page coverage: {stats.sections_with_pages}/{stats.n_sections} sections; "
        f"extraction {'cached' if result.cached_extraction else 'fresh'}; "
        f"descriptions {'LLM' if result.used_llm else 'deterministic'}"
    )
    return 0


def _cmd_batch(args: argparse.Namespace) -> int:
    from datasheet_analyzer.batch import BatchError, run_batch

    settings = get_settings()
    try:
        report = run_batch(
            Path(args.dir),
            settings=settings,
            use_cache=not args.no_cache,
            use_llm=not args.no_llm,
        )
    except BatchError as exc:
        print(f"batch error: {exc}", file=sys.stderr)
        return 2
    return 0 if report.ok else 1


def _spec_fields(rec) -> str:
    return (
        f"{rec.symbol} {rec.name} {rec.conditions} "
        f"{rec.min} {rec.typ} {rec.max} {rec.value} "
        f"{rec.unit.verbatim} {rec.unit.canonical}"
    )


def _cmd_verify(args: argparse.Namespace) -> int:
    from datasheet_analyzer.evalh.citations import contains, summarize, verify_questions
    from datasheet_analyzer.evalh.golden import (
        estimate_lookup_tokens,
        load_golden,
        render_verification_report,
    )
    from datasheet_analyzer.extract.pdf_structure import page_texts
    from datasheet_analyzer.query import SpecQuery, find_plots

    settings = get_settings()
    part_dir = settings.parts_dir / args.part
    if not (part_dir / "manifest.json").exists():
        print(f"no corpus at {part_dir} — run `dsa build` first", file=sys.stderr)
        return 2

    questions = load_golden(Path(args.golden))
    pages = page_texts(Path(args.pdf)) if args.pdf else []
    if not pages:
        print("warning: --pdf not given; page-truth check disabled", file=sys.stderr)
    results = verify_questions(questions, part_dir, pages)
    print(render_verification_report(results))
    if pages:
        tokens = estimate_lookup_tokens(part_dir, results)
        print("## Token cost per question (measured on the built corpus)")
        print()
        print(f"- INDEX.md (always loaded): {tokens['index_tokens']} tokens")
        print(f"- avg question total (index + section): {tokens['avg_per_question']:.0f} tokens")
        print(f"- worst question total: {tokens['max_per_question']} tokens")
        print(f"- naive full-corpus dump: {tokens['full_dump_tokens']} tokens")

    summary = summarize(results)
    failed = summary["failed"] != 0

    if args.specs:
        spec_questions = [q for q in questions if q.spec_query]
        spec_results: list[tuple] = []
        for q in spec_questions:
            recs = SpecQuery(part_dir).find(**q.spec_query)
            # Multi-row answers (e.g. DSA range + step, VCO coverage) are
            # verified across the query result set: every expected substring
            # must appear on at least one record whose page is in the cited
            # page list.
            paged_recs = [r for r in recs if r.page is not None and r.page in q.pages]
            if paged_recs:
                ok = all(
                    any(contains(_spec_fields(r), sub) for r in paged_recs)
                    for sub in q.expected_substrings
                )
            else:
                ok = False
            spec_results.append((q, ok, recs))

        print()
        print("## Spec query verification (deterministic)")
        print()
        print(f"**{sum(1 for _, ok, _ in spec_results if ok)}/{len(spec_results)} passed**")
        print()
        print("| # | Question | Query | Result |")
        print("|---|---|---|---|")
        for i, (q, ok, recs) in enumerate(spec_results, 1):
            query_str = ", ".join(f"{k}={v!r}" for k, v in (q.spec_query or {}).items())
            status = "✅" if ok else "❌"
            detail = f"{len(recs)} record(s)" if ok else f"{len(recs)} record(s), page/value mismatch"
            print(f"| {i} | {q.question} | {query_str} | {status} {detail} |")
        if not all(ok for _, ok, _ in spec_results):
            failed = True

    # Plot query verification (Phase 3): every plot_query must match at least
    # one PlotRecord whose image file exists and is >1 KB, on the right page.
    plot_questions = [q for q in questions if q.plot_query]
    if plot_questions:
        plot_results: list[tuple] = []
        for q in plot_questions:
            query = q.plot_query or {}
            recs = find_plots(
                part_dir,
                caption=query.get("caption_contains", ""),
                conditions=query.get("conditions_contain", ""),
                section=query.get("section", ""),
            )
            paged = [r for r in recs if r.page_start is not None and r.page_start in q.pages]
            file_hits = []
            for r in paged:
                if not r.file:
                    continue
                fpath = part_dir / r.file
                try:
                    if fpath.exists() and fpath.stat().st_size > 1024:
                        file_hits.append(r)
                except OSError:
                    pass
            ok = bool(file_hits)
            if ok and q.expected_substrings:
                text = " ".join(r.caption + " " + r.conditions for r in file_hits)
                ok = all(contains(text, sub) for sub in q.expected_substrings)
            plot_results.append((q, ok, recs, file_hits))

        print()
        print("## Plot query verification (deterministic)")
        print()
        print(
            f"**{sum(1 for _, ok, _, _ in plot_results if ok)}/{len(plot_results)} passed**"
        )
        print()
        print("| # | Question | Query | Result |")
        print("|---|---|---|---|")
        for i, (q, ok, recs, file_hits) in enumerate(plot_results, 1):
            query_str = ", ".join(f"{k}={v!r}" for k, v in (q.plot_query or {}).items())
            status = "✅" if ok else "❌"
            detail = f"{len(file_hits)} plot file(s)" if ok else f"{len(recs)} match(es), {len(file_hits)} valid file(s)"
            print(f"| {i} | {q.question} | {query_str} | {status} {detail} |")
        if not all(ok for _, ok, _, _ in plot_results):
            failed = True

    return 0 if not failed else 1


def _cmd_query(args: argparse.Namespace) -> int:
    from datasheet_analyzer.query import SpecQuery, format_answer

    settings = get_settings()
    part_dir = settings.parts_dir / args.part
    if not (part_dir / "manifest.json").exists():
        print(f"no corpus at {part_dir} — run `dsa build` first", file=sys.stderr)
        return 2

    recs = SpecQuery(part_dir).find(
        symbol=args.symbol or "",
        name=args.name or "",
        section=args.section or "",
    )
    print(format_answer(recs))
    return 0 if recs else 1


def _cmd_plots(args: argparse.Namespace) -> int:
    from datasheet_analyzer.query import find_plots, format_plot_answer

    settings = get_settings()
    part_dir = settings.parts_dir / args.part
    if not (part_dir / "manifest.json").exists():
        print(f"no corpus at {part_dir} — run `dsa build` first", file=sys.stderr)
        return 2

    tags = [t.strip() for t in args.tag.split(",") if t.strip()] if args.tag else []
    recs = find_plots(
        part_dir,
        q=args.q or "",
        section=args.section or "",
        tags=tags,
    )
    print(format_plot_answer(recs))
    return 0 if recs else 1


def _part_vendor_info(part: Path) -> tuple[str, str, list[str], list[str]]:
    """(vendor, evidence, backends, doc_stats_lines) for a part.

    Vendor + evidence always come from sources.json — the pinned acquire
    record (a built part's manifest only mirrors it, and legacy manifests
    predate the field). Backends and per-document extraction stats come
    from the manifest's extraction stats when the part is built. ("", "",
    [], []) when nothing is registered.
    """
    from datasheet_analyzer.acquire import load_inventory
    from datasheet_analyzer.models import CorpusManifest, DocType

    sources = load_inventory(part) if (part / "sources.json").exists() else []
    vendor, evidence = "", ""
    if sources:
        ds = next((s for s in sources if s.doc_type == DocType.DATASHEET), sources[0])
        vendor, evidence = ds.vendor, ds.vendor_evidence
    backends: list[str] = []
    doc_lines: list[str] = []
    manifest_path = part / "manifest.json"
    if manifest_path.exists():
        try:
            m = CorpusManifest.model_validate_json(
                manifest_path.read_text(encoding="utf-8")
            )
        except (ValueError, OSError, TypeError):
            m = None
        if m is not None:
            backends = list(
                dict.fromkeys(st.backend for st in m.extraction_stats.values() if st.backend)
            )
            for doc in m.documents:
                st = m.extraction_stats.get(doc.content_hash)
                if st is None:
                    continue
                line = (f"    {doc.doc_type.value}-{doc.content_hash[:8]}: backend "
                        f"{st.backend} · tables: {st.tables_detected} detected / "
                        f"{st.tables_accepted} accepted / {st.tables_rejected} rejected")
                if st.mean_fidelity > 0.0:
                    line += f" · fidelity {st.mean_fidelity:.2f}"
                if st.rejection_reasons:
                    shown = "; ".join(st.rejection_reasons[:3])
                    if len(st.rejection_reasons) > 3:
                        shown += "; …"
                    line += f" · rejection reasons: {shown}"
                doc_lines.append(line)
    return vendor, evidence, backends, doc_lines


def _cmd_status(_args: argparse.Namespace) -> int:
    settings = get_settings()
    print(f"datasheet-analyzer {PIPELINE_VERSION}")
    print(f"parts_dir: {settings.parts_dir}")
    print(f"cache_dir: {settings.cache_dir}")
    print(f"llm: {'available (' + settings.model + ')' if settings.llm_available else 'NO KEY (deterministic mode)'}")
    if settings.parts_dir.exists():
        for part in sorted(p for p in settings.parts_dir.iterdir() if p.is_dir()):
            has_index = (part / "INDEX.md").exists()
            label = f"  part: {part.name} {'[built]' if has_index else '[partial]'}"
            vendor, evidence, backends, doc_lines = _part_vendor_info(part)
            if vendor:
                label += f" vendor: {vendor}"
                if evidence:
                    label += f" ({evidence})"
                if any(backends):
                    label += f" extraction: {', '.join(backends)}"
            else:
                label += " vendor: (none)"
            print(label)
            for line in doc_lines:
                print(line)
    return 0


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    # Windows consoles default to cp1252 — reports contain ✅/❌/± etc.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    parser = argparse.ArgumentParser(prog="dsa", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p_build = sub.add_parser("build", help="build a part corpus from a datasheet PDF")
    p_build.add_argument("pdf")
    p_build.add_argument("--part", required=True, help="part number, e.g. AFE7950")
    p_build.add_argument(
        "--vendor",
        default="",
        help="explicit vendor override, e.g. adi (default: detected + pinned)",
    )
    p_build.add_argument("--no-cache", action="store_true")
    p_build.add_argument("--no-llm", action="store_true")
    p_build.set_defaults(func=_cmd_build)

    p_batch = sub.add_parser(
        "batch",
        help="build every PDF directly inside a directory as its own part corpus",
    )
    p_batch.add_argument("dir", help="directory of datasheet PDFs (flat scan)")
    p_batch.add_argument("--no-cache", action="store_true")
    p_batch.add_argument("--no-llm", action="store_true")
    p_batch.set_defaults(func=_cmd_batch)

    p_add = sub.add_parser("add-doc", help="register a companion document (register map, errata, app note)")
    p_add.add_argument("pdf", help="PDF file to register")
    p_add.add_argument("--part", required=True, help="part number")
    p_add.add_argument(
        "--type",
        required=True,
        choices=["register_map", "errata", "app_note", "datasheet"],
        help="document type",
    )
    p_add.add_argument("--nda", action="store_true", help="mark as NDA")
    p_add.add_argument(
        "--vendor",
        default="",
        help="explicit vendor override (default: detected + pinned)",
    )
    p_add.set_defaults(func=_cmd_add_doc)

    p_verify = sub.add_parser("verify", help="verify a built corpus against the golden Q&A set")
    p_verify.add_argument("--part", required=True)
    p_verify.add_argument("--pdf", default="", help="source PDF for page-truth checks")
    p_verify.add_argument("--specs", action="store_true", help="also verify spec_query entries")
    p_verify.add_argument(
        "--golden",
        default=str(Path(__file__).parent.parent.parent / "tests" / "fixtures" / "golden_qa.yaml"),
    )
    p_verify.set_defaults(func=_cmd_verify)

    p_query = sub.add_parser("query", help="deterministic spec lookup")
    p_query.add_argument("--part", required=True)
    p_query.add_argument("--symbol", default="")
    p_query.add_argument("--name", default="")
    p_query.add_argument("--section", default="")
    p_query.set_defaults(func=_cmd_query)

    p_plots = sub.add_parser("plots", help="deterministic plot lookup")
    p_plots.add_argument("--part", required=True)
    p_plots.add_argument("--q", default="", help="caption/conditions substring")
    p_plots.add_argument("--section", default="", help="exact section number")
    p_plots.add_argument(
        "--tag", default="", help="comma-separated tags (all must match)"
    )
    p_plots.set_defaults(func=_cmd_plots)

    p_status = sub.add_parser("status", help="show configuration and built parts")
    p_status.set_defaults(func=_cmd_status)

    p_version = sub.add_parser("version", help="print version")
    p_version.set_defaults(func=lambda _a: print(PIPELINE_VERSION) or 0)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
