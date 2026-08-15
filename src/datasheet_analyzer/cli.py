"""CLI entrypoint: `dsa <command>`.

Commands:
  build <pdf> --part NAME   full pipeline: acquire -> extract -> corpus
  batch <dir>               build every PDF in a directory as its own part (unchanged parts skipped; --force rebuilds; --workers N parallel, default 4)
  verify --part NAME        golden Q&A citation verification (deterministic)
  query --part NAME         deterministic spec lookup (alias ladder; --json)
  search --part NAME "..."  BM25 full-text search, cited by construction (--json)
  plots --part NAME         deterministic plot lookup (--json)
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
            force=args.force,
            workers=args.workers if args.workers is not None else settings.batch_workers,
        )
    except BatchError as exc:
        print(f"batch error: {exc}", file=sys.stderr)
        return 2
    return 0 if report.ok else 1


def _default_golden_path(part: str) -> Path:
    """Per-part golden discovery (SPEC story 26): each part verifies
    against tests/fixtures/golden_qa_<PART>.yaml, so a missing benchmark
    is a hard failure, never a silent zero-question pass."""
    return (
        Path(__file__).resolve().parent.parent.parent
        / "tests"
        / "fixtures"
        / f"golden_qa_{part}.yaml"
    )


def _cmd_verify(args: argparse.Namespace) -> int:
    from datasheet_analyzer.evalh.citations import (
        summarize,
        verify_plot_queries,
        verify_questions,
        verify_spec_queries,
    )
    from datasheet_analyzer.evalh.golden import (
        estimate_lookup_tokens,
        load_golden,
        render_plot_query_report,
        render_spec_query_report,
        render_token_economics,
        render_verification_report,
    )
    from datasheet_analyzer.extract.pdf_structure import page_texts

    settings = get_settings()
    part_dir = settings.parts_dir / args.part
    if not (part_dir / "manifest.json").exists():
        print(f"no corpus at {part_dir} — run `dsa build` first", file=sys.stderr)
        return 2

    golden = Path(args.golden) if args.golden else _default_golden_path(args.part)
    if not golden.exists():
        print(
            f"verify error: no golden benchmark for part {args.part}: {golden} missing. "
            "Write tests/fixtures/golden_qa_<PART>.yaml (see golden_qa_AD9081.yaml "
            "for the format) or pass --golden <file>.",
            file=sys.stderr,
        )
        return 2
    questions = load_golden(golden)
    if not questions:
        print(
            f"verify error: golden benchmark {golden} has 0 questions — nothing "
            "to verify; every part must be provably verified or provably not.",
            file=sys.stderr,
        )
        return 2
    pages = page_texts(Path(args.pdf)) if args.pdf else []
    if not pages:
        print("warning: --pdf not given; page-truth check disabled", file=sys.stderr)
    results = verify_questions(questions, part_dir, pages)
    print(render_verification_report(results))
    if pages:
        print(render_token_economics(estimate_lookup_tokens(part_dir, results)))

    summary = summarize(results)
    failed = summary["failed"] != 0

    if args.specs:
        spec_results = verify_spec_queries(questions, part_dir)
        print()
        print(render_spec_query_report(spec_results))
        if any(not r.ok for r in spec_results):
            failed = True

    # Plot query verification (Phase 3) runs whenever the golden set carries
    # plot questions; the pass rule lives in evalh, not here.
    plot_results = verify_plot_queries(questions, part_dir)
    if plot_results:
        print()
        print(render_plot_query_report(plot_results))
        if any(not r.ok for r in plot_results):
            failed = True

    return 0 if not failed else 1


def _cmd_query(args: argparse.Namespace) -> int:
    import json

    from datasheet_analyzer.query import format_no_match, format_spec_hits
    from datasheet_analyzer.retrieve import Retriever

    settings = get_settings()
    part_dir = settings.parts_dir / args.part
    if not (part_dir / "manifest.json").exists():
        print(f"no corpus at {part_dir} — run `dsa build` first", file=sys.stderr)
        return 2

    retriever = Retriever.for_part(part_dir)
    hits = retriever.specs(
        symbol=args.symbol or "",
        name=args.name or "",
        section=args.section or "",
    )
    term = (args.symbol or args.name or "").strip()
    if args.json:
        # The retrieval core owns the shape (SpecHit.as_dict); the CLI only
        # decides that this invocation wants JSON.
        payload = {
            "part": args.part,
            "query": {"symbol": args.symbol, "name": args.name, "section": args.section},
            "hits": [h.as_dict() for h in hits],
            "suggestions": [] if hits else retriever.suggest_specs(term),
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0 if hits else 1

    if not hits:
        print(format_no_match(term, retriever.suggest_specs(term)))
        return 1
    print(format_spec_hits(hits))
    return 0


def _cmd_search(args: argparse.Namespace) -> int:
    import json

    from datasheet_analyzer.query import format_search_hits
    from datasheet_analyzer.retrieve import Retriever

    settings = get_settings()
    part_dir = settings.parts_dir / args.part
    if not (part_dir / "manifest.json").exists():
        print(f"no corpus at {part_dir} — run `dsa build` first", file=sys.stderr)
        return 2

    retriever = Retriever.for_part(part_dir)
    # An unsearchable corpus degrades with the core's own message (rebuild to
    # enable search), never as an empty result set that reads like "no match".
    unavailable = retriever.search_unavailable()
    if unavailable:
        print(unavailable, file=sys.stderr)
        return 2

    hits = retriever.search(args.query, limit=args.limit)
    if args.json:
        payload = {
            "part": args.part,
            "query": args.query,
            "hits": [h.as_dict() for h in hits],
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0 if hits else 1
    print(format_search_hits(hits))
    return 0 if hits else 1


def _cmd_plots(args: argparse.Namespace) -> int:
    import json

    from datasheet_analyzer.query import format_plot_hits
    from datasheet_analyzer.retrieve import Retriever

    settings = get_settings()
    part_dir = settings.parts_dir / args.part
    if not (part_dir / "manifest.json").exists():
        print(f"no corpus at {part_dir} — run `dsa build` first", file=sys.stderr)
        return 2

    tags = [t.strip() for t in args.tag.split(",") if t.strip()] if args.tag else []
    hits = Retriever.for_part(part_dir).plots(
        q=args.q or "",
        section=args.section or "",
        tags=tags,
    )
    if args.json:
        # Shape owned by PlotHit.as_dict(), like every other JSON surface.
        payload = {
            "part": args.part,
            "query": {"q": args.q, "section": args.section, "tags": tags},
            "hits": [h.as_dict() for h in hits],
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0 if hits else 1
    print(format_plot_hits(hits))
    return 0 if hits else 1


def _confidence_line(stats) -> str:
    """`confidence: specs 412 high / 190 medium / 17 low` — `""` when ungraded.

    The counts are read from the manifest, where the publisher recorded them;
    the CLI only decides how they read on a terminal. A corpus built before
    per-record grading existed carries no mix and prints no line, rather than
    printing zeros that would look like a graded corpus with no confidence.
    """
    parts = []
    for label, mix in (("specs", stats.spec_confidence), ("plots", stats.plot_confidence)):
        if mix:
            counts = " / ".join(f"{n} {grade}" for grade, n in mix.items())
            parts.append(f"{label} {counts}")
    return f"    confidence: {'; '.join(parts)}" if parts else ""


def _part_vendor_info(part: Path) -> tuple[str, str, list[str], list[str]]:
    """(vendor, evidence, backends, stats_lines) for a part.

    Vendor + evidence always come from sources.json — the pinned acquire
    record (a built part's manifest only mirrors it, and legacy manifests
    predate the field). Backends, the per-record confidence mix and the
    per-document extraction stats come from the manifest when the part is
    built, loaded through `CorpusIndex` so the CLI never parses corpus JSON
    itself. ("", "", [], []) when nothing is registered.
    """
    from datasheet_analyzer.acquire import load_inventory
    from datasheet_analyzer.models import DocType
    from datasheet_analyzer.retrieve import CorpusIndex

    sources = load_inventory(part) if (part / "sources.json").exists() else []
    vendor, evidence = "", ""
    if sources:
        ds = next((s for s in sources if s.doc_type == DocType.DATASHEET), sources[0])
        vendor, evidence = ds.vendor, ds.vendor_evidence
    backends: list[str] = []
    doc_lines: list[str] = []
    m = CorpusIndex.load(part).manifest
    if m is not None:
        backends = list(
            dict.fromkeys(st.backend for st in m.extraction_stats.values() if st.backend)
        )
        confidence = _confidence_line(m.stats)
        if confidence:
            doc_lines.append(confidence)
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
            vendor, evidence, backends, stat_lines = _part_vendor_info(part)
            if vendor:
                label += f" vendor: {vendor}"
                if evidence:
                    label += f" ({evidence})"
                if any(backends):
                    label += f" extraction: {', '.join(backends)}"
            else:
                label += " vendor: (none)"
            print(label)
            for line in stat_lines:
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
    p_batch.add_argument(
        "--force", action="store_true",
        help="rebuild every part even when up to date",
    )
    p_batch.add_argument("--no-cache", action="store_true")
    p_batch.add_argument("--no-llm", action="store_true")
    p_batch.add_argument(
        "--workers", type=int, default=None,
        help="parallel jobs (default: DSA_BATCH_WORKERS env, then 4)",
    )
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
        default="",
        help="explicit golden file (default: discover tests/fixtures/golden_qa_<PART>.yaml)",
    )
    p_verify.set_defaults(func=_cmd_verify)

    p_query = sub.add_parser("query", help="deterministic spec lookup")
    p_query.add_argument("--part", required=True)
    p_query.add_argument("--symbol", default="")
    p_query.add_argument("--name", default="")
    p_query.add_argument("--section", default="")
    p_query.add_argument(
        "--json",
        action="store_true",
        help="emit hits (with matched_via + confidence) as JSON",
    )
    p_query.set_defaults(func=_cmd_query)

    p_search = sub.add_parser("search", help="full-text search with page citations")
    p_search.add_argument("--part", required=True)
    p_search.add_argument("query", help="free text, e.g. \"sysref setup\"")
    p_search.add_argument("--limit", type=int, default=5, help="max hits (default 5)")
    p_search.add_argument(
        "--json", action="store_true", help="emit hits (score, citation, snippet) as JSON"
    )
    p_search.set_defaults(func=_cmd_search)

    p_plots = sub.add_parser("plots", help="deterministic plot lookup")
    p_plots.add_argument("--part", required=True)
    p_plots.add_argument("--q", default="", help="caption/conditions substring")
    p_plots.add_argument("--section", default="", help="exact section number")
    p_plots.add_argument(
        "--tag", default="", help="comma-separated tags (all must match)"
    )
    p_plots.add_argument(
        "--json",
        action="store_true",
        help="emit hits (with matched_via + confidence) as JSON",
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
