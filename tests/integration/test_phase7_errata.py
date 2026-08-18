"""Phase 7, ticket 04 gate — errata cross-linking on a real datasheet.

The document being linked *to* is real: `tests/fixtures/pdf/lm741.pdf`, built by
the whole pipeline into the corpus every other gate uses. The errata document is
synthetic (`tests/fixtures/synthetic/errata_doc.py`) because this repo holds no
vendor errata PDF and none can be fetched offline — the honest split is recorded
there and in `Reports/PHASE_7_LIVE_RUN.md`.

What the gate proves, end to end and through the published files rather than
through the linker's return value:

- a real section number and a real spec row are linked, and each link names the
  rule and the identifier it fired on;
- an item the matcher could not place is **still published**, under the
  "unlinked errata" heading — the failure this ticket exists to prevent;
- the affected section files carry a warning banner at publish;
- an answer pack whose supporting record is targeted carries the warning inline;
- a part with no errata document is untouched: no file, no banner, no warning.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from datasheet_analyzer.acquire import append_to_inventory, register_source
from datasheet_analyzer.config import ERRATA_SCHEMA_VERSION, Settings
from datasheet_analyzer.errata import (
    ERRATA_LINKS_FILENAME,
    ERRATA_MARKDOWN_FILENAME,
    UNLINKED_HEADING,
)
from datasheet_analyzer.errata.render import BANNER_MARKER
from datasheet_analyzer.models import ErrataLinkSet
from datasheet_analyzer.pipeline import build_part
from datasheet_analyzer.retrieve import Retriever, clear_index_cache
from datasheet_analyzer.retrieve.pack import ROUTE_SPEC, build_pack

sys.path.insert(0, str(Path(__file__).parent.parent / "fixtures" / "synthetic"))
import errata_doc

LM741 = Path(__file__).parent.parent / "fixtures" / "pdf" / "lm741.pdf"


def _build(tmp_path: Path, *, with_errata: bool) -> tuple[Settings, Path]:
    """Build LM741 with (or without) the synthetic errata companion attached."""
    if not LM741.exists():  # pragma: no cover - the fixture is committed
        pytest.fail(f"missing committed gate fixture: {LM741}")
    settings = Settings(
        parts_dir=tmp_path / "parts", cache_dir=tmp_path / ".cache"
    ).resolve()
    part_dir = settings.parts_dir / errata_doc.PART
    sources = [
        register_source(
            LM741, part_number=errata_doc.PART, doc_type="datasheet", vendor="unknown"
        )
    ]
    if with_errata:
        pdf = errata_doc.write_errata_pdf(tmp_path / "lm741_errata.pdf")
        sources.append(
            register_source(
                pdf, part_number=errata_doc.PART, doc_type="errata", vendor="unknown"
            )
        )
    append_to_inventory(sources, part_dir)
    build_part(
        LM741, part_number=errata_doc.PART, settings=settings,
        vendor="unknown", use_llm=False,
    )
    clear_index_cache()
    return settings, part_dir


@pytest.fixture(scope="module")
def linked(tmp_path_factory) -> tuple[Settings, Path, ErrataLinkSet]:
    """One build of LM741 + errata, shared by the assertions below.

    Module-scoped because the build is the expensive part (a real 17-page PDF
    through the layout floor) and every assertion here reads the *same*
    published corpus — which is also what makes them a gate rather than a set
    of unit tests.
    """
    settings, part_dir = _build(tmp_path_factory.mktemp("errata"), with_errata=True)
    link_set = ErrataLinkSet.model_validate_json(
        (part_dir / ERRATA_LINKS_FILENAME).read_text(encoding="utf-8")
    )
    return settings, part_dir, link_set


class TestPublishedLinks:
    def test_every_item_is_published(self, linked):
        _settings, _part_dir, link_set = linked
        assert link_set.schema_version == ERRATA_SCHEMA_VERSION
        # The count is the criterion: three printed items, three published.
        assert link_set.n_items == len(errata_doc.ITEMS)
        markers = [link.item.marker for link in link_set.all_items()]
        assert sorted(markers) == sorted(marker for marker, _lines in errata_doc.ITEMS)

    def test_declared_targets_are_exactly_what_landed(self, linked):
        """Every hand-read target, and nothing invented beside it."""
        _settings, _part_dir, link_set = linked
        for link in link_set.all_items():
            expected = errata_doc.EXPECTED[link.item.marker]
            found = tuple((t.kind.value, t.id) for t in link.targets)
            assert len(found) == len(expected), (
                f"{link.item.marker}: {[t.id for t in link.targets]}"
            )
            for (kind, ref), (want_kind, want_tail) in zip(found, expected):
                assert kind == want_kind
                assert ref.endswith(want_tail), f"{ref} !~ {want_tail}"

    def test_every_link_records_what_it_matched_on(self, linked):
        """A wrong link must be diagnosable from the file alone."""
        _settings, _part_dir, link_set = linked
        for link in link_set.links:
            for target in link.targets:
                assert target.rule, target
                assert target.matched_on, target
                assert target.confidence.value in {"high", "medium", "low"}
                for tail, rule in errata_doc.EXPECTED_RULES.items():
                    if target.id.endswith(tail):
                        assert target.rule == rule, target
                        break
                else:  # pragma: no cover - guarded by the target test above
                    pytest.fail(f"unexpected target {target.id}")

    def test_verbatim_item_text_is_not_rewritten(self, linked):
        _settings, _part_dir, link_set = linked
        by_marker = {link.item.marker: link.item.text for link in link_set.all_items()}
        for marker, lines in errata_doc.ITEMS:
            for line in lines:
                assert line in by_marker[marker]


class TestUnlinkedItemsSurvive:
    """The worst failure this ticket can produce is a lost erratum."""

    def test_unplaceable_item_is_published_not_dropped(self, linked):
        _settings, _part_dir, link_set = linked
        unlinked = [link.item.marker for link in link_set.unlinked]
        assert unlinked == ["Advisory 2"]
        assert link_set.n_items == len(link_set.links) + len(link_set.unlinked)

    def test_it_appears_under_the_unlinked_heading(self, linked):
        _settings, part_dir, _link_set = linked
        markdown = (part_dir / ERRATA_MARKDOWN_FILENAME).read_text(encoding="utf-8")
        assert UNLINKED_HEADING in markdown
        tail = markdown.split(UNLINKED_HEADING, 1)[1]
        assert "Advisory 2" in tail
        assert "has not yet been characterized" in tail

    def test_the_manifest_records_the_unplaced_population(self, linked):
        _settings, part_dir, _link_set = linked
        manifest = json.loads((part_dir / "manifest.json").read_text(encoding="utf-8"))
        assert manifest["stats"]["n_errata_items"] == len(errata_doc.ITEMS)
        assert manifest["stats"]["n_errata_linked"] == len(errata_doc.ITEMS) - 1
        assert any(
            "could not be linked" in warning
            for warning in manifest["derived_warnings"]
        )


class TestSectionBanners:
    def test_targeted_section_files_carry_a_banner(self, linked):
        _settings, part_dir, link_set = linked
        bannered = 0
        for link in link_set.links:
            for target in link.targets:
                if target.kind.value != "section":
                    continue
                text = (part_dir / target.id).read_text(encoding="utf-8")
                assert BANNER_MARKER in text
                assert link.item.id in text
                assert target.matched_on in text
                # Under the provenance comment, above the body: a reader who
                # opens the section cannot miss it, and the file still opens
                # with its title and its source line.
                assert text.index("<!-- source:") < text.index(BANNER_MARKER)
                bannered += 1
        assert bannered >= 2

    def test_an_untargeted_section_is_untouched(self, linked):
        _settings, part_dir, _link_set = linked
        others = [
            p
            for p in sorted(part_dir.glob("docs/*/sections/*.md"))
            if "6-1-absolute" not in p.name and "7-3-2-latch" not in p.name
        ]
        assert others
        for path in others:
            assert BANNER_MARKER not in path.read_text(encoding="utf-8")


class TestAnswerPackCarriesTheWarning:
    def test_a_targeted_record_answers_with_the_erratum_inline(self, linked):
        """End to end: ask the question the erratum is about."""
        _settings, part_dir, _link_set = linked
        pack = build_pack(
            Retriever.for_part(part_dir), "maximum junction temperature", budget=2000
        )
        assert pack.route == ROUTE_SPEC
        top = pack.answers[0]
        assert top.source.endswith(("specs.json#rec_9", "specs.json#rec_10"))
        assert top.errata, pack.markdown
        assert "err_1" in top.errata[0]
        # The warning is *in the payload*, not merely on the object: a caller
        # that renders the markdown must see it beside the value.
        assert "errata err_1" in pack.markdown

    def test_the_warning_is_in_the_declared_json_shape(self, linked):
        _settings, part_dir, _link_set = linked
        from datasheet_analyzer.retrieve.pack import validate_pack

        pack = build_pack(
            Retriever.for_part(part_dir), "maximum junction temperature", budget=2000
        )
        payload = pack.as_dict()
        assert validate_pack(payload) == []
        assert payload["answers"][0]["errata"]

    def test_a_record_no_erratum_names_carries_no_warning(self, linked):
        _settings, part_dir, _link_set = linked
        pack = build_pack(
            Retriever.for_part(part_dir), "input offset voltage", budget=2000
        )
        assert all(not line.errata for line in pack.answers), pack.markdown


class TestPartWithoutErrataIsUnaffected:
    def test_no_file_no_banner_no_warning(self, tmp_path):
        _settings, part_dir = _build(tmp_path, with_errata=False)
        assert not (part_dir / ERRATA_LINKS_FILENAME).exists()
        assert not (part_dir / ERRATA_MARKDOWN_FILENAME).exists()
        for path in sorted(part_dir.glob("docs/*/sections/*.md")):
            assert BANNER_MARKER not in path.read_text(encoding="utf-8")
        manifest = json.loads((part_dir / "manifest.json").read_text(encoding="utf-8"))
        assert manifest["stats"]["n_errata_items"] == 0
        assert not any("errata" in w for w in manifest["derived_warnings"])

    def test_its_answer_packs_are_unchanged(self, tmp_path):
        _settings, part_dir = _build(tmp_path, with_errata=False)
        pack = build_pack(
            Retriever.for_part(part_dir), "maximum junction temperature", budget=2000
        )
        assert pack.route == ROUTE_SPEC
        assert all(not line.errata for line in pack.answers)
