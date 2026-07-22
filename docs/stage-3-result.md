# Stage 3 Result — Evidence-Grounded Claim Extraction and Semantic Modeling

## Status

```yaml
stage: Stage 3
estimated_engineering_time: 24_to_36_hours
implementation: complete
local_focused_tests: 31_passed
github_focused_checks: pending
integration: pending_pull_request
project_acceptance_performed: false
release_candidate: false
freeze_approved: false
```

## Scope completed

### Claim candidate contract

Each semantic candidate binds:

- one of six supported Claim types;
- subject, object, value, unit, and polarity;
- discourse and factual status;
- source and Unit identities;
- exact Evidence and trigger character spans;
- line ranges and Evidence SHA-256;
- deterministic extraction rule, candidate ID, validation result, and review state.

### Six-predicate extraction

The deterministic lexical layer proposes candidates for:

```text
alias
defeats
located_in
permission
count
date
```

Assertive proposals must pass the existing deterministic Claim validator before they may enter `accepted-claims.jsonl`.

### Factual-status separation

Stage 3 separates:

- asserted facts;
- negated facts;
- beliefs;
- suspicions;
- rumors;
- accusations;
- hypotheticals;
- questions;
- future intentions.

Only direct assertions that pass deterministic validation and all upstream gates may be marked `may_index=true`. Nonassertive propositions are retained with attribution but cannot become canonical facts.

### Upstream safety gates

- Candidate Evidence is restricted to Stage 2 Unit body spans.
- Units requiring structural review cannot contribute indexable Claims.
- Evidence overlapping Stage 1 contamination, paratext, or high-severity text anomalies cannot be indexed.
- Source and Unit hashes are verified, and the source is rehashed after extraction.

### Constrained model interface

Model assistance is limited to exact source-bound proposal tasks. A model task:

- permits only the six supported Claim types;
- binds one exact Evidence span;
- forbids acceptance, indexing, certification, and freeze authority;
- requires deterministic validation for every returned proposal;
- rejects output that escapes the task Evidence span or modifies Evidence text.

### Existing semantic stack integration

Accepted assertions are converted to the existing Phase 3 accepted-record contract and passed through the Phase 4 normalizer. Stage 3 therefore emits deterministic:

- entity mentions;
- entities and aliases;
- facts;
- timeline events;
- conflicts;
- ambiguity groups;
- normalization report.

## Standard artifact set

```text
semantic-report.json
claim-candidates.jsonl
accepted-claims.jsonl
nonassertive-claims.jsonl
semantic-findings.jsonl
model-extraction-tasks.jsonl
entities.jsonl
facts.jsonl
timeline.jsonl
conflicts.jsonl
ambiguity-groups.jsonl
normalization-report.json
semantic-ledger.csv
stage-result.json
artifact-manifest.json
```

## Contracts

```text
schemas/semantic-candidate.schema.json
schemas/semantic-finding.schema.json
schemas/model-extraction-task.schema.json
schemas/accepted-claim-record.schema.json
schemas/semantic-report.schema.json
```

## Focused test coverage

The 31 local focused tests cover:

- six-predicate extraction;
- positive and negative permission;
- Chinese integer and decimal count values;
- exact date values;
- rumor, belief, suspicion, accusation, hypothetical, question, and future-intent isolation;
- negated relation rejection;
- Evidence span and hash correctness;
- Unit heading exclusion;
- deterministic candidate IDs;
- constrained model tasks and proposal envelope checks;
- entity-normalization output;
- UTF-8 BOM and UTF-16 offsets;
- candidate limits;
- upstream anomaly-overlap blocking;
- deterministic artifact publication;
- CLI output and policy validation.

## Remaining final-acceptance measurements

Stage 3 does not claim measured production accuracy. The following remain deferred until the final integrated Skill acceptance:

- private six-predicate precision, recall, and Macro-F1;
- private factual-status Macro-F1;
- zero rumor, suspicion, belief, or accusation promotions to fact;
- exact Evidence span accuracy;
- clean-corpus false-positive rates;
- long-corpus throughput and peak memory;
- model-proposal adversarial resistance;
- complete end-to-end indexing and QA behavior.

## Next large stage

**Stage 4 — End-to-End Knowledge System**

Estimated engineering time: **18–28 hours**.

Scope:

- raw-corpus orchestration;
- accepted Claim and entity indexing;
- retrieval filtering by source, Unit, entity, predicate, time, and review state;
- strict answers and refusal;
- complete citation provenance from answer to source SHA-256;
- conflict-aware and ambiguity-aware responses;
- deterministic pipeline manifests and incremental stage reuse.
