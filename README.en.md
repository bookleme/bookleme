<p align="center">
  <img src="docs/assets/bookleme-banner.png" alt="BookLeme — From Books to Skills" width="100%">
</p>

<h1 align="center">BookLeme · 读了么</h1>

<p align="center">
  <a href="README.md">简体中文</a> ·
  <a href="README.en.md"><strong>English</strong></a>
</p>

<p align="center">
  <strong>Compile a book into installable agent skills — from "having read it" to "knowing how to do it".</strong>
</p>

<p align="center">
  <a href="https://github.com/bookleme/bookleme/actions/workflows/ci.yml"><img src="https://img.shields.io/github/actions/workflow/status/bookleme/bookleme/ci.yml?style=for-the-badge&label=CI&color=brightgreen" alt="CI"></a>
  <img src="https://img.shields.io/badge/License-MIT-blue?style=for-the-badge" alt="MIT License">
  <img src="https://img.shields.io/badge/Python-3.9%2B-blue?style=for-the-badge&logo=python&logoColor=white" alt="Python 3.9+">
  <img src="https://img.shields.io/badge/runtime-zero%20third--party%20deps-brightgreen?style=for-the-badge" alt="Zero deps">
  <img src="https://img.shields.io/badge/formats-PDF%20%C2%B7%20EPUB%20%C2%B7%20DOCX%20%C2%B7%20MD%20%C2%B7%20HTML%20%C2%B7%20RTF%20%C2%B7%20MOBI-green?style=for-the-badge" alt="Formats">
</p>

<p align="center">
  <a href="#why">Why</a> ·
  <a href="#what">What it generates</a> ·
  <a href="#engines">Dual engine</a> ·
  <a href="#fidelity">Fidelity</a> ·
  <a href="#quickstart">Quick start</a> ·
  <a href="#arch">Architecture</a> ·
  <a href="#compare">Comparison</a> ·
  <a href="#roadmap">Roadmap</a> ·
  <a href="#docs">Docs</a>
</p>

---

<a id="why"></a>

## Why

Models are already smart enough. What's scarce is **real human working experience**.

And the most valuable thing in a book is never the conclusion — it's the author's **way of working**:

| Book | What actually matters |
|---|---|
| *Designing Your Life* | Not the life answers, but that **sequence of questions** — which draws out the reader's own answers |
| *Penetrating Financial Reports* | Not industry conclusions, but **decision criteria + evidence rules + falsification conditions** |

The problem: after reading, these "ways of working" are scattered across 300 pages — they can't be invoked, reused, or verified.

**BookLeme compiles them into runnable agent skills.**

<p align="center">
  <img src="docs/assets/bookleme-witch-study.png" alt="Compile knowledge into skills" width="72%">
</p>

<details>
<summary><b>Three design principles</b> (adopted as engineering practice, not claimed as verified)</summary>

1. **Compile-time / run-time separation** — read the book once at compile time; load knowledge slices on demand at run time
2. **Three-level progressive disclosure** — always-loaded entry → on-demand slices → local full text
3. **Decouple deterministic extraction from probabilistic generation** — unit-testable, diffable, regression-safe

> "Distilling structure rather than summarising" is a design choice, not a verified conclusion. This project marks it `UNVERIFIED` rather than stating it as fact.

</details>

---

<a id="what"></a>

## What it generates

Not reading notes — **two kinds of installable, invokable, verifiable artifacts**:

<p align="center">
  <img src="docs/assets/bookleme-witch-library.png" alt="Dual-engine artifacts" width="62%">
</p>

<table>
<tr><th></th><th>📚 Knowledge pack · <code>knowledge_pack</code></th><th>⚡ Behavior skill · <code>behavior_skill</code></th></tr>
<tr><td><b>Shape</b></td><td>A queryable, structured knowledge base</td><td>A running flow with a state machine</td></tr>
<tr><td><b>Contains</b></td><td>Topic Index router + on-demand framework slices + decision cheatsheet + provenance list</td><td>Role + hard constraints + state machine + named output contract + anti-patterns + emotional guardrails</td></tr>
<tr><td><b>Typical use</b></td><td>"How do I use framework X from this book?"</td><td>"Walk me through a full design-your-life conversation."</td></tr>
<tr><td><b>Example</b></td><td><code>examples/reference/</code> (11 files)</td><td><code>examples/coach/</code> (14 files)</td></tr>
</table>

**Core capabilities**

- 🎛 **Dual-engine auto-routing** — decided by 12 deterministic genre features, or overridden manually; both engines share one intermediate representation, so a book is never read twice
- 🧩 **Pluggable genre plugins** — a new genre is one file (schema / state machine / output contract / anti-patterns); zero core changes
- 🔍 **Verbatim fidelity verification** — every quote must be an exact substring of the source; 7 metrics split into `measured` / `heuristic`
- 🛡 **Copyright engineering** — 6 deterministic hard gates + provenance manifest + private-by-default, preventing any verbatim reproduction
- ⚙️ **Zero third-party dependencies** — the core uses only the Python standard library
- 🔁 **Stage-level idempotency** — sha256 checkpoint resume; delete any stage output and only that stage recomputes

