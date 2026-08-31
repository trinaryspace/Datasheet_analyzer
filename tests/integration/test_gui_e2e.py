"""The workbench, end to end, over one hermetic pass (ticket 22).

Twenty-one tickets each verified their own module against fakes and frozen
signatures. Nothing had yet run the real pieces against each other, and that
is where a contract drifts: an inference the review screen edits, a build that
publishes a shared document once, a chat turn whose citation must survive as
far as a rectangle on a printed page. This file walks that whole path in one
test class, with nothing faked except the two things that would otherwise
leave the machine.

**What is real.** The FastAPI application (`create_app`, every discovered
router), the analyze registry and its background build, the pipeline, the
Library, the shared publish, the retrieval core, the nine agent tools, the
scope resolver, `/api/locate`'s PyMuPDF search, and the session store.

**What is not.** Three synthetic PDFs built with `fitz`, an applicability
classifier that answers from a script, and an Anthropic client that replays a
scripted tool-use exchange through the *real* SDK tool runner — so the loop
under test is the loop that ships and only the transport is fake. No network,
no API key, no browser.

The regressions at the end are the ones this design put at risk, and each
says which invariant it is standing on.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import fitz
import pytest
from anthropic.lib.tools import BetaAsyncStreamingToolRunner
from anthropic.types.beta import BetaMessage
from fastapi.testclient import TestClient
from typing_extensions import Self

from datasheet_analyzer import cli
from datasheet_analyzer.app import deps
from datasheet_analyzer.app.jobs import JobRegistry
from datasheet_analyzer.app.main import create_app
from datasheet_analyzer.app.routers import chat as chat_router
from datasheet_analyzer.app.routers import review as review_router
from datasheet_analyzer.config import PIPELINE_VERSION, Settings, reset_settings_cache
from datasheet_analyzer.extract.pdf_layout import PdfLayoutBackend
from datasheet_analyzer.models import JobState, RawDocument
from datasheet_analyzer.publish import document_dirs, read_manifest

# --- the three synthetic documents --------------------------------------------

PAGE_W, PAGE_H = 612.0, 792.0

#: AD9081-style column left edges, the geometry the layout engine is tuned to.
X = {"param": 56.0, "conditions": 222.0, "min": 435.0, "typ": 460.0, "max": 515.0, "unit": 548.0}
PITCH = 13.0
CAP_Y = 140.0
HDR_Y = 153.0

DATASHEET_PART = "AD9081"
FAMILY_PARTS = ("AFE7950", "AFE7952")

#: A phrase printed on page 1 of the datasheet, in the row `find_spec` finds.
#: Step 7 hands exactly this to `/api/locate` as the needle, which is why it
#: has to be text that is really on the page rather than a paraphrase.
SPEC_NEEDLE = "DAC RESOLUTION"

DEADLINE = 300.0


def _write(
    path: Path, pages: list[list[tuple[float, float, str]]], toc: list[list] | None = None
) -> Path:
    doc = fitz.open()
    for lines in pages:
        page = doc.new_page(width=PAGE_W, height=PAGE_H)
        for x, y, text in lines:
            page.insert_text((x, y), text)
    if toc:
        doc.set_toc(toc)
    doc.save(str(path))
    doc.close()
    return path


def _datasheet(directory: Path) -> Path:
    """A one-part datasheet with a real caption-anchored spec table.

    Page 1 prints "Analog Devices" because `vendor.detect_vendor` pins the
    routing on a brand mark and falls back to `ti`, whose datasheet chain is
    `ti_html` — a network fetch, which a hermetic test must never reach. A
    real ADI datasheet prints exactly this, so nothing here is a test-shaped
    special case.
    """
    page1 = [
        (56.0, 60.0, "Analog Devices AD9081"),  # the brand mark vendor routing pins on
        (56.0, 72.0, "AD9081 Quad RF Sampling Transmitter"),
        (56.0, 90.0, "1 Features"),
        (56.0, 112.0, "Nominal supplies unless otherwise noted."),
        (56.0, CAP_Y, "Table 1. DAC DC Specifications"),
        (X["param"], HDR_Y, "Parameter"),
        (X["conditions"], HDR_Y, "Test Conditions/Comments"),
        (X["min"], HDR_Y, "Min"),
        (X["typ"], HDR_Y, "Typ"),
        (X["max"], HDR_Y, "Max"),
        (X["unit"], HDR_Y, "Unit"),
        (X["param"], HDR_Y + PITCH, SPEC_NEEDLE),
        (X["min"], HDR_Y + PITCH, "16"),
        (X["unit"], HDR_Y + PITCH, "Bit"),
        (X["param"], HDR_Y + 2 * PITCH, "Integral Nonlinearity (INL)"),
        (X["conditions"], HDR_Y + 2 * PITCH, "Shuffling disabled"),
        (X["typ"], HDR_Y + 2 * PITCH, "8.0"),
        (X["unit"], HDR_Y + 2 * PITCH, "LSB"),
    ]
    page2 = [(56.0, 90.0, "2 Applications"), (56.0, 112.0, "Wideband radio transmit chains.")]
    return _write(
        directory / "ad9081_datasheet.pdf",
        [page1, page2],
        toc=[[1, "1 Features", 1], [1, "2 Applications", 2]],
    )


def _register_map(directory: Path) -> Path:
    """A companion the same part owns — a second document, not a second part."""
    return _write(
        directory / "ad9081_register_map.pdf",
        [
            [
                (56.0, 72.0, "AD9081 Register Map"),
                (56.0, 96.0, "0x0000 SPI configuration register, reset value 0x00."),
            ],
            [(56.0, 72.0, "0x0100 DAC page select register, reset value 0x01.")],
        ],
    )


def _app_note(directory: Path) -> Path:
    """One document about two parts — the case containment cannot express."""
    return _write(
        directory / "afe79xx_app_note.pdf",
        [
            [
                (56.0, 72.0, "JESD204C Interface Guide"),
                (56.0, 96.0, "Applies to AFE7950 and AFE7952 transceivers."),
                (56.0, 120.0, "Link initialization is identical on both devices."),
            ],
            [(56.0, 72.0, "Lane mapping is fixed by the SERDES configuration register.")],
        ],
    )


# --- the two scripted stand-ins -----------------------------------------------


class ScriptedClassifier:
    """`enrich.llm.LLMClient` for `acquire.applicability.infer`.

    Reached only when the deterministic sweep finds more than one candidate,
    which here is exactly the app note. It answers with the JSON object
    ticket 02 documented and nothing else.
    """

    model = "scripted-classifier"

    def __init__(self) -> None:
        self.prompts: list[str] = []

    def complete(self, system: str, prompt: str, max_tokens: int) -> str:
        self.prompts.append(prompt)
        return json.dumps(
            {
                "kind": "parts",
                "parts": list(FAMILY_PARTS),
                "family": "",
                "part_number": FAMILY_PARTS[0],
                "reason": "the title block names both transceivers",
            }
        )


def assistant_message(content: list[dict[str, Any]], stop_reason: str) -> BetaMessage:
    """A real `BetaMessage`: the SDK runner inspects it, so it must be real."""
    return BetaMessage.model_validate(
        {
            "id": "msg_e2e",
            "type": "message",
            "role": "assistant",
            "model": "claude-opus-5",
            "content": content,
            "stop_reason": stop_reason,
            "stop_sequence": None,
            "usage": {"input_tokens": 1, "output_tokens": 1},
        }
    )


class FakeStream:
    """One scripted turn: a few stream events, then the final message."""

    def __init__(self, events: list[Any], final: BetaMessage) -> None:
        self.events = events
        self.final = final
        self.closed = False

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc: object) -> bool:
        await self.close()
        return False

    async def __aiter__(self):
        for event in self.events:
            await asyncio.sleep(0)  # a real stream suspends between frames
            yield event

    async def get_final_message(self) -> BetaMessage:
        return self.final

    async def close(self) -> None:
        self.closed = True


class FakeMessages:
    def __init__(self, client: FakeAnthropic, script: list[tuple[list[Any], BetaMessage]]) -> None:
        self._client = client
        self._script = list(script)
        self.requests: list[dict[str, Any]] = []

    def tool_runner(
        self, *, tools: Any, stream: bool = False, max_iterations: int | None = None, **params: Any
    ) -> BetaAsyncStreamingToolRunner:
        assert stream is True, "the chat loop must stream"
        return BetaAsyncStreamingToolRunner(
            params=params,
            options={},
            tools=tools,
            client=self._client,  # type: ignore[arg-type]
            max_iterations=max_iterations,
        )

    def stream(self, **kwargs: Any) -> FakeStream:
        self.requests.append(kwargs)
        assert self._script, "the model was called more times than the script allows"
        events, final = self._script.pop(0)
        return FakeStream(events, final)


class FakeAnthropic:
    """Just enough of `AsyncAnthropic` for the real tool runner to drive."""

    def __init__(self, script: list[tuple[list[Any], BetaMessage]]) -> None:
        self.messages = FakeMessages(self, script)
        self.beta = SimpleNamespace(messages=self.messages)


def find_spec_script(answer: str) -> list[tuple[list[Any], BetaMessage]]:
    """Turn one calls `find_spec`; turn two answers with the value it found."""
    arguments = {"symbol": "", "name": "DAC resolution", "section": ""}
    return [
        (
            [
                SimpleNamespace(type="text", text="Let me look that up. "),
                SimpleNamespace(
                    type="content_block_stop",
                    content_block=SimpleNamespace(
                        type="tool_use", id="toolu_1", name="find_spec", input=arguments
                    ),
                ),
            ],
            assistant_message(
                [
                    {"type": "text", "text": "Let me look that up. "},
                    {
                        "type": "tool_use",
                        "id": "toolu_1",
                        "name": "find_spec",
                        "input": arguments,
                    },
                ],
                "tool_use",
            ),
        ),
        (
            [SimpleNamespace(type="text", text=answer)],
            assistant_message([{"type": "text", "text": answer}], "end_turn"),
        ),
    ]


# --- fixtures -----------------------------------------------------------------


@pytest.fixture(scope="module")
def workspace(tmp_path_factory) -> Path:
    """One tree for the whole walk: the run in step 3 is what step 5 asks."""
    return tmp_path_factory.mktemp("gui-e2e")


@pytest.fixture(scope="module")
def inbox(workspace: Path) -> Path:
    """The directory a user points the analyze screen at."""
    directory = workspace / "inbox"
    directory.mkdir()
    _datasheet(directory)
    _register_map(directory)
    _app_note(directory)
    return directory


#: The environment this module owns. Set for the whole module rather than
#: passed only as an object, because several paths reach for `get_settings()`
#: instead of taking one by argument — `dsa status`, `dsa query`, the scope
#: seam. A test whose two views of "where the corpus is" disagree is a test
#: that passes for the wrong reason.
@pytest.fixture(scope="module", autouse=True)
def environment(workspace: Path):
    """One temporary root for every directory, and provably no API key.

    `ANTHROPIC_API_KEY` is set to the empty string rather than unset: the repo
    keeps a real key in `.env`, `Settings` reads that file, and an environment
    variable is what outranks it. Without this the "hermetic" walk below would
    quietly call a live model for INDEX.md descriptions and for applicability
    classification.
    """
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    monkeypatch.setenv("DSA_PARTS_DIR", str(workspace / "parts"))
    monkeypatch.setenv("DSA_CACHE_DIR", str(workspace / "cache"))
    monkeypatch.setenv("DSA_PROJECTS_DIR", str(workspace / "projects"))
    monkeypatch.setenv("DSA_LIBRARY_DIR", str(workspace / "library"))
    monkeypatch.setenv("DSA_SESSIONS_DIR", str(workspace / "sessions"))
    reset_settings_cache()
    yield
    monkeypatch.undo()
    reset_settings_cache()


@pytest.fixture(autouse=True)
def isolated_library(environment):
    """Shadows the suite-wide per-test isolation for this module only.

    `tests/conftest.py` gives every test its own Library, which is exactly
    right when a test builds its own part and exactly wrong here: this file is
    one *ordered walk*, and repointing `DSA_LIBRARY_DIR` between step 3 and
    step 5 would hand the chat turn an empty shelf.
    """
    yield


@pytest.fixture(scope="module", autouse=True)
def isolated_library_for_module(environment):
    """The module-scoped half of the same shadow, for the same reason."""
    yield


@pytest.fixture(scope="module")
def settings(environment) -> Settings:
    """The resolved settings every step shares — the same ones `dsa` sees."""
    made = Settings().resolve()
    assert not made.llm_available, "this walk must not reach a live model"
    return made


@pytest.fixture(scope="module")
def registry(settings: Settings) -> JobRegistry:
    """The real registry, one worker, so the event sequence is assertable."""
    return JobRegistry(settings=settings, workers=1)


@pytest.fixture(scope="module")
def model() -> FakeAnthropic:
    return FakeAnthropic(find_spec_script("The AD9081 DAC resolution is 16 bits (§1, p.1)."))


@pytest.fixture(scope="module")
def classifier() -> ScriptedClassifier:
    return ScriptedClassifier()


@pytest.fixture(scope="module")
def http(settings, registry, model, classifier, request):
    """The real application, with the two stand-ins injected at their seams."""
    monkeypatch = pytest.MonkeyPatch()
    request.addfinalizer(monkeypatch.undo)
    monkeypatch.setattr(review_router, "_llm_client", lambda _settings: classifier)

    app = create_app(settings)
    app.dependency_overrides[deps.get_settings_dep] = lambda: settings
    app.dependency_overrides[deps.get_job_registry] = lambda: registry
    app.dependency_overrides[chat_router.get_chat_client_factory] = lambda: lambda: model
    with TestClient(app) as client:
        yield client


@pytest.fixture(scope="module")
def walk() -> dict[str, Any]:
    """What each step hands the next: proposals, a run id, a citation."""
    return {}


def sse_frames(body: str) -> list[tuple[str, dict]]:
    """`event:`/`data:` pairs out of an SSE body, ignoring `:` heartbeats."""
    frames: list[tuple[str, dict]] = []
    name = ""
    for line in body.splitlines():
        if line.startswith("event:"):
            name = line.split(":", 1)[1].strip()
        elif line.startswith("data:"):
            frames.append((name, json.loads(line.split(":", 1)[1].strip())))
    return frames


def part_dir(settings: Settings, part: str) -> Path:
    return settings.parts_dir / part


def doc_dirs_of(settings: Settings, part: str) -> dict[str, Path]:
    directory = part_dir(settings, part)
    manifest = read_manifest(directory)
    assert manifest is not None, f"{part} has no manifest"
    return document_dirs(manifest, part_dir=directory)


# --- the eight-step walk ------------------------------------------------------


@pytest.mark.integration
class TestTheWholePath:
    """Ordered on purpose: each step is the previous one's output, verified.

    Split into separate tests rather than one long function so a failure names
    the step that broke instead of the first assertion after it.
    """

    def test_1_the_inbox_holds_the_three_documents(self, inbox: Path):
        assert sorted(p.name for p in inbox.glob("*.pdf")) == [
            "ad9081_datasheet.pdf",
            "ad9081_register_map.pdf",
            "afe79xx_app_note.pdf",
        ]

    def test_2_scan_proposes_one_row_per_pdf_with_the_right_parts(
        self, http, inbox: Path, walk, classifier
    ):
        response = http.post("/api/analyze/scan", json={"directory": str(inbox)})
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["count"] == 3
        by_file = {p["filename"]: p for p in payload["proposals"]}
        walk["proposals"] = by_file

        datasheet = by_file["ad9081_datasheet.pdf"]
        assert datasheet["part_number"] == DATASHEET_PART
        assert datasheet["applicability"]["kind"] == "parts"
        assert datasheet["applicability"]["parts"] == [DATASHEET_PART]
        assert datasheet["evidence"], "an inference that cannot say why is not correctable"

        register = by_file["ad9081_register_map.pdf"]
        assert register["part_number"] == DATASHEET_PART

        note = by_file["afe79xx_app_note.pdf"]
        # The sweep found two candidates, so the classifier was asked; it said
        # both. Either shape ticket 04 allows — several parts, or a family —
        # would satisfy the design, and this run produced the multi-part one.
        assert note["applicability"]["kind"] in {"parts", "family"}
        assert set(note["applicability"]["parts"]) == set(FAMILY_PARTS)
        assert classifier.prompts, "the multi-part note must reach the classifier"

    def test_2b_the_scan_wrote_nothing(self, settings: Settings):
        """A scan is a proposal: it may not build, publish or register."""
        assert not settings.parts_dir.exists() or not list(settings.parts_dir.iterdir())
        assert not settings.library_dir.exists() or not list(settings.library_dir.glob("*.json"))

    def test_3_start_builds_every_confirmed_proposal(self, http, inbox, walk, registry):
        """The review screen's confirmed rows, used verbatim.

        Four rows, not three: the app note applies to two parts, and nothing
        in the design materializes a part that only a widened applicability
        names — a corpus exists because a job built it. Adding the second row
        is what a user does on the review screen, and it is the *only* way
        `AFE7952` comes into existence.
        """
        proposals = list(walk["proposals"].values())
        note = dict(walk["proposals"]["afe79xx_app_note.pdf"])
        second = dict(note)
        second["part_number"] = FAMILY_PARTS[1]
        proposals.append(second)

        response = http.post(
            "/api/analyze/start", json={"directory": str(inbox), "proposals": proposals}
        )
        assert response.status_code == 202, response.text
        started = response.json()
        assert started["n_jobs"] == 4
        run_id = started["run_id"]
        walk["run_id"] = run_id

        assert registry.wait(run_id, timeout=DEADLINE), "the run did not finish"
        snapshot = registry.snapshot(run_id)
        assert snapshot.done is True
        assert [job.state for job in snapshot.jobs] == [JobState.DONE] * 4, [
            (job.part_number, job.state, job.error) for job in snapshot.jobs
        ]

        # Every job walks the pipeline's own stage vocabulary, in order.
        for job in snapshot.jobs:
            states = [e.state for e in registry.history(run_id) if e.job_id == job.id]
            assert states == [
                JobState.QUEUED,
                JobState.EXTRACTING,
                JobState.STRUCTURING,
                JobState.ENRICHING,
                JobState.PUBLISHING,
                JobState.DONE,
            ], (job.part_number, states)

    def test_3b_the_stream_opens_with_a_snapshot_and_closes_with_an_end(self, http, walk):
        """A client attaching to a finished run is told everything, then ends."""
        response = http.get(f"/api/analyze/{walk['run_id']}/events")
        assert response.status_code == 200
        frames = sse_frames(response.text)
        assert [name for name, _ in frames] == ["snapshot", "end"]
        assert frames[-1][1]["done"] is True
        assert len(frames[-1][1]["jobs"]) == 4

    def test_3c_an_unknown_run_is_a_404_not_an_empty_stream(self, http):
        assert http.get("/api/analyze/no-such-run/events").status_code == 404

    def test_4_the_app_note_is_published_once_and_referenced_by_both_parts(
        self, settings: Settings, walk
    ):
        first = doc_dirs_of(settings, FAMILY_PARTS[0])
        second = doc_dirs_of(settings, FAMILY_PARTS[1])
        assert len(first) == len(second) == 1
        (hash_a, dir_a), (hash_b, dir_b) = first.popitem(), second.popitem()

        assert hash_a == hash_b, "both parts must reference one document identity"
        assert dir_a.resolve() == dir_b.resolve(), "and one directory on disk"
        assert dir_a.is_dir()
        # Published *once*: the artifacts live in the shared store, not under
        # either part. Forty parts sharing a note must not mean forty copies.
        shared = settings.library_dir / "docs"
        assert dir_a.resolve().parent == shared.resolve()
        for part in FAMILY_PARTS:
            local = part_dir(settings, part) / "docs"
            assert not local.exists() or not list(local.iterdir())
        walk["note_hash"] = hash_a

    def test_4b_afe7952_is_a_part_whose_corpus_is_only_the_app_note(self, settings: Settings, walk):
        manifest = read_manifest(part_dir(settings, FAMILY_PARTS[1]))
        assert manifest is not None
        assert manifest.part_number == FAMILY_PARTS[1]
        assert [d.content_hash for d in manifest.documents] == [walk["note_hash"]]
        assert manifest.documents[0].doc_type.value == "app_note"
        assert manifest.sections, "the note's sections must be published"

    def test_4c_ad9081_holds_its_own_two_documents_and_not_the_note(self, settings: Settings, walk):
        manifest = read_manifest(part_dir(settings, DATASHEET_PART))
        assert manifest is not None
        hashes = {d.content_hash for d in manifest.documents}
        assert len(hashes) == 2
        assert walk["note_hash"] not in hashes
        assert {d.doc_type.value for d in manifest.documents} == {
            "datasheet",
            "register_map",
        }

    def test_4d_the_library_reports_the_note_reaching_both_parts(self, http, walk):
        response = http.get("/api/library")
        assert response.status_code == 200, response.text
        documents = {d["content_hash"]: d for d in response.json()["documents"]}
        note = documents[walk["note_hash"]]
        assert set(note["parts_reached"]) >= set(FAMILY_PARTS)
        assert note["rebuild_needed"] == [], note["rebuild_needed"]

    def test_5_a_question_naming_a_part_resolves_confidently(self, http, walk):
        response = http.post(
            "/api/chat/resolve-scope",
            json={"question": f"what is the DAC resolution of the {DATASHEET_PART}?"},
        )
        assert response.status_code == 200, response.text
        resolution = response.json()
        assert resolution["confident"] is True
        assert resolution["scope"] == {"kind": "part", "name": DATASHEET_PART}
        walk["scope"] = resolution["scope"]

    def test_6_the_turn_streams_a_citation_that_came_from_a_real_tool_result(
        self, http, walk, model, settings
    ):
        created = http.post("/api/sessions", json={"title": "DAC resolution"})
        assert created.status_code == 200, created.text
        session_id = created.json()["id"]
        walk["session_id"] = session_id

        response = http.post(
            f"/api/chat/{session_id}/message",
            json={
                "question": f"what is the DAC resolution of the {DATASHEET_PART}?",
                "scope": walk["scope"],
            },
        )
        assert response.status_code == 200, response.text
        frames = sse_frames(response.text)
        names = [name for name, _ in frames]

        assert names[0] == "scope"
        assert names[-1] == "done", frames[-1]
        assert "tool" in names and "citation" in names and "token" in names
        assert names.index("tool") < names.index("done")
        assert [name for name, _ in frames if name == "error"] == []

        tool_frame = next(data for name, data in frames if name == "tool")
        assert tool_frame["tool"] == "find_spec"

        citation = next(data for name, data in frames if name == "citation")["citation"]
        # Real, because the tool ran against the built corpus: the page and
        # the document identity are the manifest's, not the model's.
        manifest = read_manifest(part_dir(settings, DATASHEET_PART))
        assert manifest is not None
        assert citation["doc_hash"] in {d.content_hash for d in manifest.documents}
        assert citation["part"] == DATASHEET_PART
        assert citation["page_start"] == 1
        assert citation["label"], "a citation without a label cannot be rendered"
        walk["citation"] = citation

        answered = "".join(data["text"] for name, data in frames if name == "token")
        assert "16 bits" in answered
        assert len(model.messages.requests) == 2, "one tool turn, then the answer"

    def test_7_locate_puts_a_rectangle_on_the_cited_page(self, http, walk):
        citation = walk["citation"]
        response = http.get(
            "/api/locate",
            params={
                "part": citation["part"],
                "doc_hash": citation["doc_hash"],
                "page": citation["page_start"],
                "needle": SPEC_NEEDLE,
            },
        )
        assert response.status_code == 200, response.text
        located = response.json()
        assert located["found"] is True, located["reason"]
        assert located["page"] == citation["page_start"]
        assert located["rects"], "a found citation must carry at least one rect"
        rect = located["rects"][0]
        assert 0 <= rect["x0"] < rect["x1"] <= located["page_width"]
        assert 0 <= rect["y0"] < rect["y1"] <= located["page_height"]

    def test_7b_a_needle_that_is_not_there_is_an_honest_miss(self, http, walk):
        citation = walk["citation"]
        response = http.get(
            "/api/locate",
            params={
                "part": citation["part"],
                "doc_hash": citation["doc_hash"],
                "page": citation["page_start"],
                "needle": "a phrase this datasheet does not print anywhere",
            },
        )
        assert response.status_code == 200
        located = response.json()
        assert located["found"] is False and located["rects"] == []
        assert located["reason"], "a miss must say why, so a viewer can report it"

    def test_8_the_session_exports_in_both_formats(self, http, walk):
        session_id = walk["session_id"]
        saved = http.get(f"/api/sessions/{session_id}")
        assert saved.status_code == 200, saved.text
        assert saved.json()["n_messages"] == 2, "the exchange must have been persisted"

        markdown = http.get(f"/api/sessions/{session_id}/export", params={"format": "markdown"})
        assert markdown.status_code == 200, markdown.text
        assert markdown.headers["content-type"].startswith("text/markdown")
        assert "16 bits" in markdown.text
        assert DATASHEET_PART in markdown.text

        golden = http.get(f"/api/sessions/{session_id}/export", params={"format": "golden"})
        assert golden.status_code == 200, golden.text
        assert golden.headers["content-type"].startswith("text/yaml")
        # It must be loadable as the fixture it claims to be.
        import yaml

        parsed = yaml.safe_load(golden.text)
        assert parsed, "a golden export must not be empty after a real exchange"


# --- the regressions this design put at risk ----------------------------------


@pytest.mark.integration
class TestTheInvariantsThisDesignPutAtRisk:
    def test_a_cached_raw_document_still_deserializes(self, settings: Settings):
        """If this fails, `SourceDocument` changed shape and the cache is void.

        The extraction cache is the most expensive thing this project owns: a
        real datasheet is minutes of work per document, keyed
        `(content_hash, backend)`. The build in step 3 wrote real entries;
        every one of them must still load as a `RawDocument`.
        """
        cached = sorted((settings.cache_dir / "extract").glob("*.json"))
        assert cached, "the run above must have written extraction cache entries"
        for path in cached:
            raw = RawDocument.model_validate_json(path.read_text(encoding="utf-8"))
            assert raw.source.content_hash
            assert raw.extractor

    def test_the_layout_backend_output_version_is_unchanged(self):
        """`output_version` is the extraction cache's key half.

        Bumping it silently invalidates every cached extraction on every
        machine, so it moves only when the backend's *output* really changed —
        never as a side effect of a GUI ticket. The value on this tree is
        `tables-08` (the ticket text quotes `tables-07`, which the layout
        ladder had already moved past before this wave began); what is pinned
        here is that no GUI ticket touched it.
        """
        assert PdfLayoutBackend.output_version == "tables-08"

    def test_the_pipeline_version_is_unchanged(self):
        assert PIPELINE_VERSION == "0.5.0"

    @pytest.mark.parametrize(
        "verb",
        ["build", "batch", "query", "plots", "status", "verify", "serve", "project"],
    )
    def test_every_cli_subcommand_is_still_wired(self, verb, capsys):
        """The CLI is not the workbench's junior partner — it must still run.

        `--help` per verb proves the parser and the handler binding without
        running a build; each verb's real behaviour is covered against real
        corpora in the phase-2/3/4 suites, which this file does not duplicate.
        """
        with pytest.raises(SystemExit) as exit_info:
            cli.main([verb, "--help"])
        assert exit_info.value.code == 0
        assert verb in capsys.readouterr().out

    def test_dsa_status_reads_the_corpora_this_run_built(self, settings, capsys):
        """`dsa status` reads `sources.json`, which is now derived (ADR 0005)."""
        assert cli.main(["status"]) == 0
        printed = capsys.readouterr().out
        for part in (DATASHEET_PART, *FAMILY_PARTS):
            assert part in printed

    def test_dsa_query_answers_from_the_built_corpus(self, settings, capsys):
        assert cli.main(["query", "--part", DATASHEET_PART, "--name", "DAC resolution"]) == 0
        assert "16" in capsys.readouterr().out

    def test_serve_mcp_is_still_reachable_without_starting_a_server(self, monkeypatch):
        """`dsa serve --mcp` still routes to the MCP transport, and only it.

        The runner is faked: the point is the wiring, and a real
        `serve_stdio()` would block the suite forever.
        """
        started: list[Settings] = []
        monkeypatch.setattr(
            "datasheet_analyzer.mcp_server.serve_stdio",
            lambda settings: started.append(settings),
        )
        assert cli.main(["serve", "--mcp"]) == 0
        assert len(started) == 1
