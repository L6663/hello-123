---
name: text-knowledge-reader
description: Build an evidence-bound knowledge project from uploaded UTF-8 or BOM-marked UTF-16 text, detect contamination and structure, extract six typed fact relations, answer supported questions with exact citations, and refuse unsupported claims. Use for books, historical corpora, technical documents, notes, and other long text files when source integrity and auditable evidence matter.
---

# Text Knowledge Reader

**Version:** 5.9.0  
**Status:** Final, accepted, and frozen

## Purpose

Use this skill to turn one or more uploaded text files into auditable, source-bound knowledge projects and answer factual questions only when the answer is supported by exact evidence.

The skill is self-contained. Do not ask the user to install a Wheel, clone a repository, or run commands manually. Use the bundled Python entry point in `scripts/tkr.py`.

## Inputs

Primary inputs:

- one uploaded `.txt` or `.md` file;
- optionally several text files, processed as separate projects unless the user explicitly asks to combine them;
- a factual question about a project already built in the current conversation;
- an existing Text Knowledge Reader project directory or saved answer packet.

Supported decoding:

- strict UTF-8;
- UTF-8 with BOM;
- UTF-16 LE with BOM;
- UTF-16 BE with BOM.

Never silently replace undecodable characters. Never mutate, overwrite, delete, or normalize the user's original source file in place.

## Workflow

### 1. Locate the skill and inputs

Treat the directory containing this `SKILL.md` as `SKILL_DIR`.

Use only files actually available in the current conversation or sandbox. Do not infer file paths from filenames alone. Do not use prior model knowledge to fill missing corpus content.

### 2. Choose the operation

Use these operations:

- **Build** when the user uploads a corpus or asks to create a knowledge base.
- **Verify** when the user asks whether a built project is intact.
- **Query** when the user asks a supported factual question.
- **Verify answer** when the user provides a saved answer packet.
- **Inspect** when the user asks for source, anomaly, structure, or semantic diagnostics.

### 3. Run the bundled entry point

Use the current Python interpreter:

```bash
python "${SKILL_DIR}/scripts/tkr.py" doctor
python "${SKILL_DIR}/scripts/tkr.py" audit
```

Build a project:

```bash
python "${SKILL_DIR}/scripts/tkr.py" build INPUT.txt \
  --outdir OUTPUT_PROJECT \
  --state-dir OUTPUT_STATE \
  --profile balanced
```

Use `strict` only when the user explicitly requests canonical/final indexing. Use `high-recall` for difficult or irregular corpora when review findings are acceptable.

Verify:

```bash
python "${SKILL_DIR}/scripts/tkr.py" verify OUTPUT_PROJECT
```

Query:

```bash
python "${SKILL_DIR}/scripts/tkr.py" query OUTPUT_PROJECT "QUESTION"
```

Save an answer packet when useful:

```bash
python "${SKILL_DIR}/scripts/tkr.py" query OUTPUT_PROJECT "QUESTION" --output ANSWER.json
python "${SKILL_DIR}/scripts/tkr.py" verify-answer OUTPUT_PROJECT ANSWER.json
```

### 4. Interpret results

A completed build produces a self-contained project with:

- original and normalized source identity;
- anomaly and contamination candidates;
- deterministic heading and Unit Index artifacts;
- semantic candidates and accepted claims;
- entity, fact, timeline, conflict, and ambiguity artifacts;
- SQLite knowledge index;
- project report and immutable manifest.

A query may either:

- return a supported answer with exact evidence and citation chain; or
- return a deterministic refusal because the predicate is unsupported, evidence is missing, identity is ambiguous, facts conflict, or integrity verification failed.

Do not rewrite a refusal as a speculative answer.

## Supported predicates

The deterministic fact and QA stack supports:

- `alias` — names and aliases;
- `defeats` — who defeated whom;
- `located_in` — where an entity is located;
- `permission` — who may or may not perform an action;
- `count` — explicit quantities;
- `date` — explicit dates.

Examples:

- `玄霄又称青帝。`
- `陆川击败韩岳。`
- `听雪楼位于北境。`
- `守门人允许陆川进入内殿。`
- `剑阵共有十二柄飞剑。`
- `大战发生于2026年7月22日。`

Open-ended theme, symbolism, motive, emotional interpretation, literary criticism, and unsupported predicates are outside the deterministic fact contract unless the user explicitly requests a non-authoritative reading separate from the knowledge project.

## Factual-status handling

Separate direct assertions from:

- negated assertions;
- beliefs;
- suspicions;
- rumors;
- accusations;
- hypotheticals;
- questions;
- future intentions.

Only direct assertions that pass source, structure, anomaly, evidence, validation, entity, conflict, and integrity gates may enter accepted facts.

## Safety boundaries

Always enforce these rules:

1. Preserve original source bytes and SHA-256 identity.
2. Do not repair text through replacement decoding.
3. Do not auto-delete suspected pollution, paratext, or anomalous spans.
4. Do not accept a claim whose evidence span or evidence text does not exactly match the source.
5. Do not treat belief, rumor, suspicion, accusation, question, hypothetical, or future intent as established fact.
6. Do not answer from model memory when the project lacks evidence.
7. Do not continue after project, database, manifest, source, or answer-packet integrity verification fails.
8. Do not combine separate source files without explicit user authorization and a documented combination method.
9. Keep mutable locks, journals, and caches outside the immutable project directory.
10. Never claim successful processing when a command failed or returned a blocked status.

## Standard artifacts

For each project, preserve and offer the relevant artifacts to the user:

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

When the user asks for a downloadable result, package the project directory rather than only pasting console output.

## Commands

The bundled entry point exposes:

```text
doctor
 audit
 profiles
 show-profile
 build
 verify
 query
 verify-answer
```

Examples:

```bash
python scripts/tkr.py profiles
python scripts/tkr.py show-profile balanced
python scripts/tkr.py build corpus.txt --outdir project --profile balanced
python scripts/tkr.py verify project
python scripts/tkr.py query project "陆川击败了谁？"
```

## Output format

For a build, report:

- source filename and SHA-256;
- selected encoding;
- project status and project ID;
- Unit, candidate, accepted-claim, conflict, and ambiguity counts;
- important blockers or review findings;
- links to the project package and key reports.

For a supported answer, report:

- answer;
- predicate and normalized entities/value;
- exact evidence excerpt;
- Unit identifier or title;
- source identifier and source SHA-256;
- answer packet when requested.

For a refusal, report:

- refusal decision;
- concrete reason code or reason category;
- what additional evidence or clarification would be required.

## Final checks

Before responding:

1. Verify the project.
2. Confirm cited evidence exactly matches the source span.
3. Confirm the answer is supported by an accepted claim.
4. Confirm no unresolved conflict or ambiguity invalidates the answer.
5. Confirm no unsupported inference was introduced.
6. Confirm any downloadable package exists at the exact path being linked.

## Acceptance boundary

This is the directly usable Text Knowledge Reader skill bundle. Its bundled engine completed the integrated capability acceptance used to produce this package. That does not permit false claims about a new user corpus: every new corpus and every answer must still pass its own source-bound checks.
