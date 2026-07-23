---
name: text-knowledge-reader
description: Build auditable long-text knowledge projects with strict source identity, contamination isolation, exact Evidence Units, multi-file chapter catalogs, focused event causality, scoped character modeling, A/B/C epistemic separation, evidence-first queries, and Notion-ready exports. Use for novels, historical corpora, technical documents, notes, and other long text where source traceability and refusal are required.
---

# Text Knowledge Reader

**Development version:** 6.0.0-alpha1  
**Historical release:** 5.9.0 at `archive/v5.9.0-final`  
**Current development:** Stage 1 Evidence Engine, Stage 2 Chapter Structure Engine, and Stage 3 Event Causality Engine integrated; Stage 4 Focused Character Engine under final integration  
**Authority:** no v6 final acceptance, release, or freeze

## Purpose

Use this Skill to convert uploaded long text into a source-bound, reviewable knowledge system without silently repairing, deleting, renumbering, reordering, or inventing source content.

The v6 system has seven compatible project layers:

1. **Base source project** — strict decoding, source identity, anomaly isolation, Unit structure, deterministic fact predicates, entity normalization, retrieval, citations, and refusal.
2. **Chapter Project** — one or more verified source projects mapped into immutable physical chapter order plus a separate reviewable canonical-order candidate.
3. **Literary sidecar** — A/B/C assertions, selected entities, temporal relationships, reviewed literary events, revisions, and evidence-first retrieval.
4. **Evidence Project** — complete trusted-body Evidence Units, exact Claim evidence anchors, Claim→Evidence edges, coverage accounting, SQLite integrity, and deterministic rebuild verification.
5. **Event Project** — selected major events, A/B/C-separated event components, supported causal edges, temporal validation, path queries, and cycle/review findings.
6. **Character Project** — scoped core/important/placeholder people, evidence-bound attributes and states, time-bounded relationships, verified major-event links, and A/B/C-separated core-character arcs.
7. **Notion-ready projection** — fact-separated chapter, assertion, event, and focused-character pages for external upload.

No layer bypasses verification of its inputs.

## Inputs

Supported inputs include:

- one uploaded `.txt` or `.md` file;
- several uploaded text files with explicit input order;
- verified base source projects;
- a verified Chapter Project;
- one or more verified literary sidecars;
- optional reviewed literary annotation JSONL;
- reviewed Event Project annotation JSONL;
- reviewed Character Project annotation JSONL;
- a verified Event Project and Character Project;
- factual, structural, relational, character-state, character-arc, event, evidence, chapter-location, causal-path, or literary-analysis questions.

Supported strict decoding:

- UTF-8;
- UTF-8 with BOM;
- UTF-16 LE with BOM;
- UTF-16 BE with BOM.

Never use replacement decoding. Never modify the user's original file in place.

## Epistemic contract

Every knowledge conclusion and causal connection must retain its level.

### A — explicit source fact

A records require exact clean evidence bound to source, Unit, chapter, original span, evidence text, hashes, and contamination/review state. A records cannot be synthesis or interpretation.

### B — cross-evidence synthesis

B records summarize patterns or causal structure supported by multiple independent A records. Present them as synthesis, never as an explicit source sentence.

### C — model literary interpretation

C records may discuss theme, symbolism, narrative strategy, ethics, politics, or one plausible reading. They must be labeled model interpretation, cite A/B support, disclose limitations, and never enter A-grade fact or cause properties.

Do not silently promote C to B or B to A.

## Workflow

Treat the directory containing this `SKILL.md` as `SKILL_DIR`.

### 1. Check the bundled Skill

```bash
python "${SKILL_DIR}/scripts/tkr.py" doctor
python "${SKILL_DIR}/scripts/tkr.py" audit
```

### 2. Build and verify every base source project

```bash
python "${SKILL_DIR}/scripts/tkr.py" build INPUT.txt \
  --outdir BASE_PROJECT \
  --state-dir BUILD_STATE \
  --profile balanced

python "${SKILL_DIR}/scripts/tkr.py" verify BASE_PROJECT
```

Profiles:

- `balanced` — ordinary conservative build;
- `strict` — canonical indexing only when explicitly requested;
- `high-recall` — irregular corpora with additional review candidates.

### 3. Build and verify the Chapter Project

The source-project argument order is immutable input and physical file order. The canonical order is a separate numbering-derived candidate.

```bash
python "${SKILL_DIR}/scripts/tkr.py" chapter build \
  PROJECT_A PROJECT_B PROJECT_C \
  --outdir CHAPTER_PROJECT

python "${SKILL_DIR}/scripts/tkr.py" chapter verify CHAPTER_PROJECT \
  --source-project PROJECT_A \
  --source-project PROJECT_B \
  --source-project PROJECT_C
```