---

<a id="engines"></a>

## Dual engine · pluggable genres

A **genre plugin** determines what a book becomes. Four built in:

| Plugin | Genre | Status | Key design |
|---|---|---|---|
| `coach_dialogue` | Coaching / self-dialogue | ✅ Shipped | One-question-per-turn state machine, verdict owned by the user, emotional guardrails, resumable |
| `knowledge_reference` | Framework lookup | ✅ Shipped | Topic Index routing, on-demand loading, must refuse when "the book doesn't say" |
| `professional_analysis` | Professional analysis pipeline | 🔜 M4 | Evidence binding, reconciliation table, **falsification condition required per conclusion** |
| `decision_checklist` | Decision checklist | 🔜 M4 | Thresholds / trade-off matrix / decision tree / not-applicable bounds |

> Adding a genre = writing one file at `bookleme/plugins/user/<genre_id>.py`. Field contract: [docs/PLUGIN_SPEC.md](docs/PLUGIN_SPEC.md).

**Mandatory plugin declarations** (missing any → load rejected): `state_machine`, `output_contract`, `hard_constraints`, `anti_patterns`, `voice_calibration` (tone / address form / forbidden phrases / **verdict ownership**), `copyright_profile`, `trigger_words` (3–5 Chinese triggers), `eval_prompts` (must include ≥1 negative case).

---

<a id="fidelity"></a>

## Fidelity & copyright

Upstream projects market "no hallucination" without automated verification. **We split "zero hallucination" into 7 measurable metrics:**

| Metric | Type | Target | This batch |
|---|---|---|---|
| `citation_resolution_rate` | measured | 1.00 | ✅ 1.00 |
| `verbatim_violation_rate` | measured | 0.00 | ✅ 0.00 |
| `negative_refusal_rate` | measured | 1.00 | ✅ 1.00 |
| `trigger_hit_rate` | measured | ≥0.90 | ✅ 1.00 |
| `artifact_compliance_rate` | measured | 1.00 | ✅ 1.00 |
| `shingle_overlap_max` | measured | ≤0.10 | ✅ 0.084 |
| `coverage_score` | measured | ≥0.85 | ⚠️ **0.667 (below target, reported honestly)** |
| `groundedness` | heuristic | report-only | `null` (LLM judge not wired) |

**6 copyright hard gates** (any failure → no install, no publish): single quote ≤150 chars and verbatim-traceable · total quote ratio ≤0.03 · max contiguous copy ≤150 chars · 13-char shingle overlap ≤0.10 · artifact contains no full text / slices · `contains_original_text = false`.

**Copyright boundary**: output is **structured derivative notes — no source paragraphs**. Skills generated from third-party books default to private and may not be redistributed; publishing requires an explicit `--public --confirm-public PUBLISH` at launch. MIT covers the converter only, never any book. See [docs/COPYRIGHT.md](docs/COPYRIGHT.md).

---

<a id="quickstart"></a>

## Quick start

```bash
git clone https://github.com/bookleme/bookleme.git
cd bookleme

# Zero third-party dependencies; Python ≥ 3.9 is enough
python3 -m bookleme --version

# End to end: book → skill
python3 -m bookleme run --input evals/cases/synthetic/coach_book.md --title "My First Book"

# Validate artifacts (official validator + own lint + copyright gates)
python3 -m bookleme validate examples/coach

# Regression tests
python3 -m unittest discover -s tests -v
```

**Common flags**

```bash
--engine auto|knowledge_pack|behavior_skill|both   # engine selection
--genre <plugin_id>                                # force a genre
--no-router                                        # disable routing, emit both engines
--install                                          # install into the skill source of truth (off by default)
--user-rights owned|licensed|public_domain|unknown # usage-rights declaration
--public --confirm-public PUBLISH                  # public distribution (bare-word confirmation)
```

---

<a id="arch"></a>

## Architecture · S0–S9 compile pipeline

```
S0 Intake ─► S1 Deterministic extraction ─► S2 Chinese segmentation ─┬─► S3 Genre routing ──────┐
                                                                     └─► S4 Capability extract ─┼─► S5 Fidelity
                                                                           (shared IR)        ┘
                                                                                                     │
                              S9 Smoke eval ◄─ S8 Install ◄─ S7 Validation ◄─ S6 Dual-engine render ◄─┘
```

**Key design**: S3 and S4 run in parallel from S2; both engines share S1/S2/S4/S5 entirely — **only S6 diverges**, so a book is never read twice.

