# Text Knowledge Reader – staged hardening workspace

This repository hardens one subsystem at a time and keeps every stage independently testable.

## Current stack

- **v5.2 Phase 2:** deterministic bounded chunking;
- **v5.3 Phase 3:** typed Claim evidence validation;
- **v5.4 Phase 4:** entity, alias, homonym, timeline, and conflict normalization;
- **v5.5 Phase 5:** hash-verified SQLite indexing and predicate-aware hybrid retrieval;
- **v5.6 Phase 6:** strict answers, evidence packets, citation entailment, and refusal decisions;
- **v5.7 Phase 7:** immutable Gold Benchmark coverage, accuracy, refusal, citation, and hallucination gates.

## Phase 7 contract

Phase 7 evaluates Phase 6 against a JSONL Gold set. The dataset cannot provide thresholds. The CLI exposes only two built-in policy profiles:

- `smoke`: a non-certifying integration gate with at least 12 cases;
- `release`: a release-candidate gate with at least 100 cases.

Both profiles impose immutable requirements for:

- total case count;
- answerable and refusal-category counts;
- answered coverage for all six supported predicates;
- hard-negative category coverage;
- exact decision accuracy;
- structured answer-Claim accuracy;
- exact Fact/evidence citation agreement;
- answer and refusal precision/recall;
- zero overanswers, wrong answers, citation mismatches, integrity failures, and evaluator failures;
- zero measured hallucination rate.

The release profile additionally requires at least seven answered cases for each of `alias`, `defeats`, `located_in`, `permission`, `count`, and `date`, at least fifteen cases for each refusal class, and repeated coverage of all hard-negative families.

## Gold case format

Each JSONL case declares the current parser predicate and exact expected decision. An answered case must include a complete structured answer Claim, at least one expected Fact ID, and at least one evidence SHA-256. Refusal cases must not contain answer or citation expectations.

```json
{
  "gold_schema_version": "tkr-gold-cases-v1",
  "case_id": "count-current-001",
  "question": "守卫现在有多少名？",
  "expected_decision": "answered",
  "expected_predicate": "count",
  "expected_answer_claim": {
    "predicate": "count",
    "requested_role": "value",
    "subject": "守卫",
    "object": "",
    "value": 120,
    "unit": "名",
    "predicate_scope": "",
    "fact_polarity": true,
    "boolean_answer": null,
    "temporal_scope": "current"
  },
  "expected_fact_ids": ["fact_..."],
  "expected_evidence_sha256": ["..."],
  "source_id_filter": null,
  "tags": ["temporal_scope"]
}
```

Unknown fields, duplicate case IDs, parser-label mismatches, invalid hashes, vacuous answered cases, or refusal cases carrying answer expectations are rejected before scoring.

## Usage

```bash
python -m pip install .

# Run the non-certifying integration gate.
tkr-gold-benchmark run \
  project/index/knowledge.sqlite3 \
  project/benchmark/gold.jsonl \
  --profile smoke \
  --output project/benchmark/smoke-report.json

# Run the immutable release-candidate gate.
tkr-gold-benchmark run \
  project/index/knowledge.sqlite3 \
  project/benchmark/gold-release.jsonl \
  --profile release \
  --output project/benchmark/release-report.json

# Recompute the database, Gold set, policy, cases, metrics, and report ID.
tkr-gold-benchmark verify \
  project/index/knowledge.sqlite3 \
  project/benchmark/gold-release.jsonl \
  project/benchmark/release-report.json
```

A report binds the SQLite database SHA-256, index-report SHA-256, raw Gold-file SHA-256, logical Gold-case SHA-256, evaluator version, complete immutable policy, per-case outcomes, metrics, blockers, and report ID. Editing a threshold, score, case result, authority flag, or hash invalidates verification.

## Validation

```bash
python -m compileall -q tkr tests
python -m unittest discover -s tests -v
```

GitHub Actions runs the complete stack on Python 3.10, 3.11, and 3.12.

## Deliberate limits

Phase 7 certifies only measured behavior of the six closed predicates on the supplied Gold set. It does not prove open-ended novel understanding, causal reasoning, personality analysis, thematic interpretation, pronoun resolution, or unseen-domain generalization. A passing release benchmark may mark `may_certify_release=true`, but every Phase 7 report keeps `may_freeze=false`; final artifact-chain freezing remains a later stage.