Query an address or neighbors:

```bash
python "${SKILL_DIR}/scripts/tkr.py" chapter query CHAPTER_PROJECT \
  --source-project PROJECT_A \
  --source-project PROJECT_B \
  --address 8 138

python "${SKILL_DIR}/scripts/tkr.py" chapter query CHAPTER_PROJECT \
  --source-project PROJECT_A \
  --source-project PROJECT_B \
  --chapter-id CHAPTER_ID \
  --neighbors physical
```

`physical` means original input order. `canonical` means the numbering-derived candidate. Never describe the candidate as a source rewrite.

### 4. Build and verify literary sidecars

```bash
python "${SKILL_DIR}/scripts/tkr.py" literary build BASE_PROJECT \
  --outdir LITERARY_PROJECT

python "${SKILL_DIR}/scripts/tkr.py" literary verify LITERARY_PROJECT
```

Optional reviewed annotations:

```bash
python "${SKILL_DIR}/scripts/tkr.py" literary build BASE_PROJECT \
  --outdir LITERARY_PROJECT \
  --annotations REVIEWED_ANNOTATIONS.jsonl
```

Annotations receive no automatic authority. They must pass exact evidence and A/B/C validation.

### 5. Build and verify the Evidence Project

```bash
python "${SKILL_DIR}/scripts/tkr.py" evidence build \
  BASE_PROJECT LITERARY_PROJECT \
  --outdir EVIDENCE_PROJECT

python "${SKILL_DIR}/scripts/tkr.py" evidence verify \
  BASE_PROJECT LITERARY_PROJECT EVIDENCE_PROJECT
```

### 6. Build and verify the Event Project

Event annotation JSONL may contain only reviewed `event`, `component`, and `edge` envelopes. Active events must materially affect the main plot, a core character, a major faction, world state, or a later major event.

```bash
python "${SKILL_DIR}/scripts/tkr.py" event build \
  CHAPTER_PROJECT EVENTS.jsonl \
  --source-project PROJECT_A \
  --source-project PROJECT_B \
  --literary-project LITERARY_PROJECT \
  --outdir EVENT_PROJECT

python "${SKILL_DIR}/scripts/tkr.py" event verify \
  EVENT_PROJECT CHAPTER_PROJECT EVENTS.jsonl \
  --source-project PROJECT_A \
  --source-project PROJECT_B \
  --literary-project LITERARY_PROJECT
```

Query an event profile, upstream causes, downstream consequences, a supported path, or foreshadowing:

```bash
python "${SKILL_DIR}/scripts/tkr.py" event query \
  EVENT_PROJECT CHAPTER_PROJECT EVENTS.jsonl \
  --source-project PROJECT_A \
  --source-project PROJECT_B \
  --literary-project LITERARY_PROJECT \
  --name "联盟瓦解"

python "${SKILL_DIR}/scripts/tkr.py" event query \
  EVENT_PROJECT CHAPTER_PROJECT EVENTS.jsonl \
  --source-project PROJECT_A \
  --source-project PROJECT_B \
  --literary-project LITERARY_PROJECT \
  --path EVENT_A EVENT_B
```

If the Event Project status is `review_required`, causal answers must refuse until cycles or other high-severity findings are reviewed.

### 7. Build and verify the Focused Character Project

Character annotation JSONL may contain only reviewed `character`, `attribute`, `state`, `relationship`, and `event_link` envelopes. Core characters require material mainline impact; important characters require major-event, major-faction, core-character, or world-state impact; placeholders remain minimal. Mention frequency alone cannot promote a character.

```bash
python "${SKILL_DIR}/scripts/tkr.py" character build \
  CHAPTER_PROJECT EVENT_PROJECT EVENTS.jsonl CHARACTERS.jsonl \
  --source-project PROJECT_A \
  --source-project PROJECT_B \
  --literary-project LITERARY_PROJECT \
  --outdir CHARACTER_PROJECT

python "${SKILL_DIR}/scripts/tkr.py" character verify \
  CHARACTER_PROJECT CHAPTER_PROJECT EVENT_PROJECT EVENTS.jsonl CHARACTERS.jsonl \
  --source-project PROJECT_A \
  --source-project PROJECT_B \
  --literary-project LITERARY_PROJECT
```

Query a profile, state at a chapter position, relationship interval, major-event links, selection reason, or core-character arc:

