# Phase 2 Report — `specs.json`: the Verified Structured Part Model

**Status: complete. 172/172 tests passing, ruff clean, golden Q&A 16/16, spec-query verification 8/8 original + 4 new questions passing.**

Phase 2 turns the 11 real parametric tables extracted in Phase 1 into a
deterministic, machine-queryable `specs.json`, plus a `dsa query` interface.
Parametric questions now resolve to a **~2.5k-token lookup** (INDEX.md + answer)
instead of a **~4–8k section read**.

## Reproduce

```powershell
uv venv --python 3.10 .venv
uv pip install --python .venv/Scripts/python.exe -e ".[dev]"
.venv/Scripts/dsa.exe build afe7950.pdf --part AFE7950              # writes specs.json
.venv/Scripts/dsa.exe verify --part AFE7950 --pdf afe7950.pdf --specs # Phase 2 checks
.venv/Scripts/dsa.exe query --part AFE7950 --symbol DACRES          # deterministic lookup
.venv/Scripts/python.exe -m pytest tests/ -q
.venv/Scripts/python.exe -m ruff check src tests
```

The build above runs **deterministic** (no `ANTHROPIC_API_KEY`) and uses only
the recorded TI fixtures plus the local PDF — no live network in tests.

## Results

### Corpus stats (from manifest.json)

| Metric | Value |
|---|---|---|
| Sections | 39 |
| Tables | 15 (11 parametric + 1 info + 3 unmapped figure-furniture tables) |
| Figures | ≥514 (Phase 1 catalog) |
| Footnotes | 20, **0 orphans** |
| **Spec records** | **619** |
| Spec table classification | 11 `parametric`, 1 `info`, 3 `unmapped` |
| Unmapped headers | **0** |
| INDEX.md tokens | 2,460 / 3,000 budget |

### `specs.json` coverage

Every extracted table was classified and normalized:

- 4.1 Absolute Maximum Ratings → parametric
- 4.2 ESD Ratings → parametric
- 4.3 Recommended Operating Conditions → parametric
- 4.4 Thermal Information → parametric
- 4.5 Transmitter Electrical Characteristics → parametric
- 4.6 RF ADC Electrical Characteristics → parametric
- 4.7 PLL/VCO/Clock Electrical Characteristics → parametric
- 4.8 Digital Electrical Characteristics → parametric
- 4.9 Power Supply Electrical Characteristics → parametric
- 4.10 Timing Requirements → parametric
- 4.11 Switching Characteristics → parametric
- 3 Description (package table) → info
- 4.12.7 figure-furniture tables → unmapped (empty headers, no numeric data)

All 619 records validate against the `SpecSet` Pydantic model, and every
record's `page` is either `None` or inside its owning section's manifest page
range.

### Golden Q&A verification

| Mode | Result |
|---|---|
| Direct corpus + page-truth | **16/16** |
| Spec-query (`--specs`) | **8/8 original + 4 new = 12/12** |

The 8 original questions now answerable via `dsa query`:

1. DAC resolution (`symbol: DACRES`) → 14 bits, p.7
2. TX DSA range + analog step (`section: 4.5, name: Attenuation`) → 40 dB + 1.0 dB, p.7
3. DSA step accuracy after calibration (`name: step accuracy, section: 4.5`) → ±0.1 dB, p.7
5. Min SCLK period (`name: SCLK, section: 4.10`) → 25 ns, p.27
6. Junction-to-ambient thermal resistance (`name: Junction-to-ambient, section: 4.4`) → 16.2 °C/W, p.6
7. VCO coverage (`section: 4.7, name: VCO`) → 7.2–12.08 GHz, p.18
8. Peak RF input @830 MHz (`name: peak differential RF input, section: 4.1`) → 16.7 dBm, p.4
9. SYSREF setup/hold (`name: SYSREF, section: 4.10`) → 50 ps, p.27

The 4 new spec-only questions:

- q13: min 1.2V rail → 1.15 V, §4.3, p.6
- q14: PFD frequency range → 100–500 MHz, §4.7, p.18
- q15: SerDes output rise/fall time → 8 ps, §4.8, p.20
- q16: ESD Human Body Model rating → 1000 V, §4.2, p.5

### Token economics

| Strategy | Tokens/question |
|---|---|
| Naive full-corpus dump | ~46k |
| Phase 1 (INDEX.md + one section) | 4,256 avg / 8,402 worst |
| **Phase 2 spec lookup (INDEX.md + answer)** | **~2,475–2,564** (2,460 INDEX + 15–104 answer) |

**~18× cheaper than the full dump, ~1.7× cheaper than Phase 1's best section path**
for known parametric questions.

## Test infrastructure — 172 tests, mapped to pain points

| Pain point | Tests | Proof |
|---|---|---|
| Header roles mis-assigned / tables mis-classified | 7 `test_roles.py` + integration | 11 parametric + 1 info, 0 unmapped headers |
| Units canonicalized incorrectly / corpus mangled | 46 `test_units.py` | U+2126/U+03A9 → ohm; known vocabulary pinned; unknown units reported |
| Spec row values/page/footnotes lost | 9 `test_specs.py` | exact DACRES/ATTstep values, per-row cited markers, page fallback |
| Query semantics wrong | 5 `test_query.py` | AND/case-insensitive/multi-doc load |
| Phase 2 breaks Phase 1 | integration suite | 16/16 golden Q&A still pass |

## Acceptance criteria

- [x] `dsa build` writes `specs.json`; printed summary shows `619 spec records`
- [x] `dsa query --part AFE7950 --symbol DACRES` prints `DAC resolution (DACRES): 14 bits — §4.5, p.7 ...`
- [x] ≥8/12 original golden questions pass `--specs` mode; 16/16 overall
- [x] 11 parametric + 1 info tables, **0 unmapped headers**
- [x] 100% records validate; every record page ∈ its section range or `None`
- [x] `pytest` (172 tests) + `ruff` green; integration build green
- [x] Tokens per spec answer measured: ~2.5k incl. INDEX.md

## What changed in the architecture

- `models.py`: added `SpecUnit`, `SpecRecord`, `SpecTableInfo`, `SpecSet`, and
  `GoldenQuestion.spec_query`; `CorpusStats.n_specs`.
- `config.py`: added `SPECS_SCHEMA_VERSION = "1"`.
- `structure/roles.py`, `structure/units.py`, `structure/specs.py`: new
  deterministic transform modules.
- `query.py`: new deterministic lookup module.
- `publish/writer.py`: writes `docs/<doc>/specs.json` when a `SpecSet` is
  supplied; sets `stats.n_specs`.
- `pipeline.py`: builds `SpecSet` on every build (no separate cache — the
  transform is fast and deterministic).
- `cli.py`: `dsa query` command; `dsa verify --specs` flag.
- `tests/fixtures/golden_qa.yaml`: added `spec_query` blocks to 8 existing
  questions and 4 new spec-only questions.
- `AGENTS.md`: updated module table, commands, and corpus layout.

## Explicitly out of scope (kept out)

- Float parsing / numeric comparison of values (verbatim strings only).
- LLM normalization of parameter names.
- Cross-part comparison, fleet manifest, MCP.
- specs from any future `pdf_text` backend.
