# Stage 2 Result — Deterministic Corpus Structure

## Status

```yaml
stage: Stage 2
implementation: complete
local_focused_tests: 21_passed
github_focused_checks: pending
integration: pending_pull_request
project_acceptance_performed: false
release_candidate: false
freeze_approved: false
```

## Estimated engineering time

The planned Stage 2 effort is **12–18 engineering hours**. The estimate covers deterministic heading recognition, Unit Index generation, continuity findings, schemas, artifacts, focused tests, CLI integration, CI, documentation, and integration review. It excludes real-corpus acceptance, private blind evaluation, long-corpus performance testing, and final project validation.

## Completed implementation

### Heading candidates

- Arabic and full-width numeric headings.
- Conventional Chinese integer headings, including spaced forms such as `第 十 二 章`.
- Volume, part, chapter, section, book, episode, and act-style hierarchy markers.
- English `Volume`, `Book`, `Part`, `Chapter`, and `Section` headings.
- Markdown headings with fenced-code suppression.
- Prologue, preface, epilogue, afterword, appendix, and extra-story classification.
- Heading and body boundaries on the same physical line.
- Numbered headings split across two physical lines.
- Detached-title review candidates without silently changing the Unit title.
- Ambiguous long headings retained as review candidates instead of automatic boundaries.

### Deterministic Unit Index

- Exact decoded-character offsets with the external BOM excluded.
- Contiguous, non-overlapping Units covering the complete decoded source.
- Front-matter and no-heading document fallback Units.
- Deterministic parent-child relationships by hierarchy level.
- Source-bound Unit IDs.
- Per-Unit content SHA-256 values.
- Heading, body, line, and character boundaries.
- Unit limits that stop additional boundary promotion without truncating source scanning.
- Post-scan source rehashing to detect concurrent modification.

### Continuity and structure findings

- Duplicate ordinal candidates.
- Missing-number or intentional-skip candidates.
- Numbering inversion candidates.
- Duplicate title candidates.
- Empty Unit body candidates.
- Late front-matter candidates.
- Chapter-after-epilogue candidates.
- Detached-title recovery candidates.
- Ambiguous heading candidates.

### Standard artifacts

```text
structure-report.json
heading-candidates.jsonl
unit-index.jsonl
structure-anomalies.jsonl
unit-ledger.csv
stage-result.json
artifact-manifest.json
```

Every stage result keeps:

```yaml
project_acceptance_performed: false
may_accept_project: false
may_freeze: false
```

### Schema contracts

```text
schemas/heading-candidate.schema.json
schemas/unit-record.schema.json
schemas/structure-finding.schema.json
schemas/structure-report.schema.json
```

## Focused test coverage

The 21 local focused tests cover:

- Arabic, full-width, and Chinese ordinal parsing;
- numbered chapters and exact source coverage;
- volume/chapter/section parent hierarchy;
- special unit classification;
- English and Markdown headings;
- inline heading and body boundaries;
- split numbered headings;
- spaced Chinese heading numbers;
- fenced-code false-positive protection;
- no-heading fallback document Units;
- duplicate, gap, and inversion findings;
- duplicate title and empty body findings;
- epilogue and front-matter placement findings;
- UTF-8 BOM and UTF-16 LE/BE offsets;
- unsupported-source blocking;
- policy validation;
- deterministic reports;
- deterministic artifact publication;
- CLI output;
- detached-title recovery candidates;
- Unit-limit behavior without source truncation.

## Remaining limitations

Stage 2 does not claim measured production accuracy. The following are deferred to final acceptance:

- private heading Precision and Recall;
- Unit boundary accuracy across unseen corpus formats;
- clean-corpus false-positive rate;
- long-corpus throughput and peak memory;
- adversarial malformed-heading recovery metrics;
- end-to-end integration with Claim extraction;
- final capability score.

## Next large stage

**Stage 3 — Evidence-grounded semantics**

Estimated engineering time: **24–36 hours**.

Scope:

- conservative Claim candidate extraction;
- six-predicate extraction interfaces;
- exact Evidence span binding;
- fact, belief, suspicion, rumor, accusation, and negation separation;
- deterministic validation before acceptance;
- entity, alias, timeline, and conflict integration;
- semantic artifacts and schemas.