```bash
python "${SKILL_DIR}/scripts/tkr.py" character query \
  CHARACTER_PROJECT CHAPTER_PROJECT EVENT_PROJECT EVENTS.jsonl CHARACTERS.jsonl \
  --source-project PROJECT_A \
  --source-project PROJECT_B \
  --literary-project LITERARY_PROJECT \
  --name "应飞扬"

python "${SKILL_DIR}/scripts/tkr.py" character query \
  CHARACTER_PROJECT CHAPTER_PROJECT EVENT_PROJECT EVENTS.jsonl CHARACTERS.jsonl \
  --source-project PROJECT_A \
  --source-project PROJECT_B \
  --literary-project LITERARY_PROJECT \
  --arc "应飞扬"
```

Placeholder characters cannot receive complete ability systems, deep relationships, or character arcs. If the Event Project or Character Project is `review_required`, character conclusions must refuse.

### 8. Query the appropriate layer

Use the base layer for deterministic typed predicates:

```bash
python "${SKILL_DIR}/scripts/tkr.py" query BASE_PROJECT "陆川击败了谁？"
```

Use the Chapter Project for exact source location and order. Use the Event Project for supported causal chains. Use the Character Project for scoped profiles, time-bounded states and relationships, major-event participation, and core-character arcs. Use the literary layer for other evidence-linked records and explicitly separated analysis.

Do not rewrite an A/B/C-separated response into one undifferentiated narrative.

### 9. Export a Notion-ready package

```bash
python "${SKILL_DIR}/scripts/tkr.py" literary export-notion LITERARY_PROJECT \
  --outdir NOTION_PACKAGE
```

Preserve page IDs and relation IDs so later revisions update existing records rather than create duplicates.

## Chapter Structure contract

A Chapter Project records:

- **physical order** — immutable supplied project order and source-local position;
- **canonical-order candidate** — volume/chapter numbering order for review and retrieval.

Volume ordinals may derive from a combined heading, explicit parent volume Unit, conservative preceding-volume context, or remain unresolved. The derivation basis must be retained.

Required findings include duplicate keys/content, gaps, inversions, missing ordinals/headings/body, contamination, overlapping source ranges, and input order that differs from numbering order.

## Event Causality contract

Canonical event nodes are limited to materially significant events. Low-impact scenes remain chapter passages or review candidates.

Internal event components:

- `cause`;
- `process`;
- `outcome`;
- `consequence`;
- `foreshadowing`;
- `recovery`.

Event-to-event relations:

- `triggers`;
- `enables`;
- `escalates`;
- `prevents`;
- `reveals`;
- `undermines`;
- `resolves`;
- `foreshadows`;
- `recovers`.

Forward relations cannot silently point backward in time. `recovers` explicitly references an earlier clue or event. Causal cycles remain findings; they are never silently broken. Every query path must return its supporting assertions and evidence anchors.

## Focused Character contract

Character scopes are strict:

- `core` — deep evidence-bound identity, goals, choices, states, major relationships, major events, and A/B/C-separated arcs;
- `important` — moderate identity, role, state, major relationships, and major-event modeling;
- `placeholder` — minimal identity, role, chapter location, and necessary event participation only;
- mention-only — no canonical Character Project entity unless later evidence establishes material impact.

A-grade character records require exact assertions and evidence anchors. B-grade character synthesis requires multiple supported A-grade records. C-grade character interpretation requires explicit model attribution and limitations. Only core characters may receive formal arc records. Alias collisions, contradictory overlapping states, unsupported event links, and placeholder depth leakage remain explicit findings.

## Base deterministic predicates

The base fact engine supports `alias`, `defeats`, `located_in`, `permission`, `count`, and `date`. These form a deterministic A-grade foundation, not a claim that every literary fact is already extracted.

## Refusal rules

Refuse rather than improvise when:

- a requested chapter address is absent or ambiguous;
- file order or volume context is unresolved;
- the relevant span is polluted or review-only;
- any project, SQLite, report, manifest, source, or answer verification fails;
- evidence exists but no validated conclusion supports the answer;
- an Event Project or Character Project is `review_required`;
- a placeholder is asked for an unsupported deep relationship, ability system, personality analysis, or character arc;
- no supported causal path exists;
- a causal edge uses unknown assertions/evidence or invalid temporal direction;
- an interpretation lacks A/B support;
- missing post-gap content is requested as established fact.

A refusal is a correct result.

## Safety boundaries

