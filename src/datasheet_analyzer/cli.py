"""CLI entrypoint: `dsa <command>`.

Commands:
  fetch PART                resolve, download, hash-verify and register a part's documents
  check-revisions PART      ask upstream whether a corpus is still current (opt-in, network)
  build <pdf> --part NAME   full pipeline: acquire -> extract -> corpus
  batch <dir>               build every PDF in a directory as its own part (unchanged parts skipped; --force rebuilds; --workers N parallel, default 4)
  verify --part NAME        golden Q&A citation verification (deterministic)
  audit PART | --all        grade a built corpus against registry/audit_rubric.yaml (--json)
  golden suggest|confirm    propose golden candidates, then confirm them by hand
  query --part NAME         deterministic spec lookup (alias ladder; --json)
  search --part NAME "..."  BM25 full-text search, cited by construction (--json)
  ask --part NAME "..."     one cited answer pack inside a token budget (--json)
  plots --part NAME         deterministic plot lookup (--json)
  pins --part NAME          pin table lookup: pin -> name, name -> pins (--json)
  regs --part NAME          register map lookup: address / name / field (--json)
  card --part NAME --card power|thermal|interface|limits   a task-shaped view
  compare A B [--symbol S | --card power]   two parts, aligned row by row
  project new|add|remove|build|status   the noun above `part`: a design
  serve                     the local workbench (browser) on DSA_SERVE_HOST/PORT
  serve --mcp               the corpus as MCP tools over local stdio
  status                    configuration + detected parts + projects
  version                   print version

`query`, `search`, `ask` and `plots` each take either `--part NAME` or
`--project NAME`; a project fans the lookup out across its member parts and
labels every hit with the part it came from.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from collections.abc import MutableMapping
from pathlib import Path

from datasheet_analyzer.config import PIPELINE_VERSION, get_settings
from datasheet_analyzer.models import CARD_KINDS, PIN_TYPES

log = logging.getLogger("dsa")

#: Where PyMuPDF's own messages go when nobody has said otherwise.
#: `fd:2` is stderr in PyMuPDF's message-destination syntax.
PYMUPDF_MESSAGE_DEFAULT = "fd:2"


def _route_pymupdf_messages(env: MutableMapping[str, str] | None = None) -> None:
    """Send PyMuPDF's own messages to stderr, because stdout is the payload.

    Eight verbs write a JSON payload to stdout and `serve --mcp` writes a
    JSON-RPC stream there. PyMuPDF writes *its* diagnostics to stdout by
    default — a deprecated `fitz` import, a malformed xref, a font it could
    not load — so one line from a dependency turns a machine-readable payload
    into prose the caller's parser rejects.

    Set unconditionally rather than where chatter is expected, because which
    messages appear is not this repo's decision: PyMuPDF 1.28.2 warns on
    `import fitz` and 1.28.0 does not, and `pyproject.toml` pins `>=1.24`.
    Whether `--json` is parseable must not be decided by dependency
    resolution.

    `setdefault`, so an operator who routed messages somewhere deliberately
    keeps their routing.
    """
    (os.environ if env is None else env).setdefault("PYMUPDF_MESSAGE", PYMUPDF_MESSAGE_DEFAULT)


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
    print(f"  hash {source.content_hash[:8]} — {source.page_count} pages — vendor {source.vendor}")
    return 0


def _cmd_fetch(args: argparse.Namespace) -> int:
    """`dsa fetch` — resolve, download, hash-verify, register.

    The one command here that may reach the network for a document (`build`
    stays offline by construction). Everything it can refuse, it refuses with
    the fix in the message: a registry miss names `--url`, an entry with no URL
    repeats the reason it records, and a sha256 mismatch stops without writing
    and names `--accept-new-revision`.

    Exit codes: 0 all good, 1 something was refused (mismatch, miss, download
    failure), 2 the invocation itself does not make sense.
    """
    import json as _json

    from datasheet_analyzer.acquire.fetch import (
        FETCHED,
        MISMATCH,
        SKIPPED,
        fetch_part,
        fetch_project,
    )
    from datasheet_analyzer.acquire.registry import RegistryMiss, registry_path
    from datasheet_analyzer.extract.http import CachingBinaryFetcher
    from datasheet_analyzer.models import DocType

    part = args.part_pos or args.part
    if bool(args.project) == bool(part):
        print(
            "fetch takes either a part (`dsa fetch AFE7950`, `--url … --part X`) "
            "or a project (`dsa fetch --project rf-frontend`), not both and not "
            "neither",
            file=sys.stderr,
        )
        return 2
    if args.url and not part:
        print("--url needs the part it belongs to: --part <PART>", file=sys.stderr)
        return 2
    if not _known_vendor_or_error(args.vendor or ""):
        return 2

    settings = get_settings()
    reg_file = registry_path(settings.registry_dir)
    fetcher = CachingBinaryFetcher(
        settings.cache_dir / "http-bin",
        timeout_s=settings.http_timeout_s,
        delay_s=settings.http_delay_s,
        user_agent=settings.user_agent,
    )
    try:
        if args.project:
            report = fetch_project(
                args.project,
                fetcher=fetcher,
                settings=settings,
                registry_file=reg_file,
                accept_new_revision=args.accept_new_revision,
            )
        else:
            report = fetch_part(
                part,
                fetcher=fetcher,
                settings=settings,
                registry_file=reg_file,
                url=args.url or None,
                doc_type=DocType(args.doc_type) if args.doc_type else None,
                vendor=args.vendor or None,
                accept_new_revision=args.accept_new_revision,
                skip_present=args.skip_present,
            )
    except RegistryMiss as exc:
        print(f"fetch error: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(_json.dumps(report.as_dict(), indent=2))
    else:
        for doc in report.documents:
            if doc.status == FETCHED:
                print(f"fetched {doc.part_number} ({doc.doc_type.value}) -> {doc.path}")
                print(
                    f"  sha256 {doc.sha256[:12]}… — revision "
                    f"{doc.revision or 'unknown'} — registered in sources.json"
                )
                if doc.message:
                    print(f"  {doc.message}")
                print(f"  next: dsa build {doc.path} --part {doc.part_number}")
            elif doc.status == SKIPPED:
                print(f"skipped {doc.part_number} ({doc.doc_type.value}): {doc.message}")
            else:
                label = "WARNING" if doc.status == MISMATCH else "error"
                print(f"{label}: {doc.message}", file=sys.stderr)
        print(
            f"{len(report.fetched)} fetched, {len(report.skipped)} skipped, "
            f"{len(report.failed)} failed"
        )
    return 0 if report.ok else 1


def _cmd_check_revisions(args: argparse.Namespace) -> int:
    """`dsa check-revisions` - the explicit, opt-in, network freshness check.

    Nothing else in this tool calls it: `build`, `ask`, `query`, `search` and
    `verify` never touch the network, and a check that ran implicitly would
    make every lookup depend on a vendor's web server. It writes the three-state
    reading onto each document's Library record and refreshes the `INDEX.md`
    banner, so the result reaches `dsa status`, the index, the audit metric and
    every answer pack footer without a rebuild.

    The download deliberately goes through an **uncached** fetcher: asking
    "what does upstream say now" and answering it out of `.cache/http-bin`
    would report a previous run's bytes as today's upstream.

    Exit codes: 0 everything checked and current, 1 something is stale or a
    check could not run, 2 the invocation does not make sense.
    """
    import json as _json

    from datasheet_analyzer.acquire.registry import registry_path
    from datasheet_analyzer.acquire.revisions import CHECKED, check_all, check_part
    from datasheet_analyzer.extract.http import DirectBinaryFetcher
    from datasheet_analyzer.models import Staleness

    part = args.part_pos or args.part
    if bool(args.all) == bool(part):
        print(
            "check-revisions takes either a part (`dsa check-revisions AFE7950`) "
            "or --all, not both and not neither",
            file=sys.stderr,
        )
        return 2

    settings = get_settings()
    fetcher = DirectBinaryFetcher(
        timeout_s=settings.http_timeout_s,
        delay_s=settings.http_delay_s,
        user_agent=settings.user_agent,
    )
    reg_file = registry_path(settings.registry_dir)
    if args.all:
        report = check_all(fetcher=fetcher, settings=settings, registry_file=reg_file)
    else:
        report = check_part(part, fetcher=fetcher, settings=settings, registry_file=reg_file)

    if args.json:
        print(_json.dumps(report.as_dict(), indent=2))
    else:
        for check in report.checks:
            label = f"{check.part_number} ({check.doc_type.value})"
            if check.status != CHECKED:
                print(f"unchecked {label}: {check.message}", file=sys.stderr)
            elif check.state is Staleness.STALE:
                print(f"STALE {label}: {check.message}", file=sys.stderr)
            else:
                print(f"{check.state.value} {label}: {check.message}")
        print(
            f"{len([c for c in report.checks if c.completed])} checked, "
            f"{len(report.stale)} stale, {len(report.drifted)} content-drift, "
            f"{len(report.failed)} could not be checked"
        )
    return 0 if report.ok else 1


def _cmd_build(args: argparse.Namespace) -> int:
    from datasheet_analyzer.extract import BackendUnavailableError
    from datasheet_analyzer.pipeline import BuildRefused, build_part

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
            revision_label=getattr(args, "rev", "") or "",
            self_contained=args.self_contained,
        )
    except BackendUnavailableError as exc:
        print(f"build error: {exc}", file=sys.stderr)
        return 2
    except BuildRefused as exc:
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
        f"(budget {settings.index_token_budget}); AGENT.md "
        f"{stats.agent_doc_tokens} tokens"
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
    """Per-part golden discovery, owned by `evalh` (phase 7, ticket 05).

    Delegated rather than spelled here so `dsa verify`, `dsa audit` and `dsa
    golden` cannot end up meaning different files by "this part's golden set" -
    a front end may not decide where the objective function lives. It is also
    the one place `DSA_GOLDEN_DIR` takes effect, which is what keeps a confirm
    run in a test off the repository's own benchmarks.
    """
    from datasheet_analyzer.evalh.golden import default_golden_path

    return default_golden_path(part)


def _cmd_verify(args: argparse.Namespace) -> int:
    from datasheet_analyzer.evalh.citations import (
        summarize,
        verify_ask_queries,
        verify_plot_queries,
        verify_questions,
        verify_search_queries,
        verify_spec_queries,
    )
    from datasheet_analyzer.evalh.golden import (
        estimate_lookup_tokens,
        load_golden,
        render_ask_query_report,
        render_plot_query_report,
        render_search_query_report,
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
    from datasheet_analyzer.evalh.candidates import GoldenAssistError

    try:
        questions = load_golden(golden)
    except GoldenAssistError as exc:
        # Pointing `--golden` at a candidate file is the one mistake that would
        # silently swap the objective function for questions nobody confirmed
        # (phase 7, ticket 06). It is refused with the fix, not verified.
        print(f"verify error: {exc}", file=sys.stderr)
        return 2
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

    # Ask- and search-path verification (Phase 5, ticket 09) run on the same
    # terms as the plot table: whenever the golden set carries those questions.
    # They need no `--pdf` — both paths read the corpus the phase built, and
    # their ground truth is the page the question already cites.
    ask_results = verify_ask_queries(questions, part_dir)
    if ask_results:
        print()
        print(render_ask_query_report(ask_results))
        if any(not r.ok for r in ask_results):
            failed = True

    search_results = verify_search_queries(questions, part_dir)
    if search_results:
        print()
        print(render_search_query_report(search_results))
        if any(not r.ok for r in search_results):
            failed = True

    return 0 if not failed else 1


def _scope(args: argparse.Namespace):
    """`(scope, show_part)` for a `--part` / `--project` command, or `(None, …)`.

    Resolution itself is `retrieve.scope.resolve_scope` — the one place the
    `--part` XOR `--project` precondition of ADR 0006 is written down, shared
    with the MCP server and the web application. This wrapper is the CLI's
    *formatting* of that decision and nothing more: it prints the refusal to
    stderr (the caller then exits 2) and decides that a project lookup labels
    each hit with the part it came from.
    """
    from datasheet_analyzer.retrieve.scope import (
        missing_corpus_warning,
        resolve_scope,
        unbuilt_members,
    )

    settings = get_settings()
    project = getattr(args, "project", "")
    scope, reason = resolve_scope(getattr(args, "part", ""), project, settings=settings)
    if scope is None:
        print(f"project error: {reason}" if project else reason, file=sys.stderr)
        return None, bool(project)
    if project:
        # A member whose corpus is gone is named, never silently skipped: the
        # answer would otherwise be quietly missing one device.
        warning = missing_corpus_warning(unbuilt_members(project, settings=settings))
        if warning:
            print(f"warning: {warning}", file=sys.stderr)
    return scope, bool(project)


def _cmd_query(args: argparse.Namespace) -> int:
    import json

    from datasheet_analyzer.query import format_no_match, format_spec_hits

    retriever, show_part = _scope(args)
    if retriever is None:
        return 2
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
            "project": args.project,
            "query": {"symbol": args.symbol, "name": args.name, "section": args.section},
            "hits": [h.as_dict() for h in hits],
            "suggestions": [] if hits else retriever.suggest_specs(term),
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0 if hits else 1

    if not hits:
        print(format_no_match(term, retriever.suggest_specs(term)))
        return 1
    print(format_spec_hits(hits, show_part=show_part))
    return 0


def _cmd_search(args: argparse.Namespace) -> int:
    import json

    from datasheet_analyzer.query import format_search_hits

    retriever, show_part = _scope(args)
    if retriever is None:
        return 2
    # An unsearchable corpus degrades with the core's own message (rebuild to
    # enable search), never as an empty result set that reads like "no match".
    unavailable = retriever.search_unavailable()
    if unavailable:
        print(unavailable, file=sys.stderr)
        return 2
    # A project where only *some* members lack an index can still be searched;
    # the gap is reported so the result is never read as the whole design.
    gap = getattr(retriever, "search_gap", lambda: "")()
    if gap:
        print(f"warning: {gap}", file=sys.stderr)

    hits = retriever.search(args.query, limit=args.limit)
    if args.json:
        payload = {
            "part": args.part,
            "project": args.project,
            "query": args.query,
            "hits": [h.as_dict() for h in hits],
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0 if hits else 1
    print(format_search_hits(hits, show_part=show_part))
    return 0 if hits else 1


def _cmd_ask(args: argparse.Namespace) -> int:
    import json

    from datasheet_analyzer.retrieve import ROUTE_NONE, ROUTE_UNAVAILABLE

    scope, _show_part = _scope(args)
    if scope is None:
        return 2

    # Routing, assembly and the budget all live in the retrieval core; this
    # command only chooses a rendering. The pack renders itself because a
    # budget cannot be enforced on text the core did not produce — and a
    # project pack labels each answer line with its part for the same reason.
    pack = scope.ask(args.question, budget=args.budget)
    if args.json:
        print(json.dumps(pack.as_dict(), ensure_ascii=False, indent=2))
    else:
        print(pack.markdown)
    if pack.route == ROUTE_UNAVAILABLE:
        # Same exit code `dsa search` uses for the same cause: the corpus is
        # degraded, not the question unanswerable.
        return 2
    return 1 if pack.route == ROUTE_NONE else 0


def _cmd_audit(args: argparse.Namespace) -> int:
    """Grade one corpus, or the whole fleet, against the checked-in rubric.

    The scorecard is built and rendered by `audit/` - this command chooses the
    scope and the format and owns the exit codes, exactly as `diff-rev` does.
    The golden benchmark is resolved by the same per-part rule `dsa verify`
    uses, so "the golden pass rate" means the same file in both commands; a
    part with no benchmark reports that metric `n/a` rather than failing,
    because an audit is a reading of what exists and a missing benchmark is one
    of the things it exists to report.

    Exit codes: 0 the audit ran, 1 at least one part graded below the floor
    (`--min-grade`, off by default), 2 there was nothing to grade.
    """
    import json

    from datasheet_analyzer.audit import (
        build_scorecard,
        grade_order,
        render_fleet,
        render_scorecard,
    )
    from datasheet_analyzer.models import AuditGrade
    from datasheet_analyzer.retrieve import discover_parts

    settings = get_settings()
    if args.all:
        targets = discover_parts(settings.parts_dir)
        if not targets:
            print(
                f"audit error: no parts under {settings.parts_dir} - build one first: "
                f"`dsa build <pdf> --part <PART>`",
                file=sys.stderr,
            )
            return 2
    else:
        part = args.part_pos or args.part
        if not part:
            print("audit error: name a part, or pass --all", file=sys.stderr)
            return 2
        part_dir = settings.parts_dir / part
        if not part_dir.is_dir():
            print(
                f"audit error: no corpus for {part} under {settings.parts_dir} - "
                f"build it first: `dsa build <pdf> --part {part}`",
                file=sys.stderr,
            )
            return 2
        targets = [part_dir]

    cards = [
        build_scorecard(part_dir, golden=_default_golden_path(part_dir.name))
        for part_dir in targets
    ]
    if args.json:
        payload = [card.model_dump(mode="json") for card in cards]
        print(json.dumps(payload if args.all else payload[0], ensure_ascii=False, indent=2))
    elif args.all:
        print(render_fleet(cards))
    else:
        print(render_scorecard(cards[0]))

    # A floor is opt-in: an audit that failed the build by default would make
    # `dsa audit` unusable as the reporting tool it is. With one, the phase
    # gate's "every onboarded part grades >= B" becomes a command.
    #
    # An **ungraded** corpus is always below the floor, whatever the floor is:
    # a quality gate that a corpus nobody could measure passes silently is not
    # a gate. It is the same rule the fleet table sorts by, through the same
    # `grade_order`, so a part that prints first there cannot pass here.
    if not args.min_grade:
        return 0
    floor = grade_order(AuditGrade(args.min_grade.upper()))
    below = [c.part for c in cards if c.grade is None or grade_order(c.grade) < floor]
    if below:
        print(
            f"below the {args.min_grade.upper()} floor: {', '.join(sorted(below))}",
            file=sys.stderr,
        )
        return 1
    return 0


def _cmd_golden(args: argparse.Namespace) -> int:
    """`dsa golden suggest|confirm` - the ticket-06 pair (phase 7).

    This command owns the exit codes and the paths; every rule about what a
    candidate is, how it is stratified and what a decision does lives in
    `evalh`. A `GoldenAssistError` already carries the fix in its message
    (which flag, which file), so it is printed as-is rather than re-worded here
    - the same stance `dsa project` takes toward `ProjectError`.

    Exit codes: 0 it ran, 2 it refused (no corpus, no candidates, a decision
    naming a candidate that is not in the set, no decisions on a non-terminal).
    """
    from datasheet_analyzer.evalh.candidates import GoldenAssistError

    actions = {"suggest": _golden_suggest, "confirm": _golden_confirm}
    try:
        return actions[args.action](args)
    except GoldenAssistError as exc:
        print(f"golden error: {exc}", file=sys.stderr)
        return 2


def _golden_paths(args: argparse.Namespace) -> tuple[Path, Path, Path, Path]:
    """`(part_dir, golden, candidates, rejected)` for one `dsa golden` run.

    The benchmark resolves through `_default_golden_path`, which is
    `DSA_GOLDEN_DIR`-aware: `confirm` writes here, and a run that inherited
    default settings must not be able to edit the repository's own fixtures.
    """
    from datasheet_analyzer.evalh.candidates import candidate_path, rejected_path

    settings = get_settings()
    part_dir = settings.parts_dir / args.part
    golden = Path(args.golden) if args.golden else _default_golden_path(args.part)
    candidates = Path(args.out) if getattr(args, "out", "") else candidate_path(golden)
    if getattr(args, "candidates", ""):
        candidates = Path(args.candidates)
    return part_dir, golden, candidates, rejected_path(golden)


def _golden_suggest(args: argparse.Namespace) -> int:
    import json

    from datasheet_analyzer.evalh.candidates import existing_question_ids as golden_ids
    from datasheet_analyzer.evalh.candidates import rejected_keys, write_candidates
    from datasheet_analyzer.evalh.suggest import (
        render_suggestion_report,
        suggest_candidates,
    )

    part_dir, golden, out, rejected = _golden_paths(args)
    candidates = suggest_candidates(
        part_dir,
        n=args.n,
        rejected=rejected_keys(rejected),
        existing_ids=golden_ids(golden),
    )
    write_candidates(out, candidates)
    if args.json:
        print(json.dumps(candidates.model_dump(mode="json"), ensure_ascii=False, indent=2))
    else:
        print(render_suggestion_report(candidates, out))
    return 0


def _split_ids(raw: str) -> list[str]:
    return [item.strip() for item in (raw or "").split(",") if item.strip()]


def _golden_confirm(args: argparse.Namespace) -> int:
    from datasheet_analyzer.evalh.candidates import (
        GoldenAssistError,
        read_candidates,
        write_candidates,
        write_rejections,
    )
    from datasheet_analyzer.evalh.confirm import (
        PROVENANCE_BULK,
        PROVENANCE_CORPUS,
        PROVENANCE_PAGE,
        apply_decisions,
        decisions_from_ids,
        load_decisions,
        merge_into_golden,
        render_confirm_report,
        run_interactive,
    )
    from datasheet_analyzer.evalh.suggest import strata_of
    from datasheet_analyzer.models import GoldenCandidateSet

    part_dir, golden, candidates_file, rejected_file = _golden_paths(args)
    candidates = read_candidates(candidates_file)

    decisions = decisions_from_ids(
        _split_ids(args.accept_ids), _split_ids(args.reject_ids), reason=args.reject_reason
    )
    if args.decisions:
        decisions = load_decisions(Path(args.decisions)) + decisions
    # How the decisions were arrived at is recorded in the golden file, so it
    # is decided here - where the command knows whether a page was ever shown -
    # rather than assumed by the writer. The default is the bulk sentence: a
    # claim of human page-verification is only made when one is true.
    provenance = PROVENANCE_BULK
    if not decisions:
        # The interactive shell is the default *only* where there is a person
        # to answer it. A non-interactive run with no decisions must refuse
        # rather than accept nothing quietly or, far worse, accept everything.
        if not (args.interactive or sys.stdin.isatty()):
            raise GoldenAssistError(
                "no decisions given and no terminal to ask on - pass "
                "--decisions <file>, --accept-ids or --reject-ids "
                "(run in a terminal, or add --interactive, to walk them by hand)"
            )
        pages = _page_texts(args.pdf) if args.pdf else []
        provenance = PROVENANCE_PAGE if pages else PROVENANCE_CORPUS
        decisions = run_interactive(candidates, part_dir=part_dir, page_texts=pages)

    outcome = apply_decisions(candidates, decisions)
    if args.dry_run:
        print(
            render_confirm_report(
                outcome,
                _dry_merge(golden, outcome, provenance),
                rejected_file=rejected_file if outcome.rejected else None,
            )
        )
        print("(--dry-run: nothing was written)")
        return 0

    merge = merge_into_golden(golden, outcome.accepted, provenance=provenance, part=candidates.part)
    if outcome.rejected:
        write_rejections(rejected_file, candidates.part, outcome.rejected)
    write_candidates(
        candidates_file,
        GoldenCandidateSet(
            schema_version=candidates.schema_version,
            part=candidates.part,
            candidates=outcome.deferred,
            strata=strata_of(outcome.deferred),
            pool=candidates.pool,
            refused=candidates.refused,
            skipped_rejected=candidates.skipped_rejected,
            skipped_existing=candidates.skipped_existing,
            notes=candidates.notes,
        ),
    )
    print(
        render_confirm_report(
            outcome, merge, rejected_file=rejected_file if outcome.rejected else None
        )
    )
    return 0


def _dry_merge(golden: Path, outcome, provenance: str):
    """The merge a `--dry-run` would have made, without making it."""
    from datasheet_analyzer.evalh.candidates import existing_question_ids
    from datasheet_analyzer.evalh.confirm import MergeResult

    return MergeResult(
        path=golden,
        added=[q.id for q in outcome.accepted],
        preserved=sorted(existing_question_ids(golden)),
        created=not golden.exists(),
        provenance=provenance,
    )


def _page_texts(pdf: str) -> list[str]:
    from datasheet_analyzer.extract.pdf_structure import page_texts

    return page_texts(Path(pdf))


def _cmd_plots(args: argparse.Namespace) -> int:
    import json

    from datasheet_analyzer.query import format_plot_hits

    scope, show_part = _scope(args)
    if scope is None:
        return 2

    tags = [t.strip() for t in args.tag.split(",") if t.strip()] if args.tag else []
    hits = scope.plots(
        q=args.q or "",
        section=args.section or "",
        tags=tags,
        x_label=args.x_label or "",
        y_label=args.y_label or "",
        near_x=args.near_x or "",
        near_y=args.near_y or "",
    )
    if args.json:
        # Shape owned by PlotHit.as_dict(), like every other JSON surface.
        payload = {
            "part": args.part,
            "project": args.project,
            "query": {
                "q": args.q,
                "section": args.section,
                "tags": tags,
                # What narrowed the result must be visible to a machine
                # reader, or an empty `hits` is unattributable.
                "x_label": args.x_label,
                "y_label": args.y_label,
                "near_x": args.near_x,
                "near_y": args.near_y,
            },
            "hits": [h.as_dict() for h in hits],
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0 if hits else 1
    print(format_plot_hits(hits, show_part=show_part))
    return 0 if hits else 1


# --- Phase 6 derived-artifact commands -------------------------------------
#
# `pins`, `regs`, `card` and `compare` are declared here — flags, help text,
# exit codes — and implemented in `derive/`. The split is deliberate and is
# the phase's contract: ten tickets run in parallel against one command line,
# so the command line is frozen once, by ticket 01, and each later ticket
# writes only its own module. None of them edits this file.
#
# Until a module lands, its command parses, prints why it is not available and
# exits 3 — the same honest-degradation rule the optional `mcp` / `web` extras
# already follow. It never traces back, and it never silently prints nothing,
# which would read as "this part has no pins".


#: Exit code for a declared-but-not-yet-implemented command. Distinct from 1
#: ("no match" — a real answer) and 2 ("bad usage / degraded corpus") so a
#: script can tell "the tool cannot do this yet" from "the corpus cannot
#: answer this".
EXIT_NOT_IMPLEMENTED = 3

#: Which module and entry point each phase-6 command delegates to. The value
#: is the frozen signature every implementing ticket writes against:
#: `def cli_<name>(args: argparse.Namespace) -> int`.
DERIVED_COMMANDS: dict[str, tuple[str, str]] = {
    "pins": ("datasheet_analyzer.derive.pins", "cli_pins"),
    "regs": ("datasheet_analyzer.derive.registers", "cli_regs"),
    "card": ("datasheet_analyzer.derive.cards", "cli_card"),
    "compare": ("datasheet_analyzer.derive.compare", "cli_compare"),
}


def not_implemented_message(command: str) -> str:
    """What `dsa <command>` prints while its module is still unwritten."""
    module, func = DERIVED_COMMANDS[command]
    return (
        f"dsa {command}: not available in this build — it is declared here but "
        f"{module}.{func}() has not landed yet. Nothing is missing from your "
        f"corpus; the command itself is unfinished."
    )


def _run_derived(command: str, args: argparse.Namespace) -> int:
    """Delegate one phase-6 command to its module, degrading honestly.

    The import is deliberately inside the call, like every other command in
    this file: `dsa --help` must not pay for a module it is not going to run,
    and a command whose module does not exist yet must fail as a message
    rather than as an `ImportError` at startup for every other command too.
    """
    from importlib import import_module

    module_path, func_name = DERIVED_COMMANDS[command]
    try:
        func = getattr(import_module(module_path), func_name)
    except (ImportError, AttributeError):
        print(not_implemented_message(command), file=sys.stderr)
        return EXIT_NOT_IMPLEMENTED
    return int(func(args))


def _cmd_pins(args: argparse.Namespace) -> int:
    return _run_derived("pins", args)


def _cmd_regs(args: argparse.Namespace) -> int:
    return _run_derived("regs", args)


def _cmd_card(args: argparse.Namespace) -> int:
    return _run_derived("card", args)


def _cmd_compare(args: argparse.Namespace) -> int:
    return _run_derived("compare", args)


def _cmd_diff_rev(args: argparse.Namespace) -> int:
    """Print and write one revision diff — the corpus's own report, not a re-layout.

    The diff renders itself (`revdiff.render_revision_diff`), for the same reason
    a design card, an answer pack and a comparison do. This command chooses the
    two sides, the format and the destination, and owns the exit codes.

    Exit codes: 0 the diff ran (an empty diff is a valid, successful answer — it
    is the determinism check the ticket asks for), 2 the two sides could not be
    chosen. A refusal under `--json` is reported **as JSON on stdout**, the way
    `dsa fetch` and `dsa check-revisions` report theirs: a machine caller asked
    for one payload shape and must not have to parse prose to learn it failed.
    """
    import json

    from datasheet_analyzer.config import REVDIFF_SCHEMA_VERSION
    from datasheet_analyzer.publish import write_revision_diff
    from datasheet_analyzer.retrieve.revdiff import RevisionPair
    from datasheet_analyzer.revdiff import render_revision_diff

    def _refuse(message: str) -> int:
        if args.json:
            print(
                json.dumps(
                    {
                        "schema_version": REVDIFF_SCHEMA_VERSION,
                        "part_number": args.part,
                        "ok": False,
                        "error": message,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
        print(f"diff-rev error: {message}", file=sys.stderr)
        return 2

    settings = get_settings()
    part_dir = settings.parts_dir / args.part
    if not (part_dir / "manifest.json").exists():
        return _refuse(
            f"no corpus for {args.part} under {settings.parts_dir} — build it "
            f"first: `dsa build <pdf> --part {args.part}`"
        )

    pair, error = RevisionPair.for_part(
        part_dir, before=args.from_rev or "", after=args.to_rev or ""
    )
    if pair is None:
        return _refuse(error)

    diff = pair.diff()
    markdown = render_revision_diff(diff)
    written = None
    if not args.no_write:
        written = write_revision_diff(part_dir, markdown)

    if args.json:
        print(json.dumps(diff.model_dump(mode="json"), ensure_ascii=False, indent=2))
    else:
        print(markdown)
    if written is not None:
        print(f"written: {written}", file=sys.stderr)
    return 0


#: What to print when the optional MCP extra is not installed. Named here so
#: the message a user sees and the message a test asserts are the same string.
MCP_INSTALL_HINT = (
    "serve error: the MCP server needs the optional `mcp` SDK, which is not "
    'installed. Install the extra: `pip install -e ".[mcp]"` (or '
    '`uv pip install --python .venv/Scripts/python.exe -e ".[mcp]"`). '
    "Everything else in `dsa` works without it."
)


#: The same, for the optional web extra. `dsa serve` with no flag is the
#: workbench, and FastAPI/uvicorn are as optional as the MCP SDK is — a plain
#: install must not pay for either, and must not fail with a traceback when a
#: user asks for one it does not have.
WEB_INSTALL_HINT = (
    "serve error: the local workbench needs the optional `web` extra "
    "(fastapi, uvicorn, sse-starlette), which is not installed. Install the "
    'extra: `pip install -e ".[web]"` (or '
    '`uv pip install --python .venv/Scripts/python.exe -e ".[web]"`). '
    "Everything else in `dsa` works without it."
)


def _cmd_serve(args: argparse.Namespace) -> int:
    """`dsa serve` — the local workbench; `dsa serve --mcp` — MCP over stdio.

    Two transports, each stated explicitly. `--mcp` was never a default and
    does not become one now: an MCP client speaks over the pipe it already
    owns, a person opens a browser, and silently switching between the two on
    a flag's absence would make `dsa serve` mean different things over time.
    """
    return _serve_mcp() if args.mcp else _serve_web()


def _serve_mcp() -> int:
    """The corpus as MCP tools over local stdio.

    Local stdio is the only MCP transport (Phase 5 plan, Out of Scope: HTTP,
    auth, multi-tenancy).
    """
    try:
        from datasheet_analyzer.mcp_server import serve_stdio
    except ImportError as exc:
        print(f"{MCP_INSTALL_HINT} ({exc})", file=sys.stderr)
        return 2
    serve_stdio(get_settings())
    return 0


def _serve_web() -> int:
    """The local workbench: the FastAPI app on `serve_host` / `serve_port`.

    The app is imported *inside* the handler so a plain install never pays
    for FastAPI, and a missing web extra is an install hint rather than a
    traceback — exactly how the MCP branch above already behaves.

    The bind address is `settings.serve_host`, which defaults to `127.0.0.1`.
    This is a single-user local tool with no authentication: binding
    `0.0.0.0` would publish an unauthenticated corpus browser, and every
    document in it, to the network.
    """
    settings = get_settings()
    try:
        import uvicorn

        from datasheet_analyzer.app.main import create_app
    except ImportError as exc:
        print(f"{WEB_INSTALL_HINT} ({exc})", file=sys.stderr)
        return 2
    print(f"datasheet workbench: http://{settings.serve_host}:{settings.serve_port}")
    uvicorn.run(
        create_app(settings),
        host=settings.serve_host,
        port=settings.serve_port,
    )
    return 0


def _cmd_project(args: argparse.Namespace) -> int:
    """`dsa project new|add|remove|build|status`.

    Every action delegates to `datasheet_analyzer.projects`; this function
    owns the exit codes and the printing only. A `ProjectError` carries the
    fix in its message (which corpus is missing, which command builds it), so
    it is printed as-is rather than re-worded here.
    """
    from datasheet_analyzer.projects import ProjectError

    actions = {
        "new": _project_new,
        "add": _project_add,
        "remove": _project_remove,
        "build": _project_build,
        "status": _project_status,
    }
    settings = get_settings()
    try:
        return actions[args.action](args, settings)
    except ProjectError as exc:
        print(f"project error: {exc}", file=sys.stderr)
        return 2


def _project_new(args: argparse.Namespace, settings) -> int:
    from datasheet_analyzer.projects import new_project, project_dir

    project = new_project(
        args.name, settings.projects_dir, interfaces=args.interfaces, notes=args.notes
    )
    print(f"project: {project_dir(project.name, settings.projects_dir)}")
    print(f"  0 parts — add one with `dsa project add {project.name} <PART>`")
    return 0


def _project_add(args: argparse.Namespace, settings) -> int:
    from datasheet_analyzer.projects import add_parts, load_project, save_project

    project = load_project(args.name, settings.projects_dir)
    added = add_parts(project, args.parts, parts_dir=settings.parts_dir, role=args.role)
    save_project(project, settings.projects_dir)
    print(f"project {project.name}: {_members_label(project)}")
    print(f"  added {', '.join(added)}" if added else "  nothing added (already members)")
    print(f"  rebuild the index: `dsa project build {project.name}`")
    return 0


def _project_remove(args: argparse.Namespace, settings) -> int:
    from datasheet_analyzer.projects import load_project, remove_parts, save_project

    project = load_project(args.name, settings.projects_dir)
    removed = remove_parts(project, args.parts)
    save_project(project, settings.projects_dir)
    print(f"project {project.name}: {_members_label(project)}")
    print(f"  removed {', '.join(removed)}" if removed else "  nothing removed (not members)")
    print(f"  rebuild the index: `dsa project build {project.name}`")
    return 0


def _project_build(args: argparse.Namespace, settings) -> int:
    from datasheet_analyzer.projects import load_project, write_project_index
    from datasheet_analyzer.protocol import AGENT_DOC_TOKEN_BUDGET, AGENT_FILENAME
    from datasheet_analyzer.tokens import count_tokens

    project = load_project(args.name, settings.projects_dir)
    path, text = write_project_index(
        project,
        parts_dir=settings.parts_dir,
        projects_dir=settings.projects_dir,
        token_budget=settings.project_index_token_budget,
    )
    print(f"project index: {path}")
    print(
        f"  {len(project.parts)} parts — {count_tokens(text)} tokens "
        f"(budget {settings.project_index_token_budget})"
    )
    agent = path.parent / AGENT_FILENAME
    print(
        f"  agent protocol: {agent.name} — "
        f"{count_tokens(agent.read_text(encoding='utf-8'))} tokens "
        f"(budget {AGENT_DOC_TOKEN_BUDGET})"
    )
    return 0


def _project_status(args: argparse.Namespace, settings) -> int:
    from datasheet_analyzer.projects import list_projects

    names = [args.name] if args.name else list_projects(settings.projects_dir)
    if not names:
        print(f"no projects under {settings.projects_dir}")
        return 0
    for name in names:
        for line in _project_lines(name, settings):
            print(line)
    return 0


def _members_label(project) -> str:
    if not project.parts:
        return "0 parts"
    return f"{len(project.parts)} parts ({', '.join(project.part_numbers)})"


def _project_lines(name: str, settings) -> list[str]:
    """`  project: rf-frontend [built] parts: …` plus any honest warning."""
    from datasheet_analyzer.projects import (
        INDEX_FILENAME,
        ProjectError,
        is_built,
        load_project,
        project_dir,
    )

    try:
        project = load_project(name, settings.projects_dir)
    except ProjectError as exc:
        return [f"  project: {name} [unreadable] {exc}"]
    built = (project_dir(name, settings.projects_dir) / INDEX_FILENAME).exists()
    label = f"  project: {name} {'[built]' if built else '[no index]'}"
    label += f" parts: {', '.join(project.part_numbers) or '(none)'}"
    lines = [label]
    missing = [p for p in project.part_numbers if not is_built(p, settings.parts_dir)]
    if missing:
        lines.append(f"    no corpus for: {', '.join(missing)} — run `dsa build`")
    return lines


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
    from datasheet_analyzer.staleness import load_corpus_staleness, status_lines

    sources = load_inventory(part) if (part / "sources.json").exists() else []
    vendor, evidence = "", ""
    if sources:
        ds = next((s for s in sources if s.doc_type == DocType.DATASHEET), sources[0])
        vendor, evidence = ds.vendor, ds.vendor_evidence
    backends: list[str] = []
    doc_lines: list[str] = []
    # Revision freshness first (phase 7, ticket 02): of everything `status`
    # prints about a part, this is the only line that can invalidate the rest.
    if sources:
        doc_lines.extend(status_lines(load_corpus_staleness(part)))
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
            line = (
                f"    {doc.doc_type.value}-{doc.content_hash[:8]}: backend "
                f"{st.backend} · tables: {st.tables_detected} detected / "
                f"{st.tables_accepted} accepted / {st.tables_rejected} rejected"
            )
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
    from datasheet_analyzer.projects import list_projects

    settings = get_settings()
    print(f"datasheet-analyzer {PIPELINE_VERSION}")
    print(f"parts_dir: {settings.parts_dir}")
    print(f"projects_dir: {settings.projects_dir}")
    print(f"cache_dir: {settings.cache_dir}")
    print(
        f"llm: {'available (' + settings.model + ')' if settings.llm_available else 'NO KEY (deterministic mode)'}"
    )
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
    # Projects are listed alongside parts: a design is the unit a reader
    # orients on, and it is invisible unless `status` says it exists.
    for name in list_projects(settings.projects_dir):
        for line in _project_lines(name, settings):
            print(line)
    return 0


def _add_scope(parser: argparse.ArgumentParser) -> None:
    """`--part NAME` or `--project NAME`, exactly one of them.

    Mutually exclusive and required: a lookup has to know what it is asking,
    and defaulting to "all parts" would make the scope of an answer implicit.
    """
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--part", default="", help="one built part, e.g. AFE7950")
    group.add_argument(
        "--project",
        default="",
        help="every part of a project; each hit is labelled with its part",
    )


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    # Before any command function can lazily reach `fitz`: stdout belongs to
    # the payload, so PyMuPDF's messages go to stderr.
    _route_pymupdf_messages()
    # Windows consoles default to cp1252 — reports contain ✅/❌/± etc.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    parser = argparse.ArgumentParser(prog="dsa", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p_fetch = sub.add_parser(
        "fetch",
        help="download a part's documents from the curated registry and register them",
    )
    p_fetch.add_argument(
        "part_pos",
        nargs="?",
        default="",
        metavar="PART",
        help="part number, e.g. AFE7950 (or use --part with --url)",
    )
    p_fetch.add_argument("--part", default="", help="part number (with --url)")
    p_fetch.add_argument(
        "--url",
        default="",
        help="fetch this URL and record it in the registry — the growth path "
        "for a part the registry does not know yet",
    )
    p_fetch.add_argument(
        "--doc-type",
        default="",
        choices=["datasheet", "register_map", "errata", "app_note", "unknown"],
        help="document type for --url (default: datasheet)",
    )
    p_fetch.add_argument(
        "--project",
        default="",
        help="fetch everything this project's parts are missing",
    )
    p_fetch.add_argument(
        "--accept-new-revision",
        action="store_true",
        help="record the fetched hash and revision after a sha256 mismatch "
        "(look at the upstream document first)",
    )
    p_fetch.add_argument(
        "--skip-present",
        action="store_true",
        help="skip documents already registered in the part's inventory (always on for --project)",
    )
    p_fetch.add_argument(
        "--vendor", default="", help="explicit vendor override for the registered document"
    )
    p_fetch.add_argument("--json", action="store_true")
    p_fetch.set_defaults(func=_cmd_fetch)

    p_check = sub.add_parser(
        "check-revisions",
        help="ask upstream whether a built corpus is still the current revision "
        "(explicit, opt-in, network - never part of build)",
    )
    p_check.add_argument(
        "part_pos",
        nargs="?",
        default="",
        metavar="PART",
        help="part number, e.g. AFE7950 (or --all)",
    )
    p_check.add_argument("--part", default="", help="part number")
    p_check.add_argument("--all", action="store_true", help="check every part under parts_dir")
    p_check.add_argument("--json", action="store_true")
    p_check.set_defaults(func=_cmd_check_revisions)

    p_build = sub.add_parser("build", help="build a part corpus from a datasheet PDF")
    p_build.add_argument("pdf")
    p_build.add_argument("--part", required=True, help="part number, e.g. AFE7950")
    p_build.add_argument(
        "--vendor",
        default="",
        help="explicit vendor override, e.g. adi (default: detected + pinned)",
    )
    p_build.add_argument(
        "--rev",
        default="",
        help=(
            "record the revision this copy is, on its Library record, so "
            "`dsa diff-rev --from/--to` can name it. It does not widen the "
            "build: a part still builds one datasheet"
        ),
    )
    p_build.add_argument("--no-cache", action="store_true")
    p_build.add_argument("--no-llm", action="store_true")
    p_build.add_argument(
        "--self-contained",
        action="store_true",
        help=(
            "publish every artifact under parts/<PART>/docs/ instead of the "
            "shared library store (ADR 0008: what a tracked corpus must be)"
        ),
    )
    p_build.set_defaults(func=_cmd_build)

    p_batch = sub.add_parser(
        "batch",
        help="build every PDF directly inside a directory as its own part corpus",
    )
    p_batch.add_argument("dir", help="directory of datasheet PDFs (flat scan)")
    p_batch.add_argument(
        "--force",
        action="store_true",
        help="rebuild every part even when up to date",
    )
    p_batch.add_argument("--no-cache", action="store_true")
    p_batch.add_argument("--no-llm", action="store_true")
    p_batch.add_argument(
        "--workers",
        type=int,
        default=None,
        help="parallel jobs (default: DSA_BATCH_WORKERS env, then 4)",
    )
    p_batch.set_defaults(func=_cmd_batch)

    p_add = sub.add_parser(
        "add-doc", help="register a companion document (register map, errata, app note)"
    )
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
    _add_scope(p_query)
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
    _add_scope(p_search)
    p_search.add_argument("query", help='free text, e.g. "sysref setup"')
    p_search.add_argument("--limit", type=int, default=5, help="max hits (default 5)")
    p_search.add_argument(
        "--json", action="store_true", help="emit hits (score, citation, snippet) as JSON"
    )
    p_search.set_defaults(func=_cmd_search)

    p_ask = sub.add_parser(
        "ask", help="one cited, budget-bounded answer pack (spec / plot / search)"
    )
    _add_scope(p_ask)
    p_ask.add_argument("question", help="a designer's question, in plain words")
    p_ask.add_argument(
        "--budget",
        type=int,
        default=0,
        help="token budget for the pack (default: DSA_ASK_BUDGET, then 4000)",
    )
    p_ask.add_argument(
        "--json", action="store_true", help="emit the pack as JSON (declared schema)"
    )
    p_ask.set_defaults(func=_cmd_ask)

    p_audit = sub.add_parser(
        "audit",
        help="grade a built corpus against the checked-in rubric (registry/audit_rubric.yaml)",
    )
    p_audit.add_argument(
        "part_pos",
        nargs="?",
        default="",
        metavar="PART",
        help="part number, e.g. AFE7950 (or --all)",
    )
    p_audit.add_argument("--part", default="", help="part number")
    p_audit.add_argument("--all", action="store_true", help="grade every part under parts_dir")
    p_audit.add_argument(
        "--min-grade",
        dest="min_grade",
        default="",
        choices=["A", "B", "C", "D", "F"],
        help="exit 1 when any graded part falls below this letter "
        "(an ungraded part is always below it)",
    )
    p_audit.add_argument("--json", action="store_true", help="emit the scorecard(s) as JSON")
    p_audit.set_defaults(func=_cmd_audit)

    p_golden = sub.add_parser(
        "golden",
        help="generate golden Q&A candidates, then confirm them by hand "
        "(a candidate counts toward `dsa verify` only once confirmed)",
    )
    gsub = p_golden.add_subparsers(dest="action", required=True)

    g_suggest = gsub.add_parser(
        "suggest",
        help="template stratified candidate questions from published records",
    )
    g_suggest.add_argument("--part", required=True, help="part number, e.g. AFE7950")
    g_suggest.add_argument(
        "--n", type=int, default=20, help="how many candidates to propose (default 20)"
    )
    g_suggest.add_argument("--golden", default="", help="the benchmark the candidates sit beside")
    g_suggest.add_argument("--out", default="", help="write the candidate file here instead")
    g_suggest.add_argument("--json", action="store_true", help="emit the candidate set as JSON")

    g_confirm = gsub.add_parser(
        "confirm",
        help="walk candidates (accept/edit/reject) and merge the accepted ones",
    )
    g_confirm.add_argument("--part", required=True, help="part number")
    g_confirm.add_argument("--pdf", default="", help="the printed PDF, shown beside each candidate")
    g_confirm.add_argument("--golden", default="", help="benchmark file to merge into")
    g_confirm.add_argument("--candidates", default="", help="candidate file to walk")
    g_confirm.add_argument(
        "--decisions",
        default="",
        help="a YAML decisions file (accept/edit/reject per candidate id)",
    )
    g_confirm.add_argument(
        "--accept-ids",
        dest="accept_ids",
        default="",
        help="comma-separated candidate ids to accept without prompting",
    )
    g_confirm.add_argument(
        "--reject-ids",
        dest="reject_ids",
        default="",
        help="comma-separated candidate ids to reject without prompting",
    )
    g_confirm.add_argument(
        "--reject-reason",
        dest="reject_reason",
        default="",
        help="the reason recorded for every --reject-ids rejection",
    )
    g_confirm.add_argument("--interactive", action="store_true", help="force the interactive walk")
    g_confirm.add_argument(
        "--dry-run",
        dest="dry_run",
        action="store_true",
        help="print what would be merged without writing anything",
    )
    p_golden.set_defaults(func=_cmd_golden)

    p_plots = sub.add_parser("plots", help="deterministic plot lookup")
    _add_scope(p_plots)
    p_plots.add_argument("--q", default="", help="caption/conditions substring")
    p_plots.add_argument("--section", default="", help="exact section number")
    p_plots.add_argument("--tag", default="", help="comma-separated tags (all must match)")
    # Axis filters match what the figure *prints on its axes*, not what its
    # caption says. A figure whose axes could not be read is ruled out by
    # them — `query.find_plots` documents why that is the honest direction.
    p_plots.add_argument("--x-label", default="", help="substring of the printed x-axis title")
    p_plots.add_argument("--y-label", default="", help="substring of the printed y-axis title")
    p_plots.add_argument(
        "--near-x",
        default="",
        help="keep figures whose printed x range covers this quantity, e.g. 3.5GHz",
    )
    p_plots.add_argument("--near-y", default="", help="the same for the y axis, e.g. -40dBc")
    p_plots.add_argument(
        "--json",
        action="store_true",
        help="emit hits (with matched_via + confidence) as JSON",
    )
    p_plots.set_defaults(func=_cmd_plots)

    # --- Phase 6: derived artifacts. Flags frozen here, behaviour in `derive/`.
    p_pins = sub.add_parser("pins", help="deterministic pin table lookup")
    _add_scope(p_pins)
    p_pins.add_argument("--q", default="", help="pin, name or description substring")
    p_pins.add_argument(
        "--type",
        default="",
        choices=("", *PIN_TYPES),
        help="filter by pin type from the checked-in lexicon",
    )
    p_pins.add_argument("--json", action="store_true", help="emit hits (with confidence) as JSON")
    p_pins.set_defaults(func=_cmd_pins)

    p_regs = sub.add_parser("regs", help="deterministic register map lookup")
    _add_scope(p_regs)
    p_regs.add_argument("--name", default="", help="register name substring")
    p_regs.add_argument("--addr", default="", help="address as printed, e.g. 0x1A04")
    p_regs.add_argument("--field", default="", help="bit-field name substring")
    p_regs.add_argument("--json", action="store_true", help="emit registers (with fields) as JSON")
    p_regs.set_defaults(func=_cmd_regs)

    p_card = sub.add_parser("card", help="a task-shaped view over records that already exist")
    _add_scope(p_card)
    p_card.add_argument("--card", required=True, choices=CARD_KINDS, help="which card to render")
    p_card.add_argument(
        "--json", action="store_true", help="emit the card (with provenance) as JSON"
    )
    p_card.set_defaults(func=_cmd_card)

    p_compare = sub.add_parser(
        "compare", help="align two or more parts row by row, with an SI delta"
    )
    p_compare.add_argument("parts", nargs="+", help="part numbers, e.g. AFE7950 AFE7953")
    p_compare.add_argument("--symbol", default="", help="one alias-resolved symbol")
    p_compare.add_argument(
        "--card", default="", choices=("", *CARD_KINDS), help="compare a whole card"
    )
    p_compare.add_argument("--json", action="store_true", help="emit the comparison as JSON")
    p_compare.set_defaults(func=_cmd_compare)

    p_diff = sub.add_parser(
        "diff-rev",
        help="diff two revisions of one part: specs, sections, pins, registers",
    )
    p_diff.add_argument("--part", required=True, help="part number, e.g. AFE7950")
    # `--from` is a Python keyword, so argparse stores it under an explicit dest.
    p_diff.add_argument(
        "--from",
        dest="from_rev",
        default="",
        help="the earlier revision: its --rev label, printed revision, or doc dir",
    )
    p_diff.add_argument(
        "--to",
        dest="to_rev",
        default="",
        help="the later revision (omit both to diff a part holding exactly two)",
    )
    p_diff.add_argument(
        "--json",
        action="store_true",
        help="emit the diff as JSON (every value in its provenance envelope)",
    )
    p_diff.add_argument(
        "--no-write",
        action="store_true",
        help="print the report without writing parts/<PART>/REVISION_DIFF.md",
    )
    p_diff.set_defaults(func=_cmd_diff_rev)

    p_project = sub.add_parser("project", help="group parts into a design (the noun above `part`)")
    psub = p_project.add_subparsers(dest="action", required=True)

    pp_new = psub.add_parser("new", help="create an empty project")
    pp_new.add_argument("name", help="project name, e.g. rf-frontend")
    pp_new.add_argument("--interfaces", default="", help="free-text note on how the parts connect")
    pp_new.add_argument("--notes", default="", help="free-text project notes")

    pp_add = psub.add_parser("add", help="add built parts to a project")
    pp_add.add_argument("name")
    pp_add.add_argument("parts", nargs="+", help="part numbers, e.g. AFE7950 HMC520A")
    pp_add.add_argument(
        "--role", default="", help="one-line role in this design (applies to each part named)"
    )

    pp_remove = psub.add_parser("remove", help="remove parts from a project")
    pp_remove.add_argument("name")
    pp_remove.add_argument("parts", nargs="+")

    pp_build = psub.add_parser("build", help="write PROJECT_INDEX.md under its budget")
    pp_build.add_argument("name")

    pp_status = psub.add_parser("status", help="list projects and their parts")
    pp_status.add_argument("name", nargs="?", default="", help="one project (default: all)")

    p_project.set_defaults(func=_cmd_project)

    p_serve = sub.add_parser(
        "serve",
        help="run the local workbench in a browser (--mcp: MCP tools over stdio)",
    )
    p_serve.add_argument(
        "--mcp",
        action="store_true",
        help="speak MCP on stdin/stdout instead of serving the workbench",
    )
    p_serve.set_defaults(func=_cmd_serve)

    p_status = sub.add_parser("status", help="show configuration, parts and projects")
    p_status.set_defaults(func=_cmd_status)

    p_version = sub.add_parser("version", help="print version")
    p_version.set_defaults(func=lambda _a: print(PIPELINE_VERSION) or 0)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