| Layer | Responsibility | Executor |
|---|---|---|
| S0–S2 | Extraction, normalisation, Chinese segmentation (no "Chapter N" dependency) | Deterministic Python |
| S3 | 12-feature genre routing + ambiguity fallback (auto dual-engine, never stalls) | Deterministic + pluggable LLM |
| S4 | Atomic capability extraction (RIA++ six fields) | Deterministic extractor (LLM extractor is an interface placeholder) |
| S5 | Verbatim quote verification + claim ledger + 7 metrics | Deterministic + judge placeholder |
| S6 | Plugin-driven rendering (stdlib string templates) | Deterministic Python |
| S7–S9 | Four-way validation, idempotent install, smoke evaluation | Deterministic Python |

Details: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)

---

<a id="compare"></a>

## Comparison

<table>
<tr><th></th><th><b>BookLeme</b></th><th><code>virgiliojr94/book-to-skill</code></th><th><code>bookforge-ai/bookforge-skills</code></th></tr>
<tr><td><b>Positioning</b></td><td>A <b>compiler toolchain</b> book → skill</td><td>Book → knowledge pack (executed by the host agent)</td><td>A <b>artifact library</b> of pre-distilled skills</td></tr>
<tr><td><b>Artifacts</b></td><td>Knowledge pack <b>plus</b> runnable behavior skill</td><td>Knowledge pack only</td><td>Skills file collection</td></tr>
<tr><td><b>Generator</b></td><td>Coded stage DAG, unit-testable / diffable</td><td>One large SKILL.md operating procedure</td><td>—</td></tr>
<tr><td><b>Fidelity</b></td><td>7 metrics + verbatim quote verification + negative refusal</td><td>No automated verification</td><td>—</td></tr>
<tr><td><b>Genres</b></td><td>Pluggable plugins; one file per new genre</td><td>Fixed 5 files + 10-section template</td><td>—</td></tr>
<tr><td><b>Copyright</b></td><td>6 deterministic hard gates + private by default</td><td>Prompt rules + self-discipline</td><td>CC-BY-SA-4.0</td></tr>
<tr><td><b>License</b></td><td>MIT</td><td>MIT</td><td>CC-BY-SA-4.0</td></tr>
</table>

> Built from scratch after auditing `book-to-skill`; **no upstream code or template was imported**. No affiliation with `bookforge-ai`, nothing of theirs is used. Point-by-point differences: [docs/decisions/ADR-001-research-convergence.md](docs/decisions/ADR-001-research-convergence.md).

---

<a id="roadmap"></a>

## Roadmap

- ✅ **M0–M3** Research alignment · design freeze · core engine · first plugins & artifacts (**current**)
- 🔜 **M4** `professional_analysis` / `decision_checklist` plugins, 4-section synthetic eval set, two-book dogfood, LLM judge wiring
- 🔜 **M5** Skill source-of-truth install, real numbers in `evals/baseline.json`, cross-book capability merge

**Honest scope notes** (this project does not overstate): S4 is currently a deterministic extractor; the LLM judge is not wired (`groundedness` / V2 / V3 are `null`); `coverage_score` is 0.667 against a 0.85 target; `professional_analysis` and `decision_checklist` remain in M4.

---

<a id="docs"></a>

## Documentation

| Doc | Contents |
|---|---|
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | S0–S9 pipeline, idempotency model, shared IR, observability |
| [docs/PLUGIN_SPEC.md](docs/PLUGIN_SPEC.md) | 16 required plugin fields, 4 built-in skeletons, loading & safety scan |
| [docs/FIDELITY.md](docs/FIDELITY.md) | 7 metrics, verbatim verification, V1/V2/V3, unverified-assumption table |
| [docs/COPYRIGHT.md](docs/COPYRIGHT.md) | Mixed inputs, provenance, 6 gates, distribution decisions |
| [docs/EVALS.md](docs/EVALS.md) | Eval set design, 22-item hard acceptance list, smoke tests |
| [docs/ACCEPTANCE-M0-M3.md](docs/ACCEPTANCE-M0-M3.md) | Item-by-item acceptance record and measured numbers |
| [docs/UPSTREAM_AUDIT.md](docs/UPSTREAM_AUDIT.md) | Line-by-line upstream source audit notes |
| [docs/decisions/](docs/decisions/) | ADR-001 convergence · ADR-002 dual engine · ADR-003 fidelity metrics |

---

## Contributing

Issues and PRs are welcome. Before submitting, run:

```bash
python3 -m unittest discover -s tests -v
python3 -m bookleme schema --state
python3 -m bookleme plugin validate bookleme/plugins/builtin/coach_dialogue.py
```

**Hard rules**: never commit book text / covers / scans; never import upstream repository code; never write an unverified assumption as established fact. See [CONTRIBUTING.md](CONTRIBUTING.md).

---

## License

[MIT](LICENSE) © 2026 BookLeme contributors

MIT covers the converter (code + skill definitions) only — **not any book or document processed with this tool**. See [NOTICE.md](NOTICE.md).

<p align="center">
  <sub>📖 BookLeme — have you read it? Once you have, it becomes your skill.</sub>
</p>