1. Preserve original source bytes and SHA-256 identity.
2. Never decode with replacement characters.
3. Never auto-delete pollution, paratext, anomalies, or duplicates.
4. Never rewrite chapter numbers, titles, file order, or source text.
5. Keep physical and canonical candidate order separate.
6. Never accept evidence whose offsets, text, and hashes do not match source.
7. Never invent event nodes or causal links to complete a narrative.
8. Never promote C-grade interpretation to A-grade cause.
9. Never silently break causal cycles or contradictions.
10. Never promote mention frequency into character importance.
11. Never invent identity merges, personality, morality, growth, relationships, abilities, or character arcs.
12. Never allow placeholder records to acquire core-character depth.
13. Never answer from model memory when verified support is absent.
14. Stop on any verification failure.
15. Do not combine files without explicit order.
16. Never claim all capabilities exceed 9.0 before final private blind evaluation.
17. Never claim v6 release or freeze from an engineering-stage check.

## Standard artifacts

Base project:

```text
source/
stage1-anomaly/
stage2-structure/
stage3-semantics/
bridge/
index/
project-report.json
project-manifest.json
```

Evidence Project:

```text
evidence-units.jsonl
claim-evidence-anchors.jsonl
claim-evidence-edges.jsonl
evidence-coverage.json
claim-graph-report.json
evidence.sqlite
evidence-project-report.json
artifact-manifest.json
```

Chapter Project:

```text
source-bindings.jsonl
chapters.jsonl
canonical-order.jsonl
chapter-findings.jsonl
chapter.sqlite
chapter-project-report.json
artifact-manifest.json
```

Event Project:

```text
events.jsonl
event-components.jsonl
event-causal-edges.jsonl
event-findings.jsonl
event.sqlite
event-project-report.json
artifact-manifest.json
```

Character Project:

```text
characters.jsonl
character-attributes.jsonl
character-states.jsonl
character-relationships.jsonl
character-event-links.jsonl
character-findings.jsonl
character.sqlite
character-project-report.json
artifact-manifest.json
```

Literary sidecar:

```text
chapters.jsonl
evidence-anchors.jsonl
entities.jsonl
assertions.jsonl
relationships.jsonl
events.jsonl
revisions.jsonl
literary.sqlite
literary-report.json
artifact-manifest.json
```

## Commands

Bundled command surface:

```text
doctor
audit
profiles
show-profile
build
verify
query
verify-answer
chapter build
chapter verify
chapter query
evidence build
evidence verify
event build
event verify
event query
character build
character verify
character query
literary build
literary verify
literary query
literary export-notion
```

Automation aliases:

```text
chapter-build
chapter-verify
chapter-query
evidence-build
evidence-verify
event-build
event-verify
event-query
character-build
character-verify
character-query
literary-build
literary-verify
literary-query
literary-export-notion
```

```bash
python "${SKILL_DIR}/scripts/tkr.py" --help
```

## Output requirements

For a Chapter Project, report source order, canonical candidate order, address coverage, findings, exact spans/hashes, and review requirements.

For an Event Project, report:

- selected event count and significance;
- A/B/C component counts;
- active and contested causal-edge counts;
- cycles, unsupported references, and temporal findings;
- chapter/literary/annotation binding hashes;
- graph status: `completed` or `review_required`;
- logical and database hashes.

For a Character Project, report scope counts, selection reasons, A/B/C attribute counts, state and relationship intervals, major-event links, alias/state conflicts, graph status, logical hash, database hash, and placeholders kept minimal.

For an answer, report answer or refusal, epistemic tier, character scope when relevant, event component or edge type, path direction, chapter binding, supporting assertion IDs, exact evidence anchors, support chains, and limitations.

## Final checks

Before responding:

1. Verify every base project used.
2. Verify the Chapter Project for chapter/order information.
3. Verify every literary sidecar used.
4. Verify the Evidence Project for Claim support.
5. Verify the Event Project for causal answers and character-event links.
6. Verify the Character Project for character profiles, states, relationships, events, and arcs.
7. Confirm exact offsets, text, hashes, and source identity.
8. Confirm physical order was not rewritten.
9. Confirm canonical order is labeled candidate.
10. Confirm active events and modeled core/important characters are materially significant.
11. Confirm placeholder and mention-only records were not given invented depth.
12. Confirm every causal edge and character record has verified support.
13. Confirm `review_required` graphs refuse presentation.
14. Confirm A/B/C separation remains intact.
15. Confirm downloadable files exist at the exact linked path.
16. State that v6 remains under development until final integrated acceptance.

## Acceptance boundary

The historical v5.9 release remains archived and unchanged. Stage 1, Stage 2, Stage 3, and Stage 4 checks are engineering evidence for the v6 development line. They do not establish that every final literary capability has reached 9.0, do not create a release candidate, and do not authorize repository freeze.
