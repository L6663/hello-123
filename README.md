# Text Knowledge Reader – staged hardening workspace

This repository hardens one subsystem at a time and keeps every stage independently testable.

## Current stack

- **v5.2 Phase 2:** deterministic bounded chunking;
- **v5.3 Phase 3:** typed Claim evidence validation;
- **v5.4 Phase 4:** entity, alias, homonym, timeline, and conflict normalization;
- **v5.5 Phase 5:** hash-verified SQLite indexing and predicate-aware hybrid retrieval;
- **v5.6 Phase 6:** strict answers, evidence packets, citation entailment, and refusal decisions;
- **v5.7 Phase 7:** immutable Gold Benchmark coverage, accuracy, refusal, citation, and hallucination gates;
- **v5.8 Phase 8:** artifact-chain manifests, reproducible wheel checks, explicit approval, and freeze seals.

## v5.7 release acceptance

`benchmark/release_benchmark.py` builds a versioned 108-case Release Gold corpus with 48 answered cases, 20 cases for each refusal class, complete six-predicate coverage, and repeated database-grounded hard negatives. The complete case specifications and full Gold JSONL bytes are bound to immutable SHA-256 commitments.

`.github/workflows/release-acceptance.yml` builds the wheel with a fixed `SOURCE_DATE_EPOCH`, installs it into isolated Python 3.10, 3.11, and 3.12 environments, checks every console script, audits wheel contents and installed size, runs and verifies the Release Gold gate, rebuilds the wheel twice, and assembles a technical freeze candidate.

## Phase 7 contract

Phase 7 evaluates strict QA against a JSONL Gold set. The dataset cannot provide thresholds. The built-in policies are:

- `smoke`: a non-certifying integration gate with at least 12 cases;
- `release`: a supplied-Gold behavior gate with at least 100 cases.

Both profiles impose immutable coverage, answer, refusal, citation, integrity, and hallucination requirements. A passing release report may set `may_certify_release=true`, but Phase 7 must keep `may_freeze=false`.

## Phase 8 contract

Phase 8 separates technical readiness from human release authority.

### Technical candidate

`tkr-release-freeze prepare` requires and binds:

- one exact wheel;
- one Release Gold manifest, report, and verification result;
- accepted package reports from Python 3.10, 3.11, and 3.12;
- one reproducible-build report containing at least two byte-identical wheel builds;
- release version, source commit, and fixed source-date epoch.

The candidate recomputes every file size and SHA-256, rechecks the Release Gold authority boundary, confirms all package reports point to the same wheel, and verifies byte-for-byte reproducibility. A technical candidate always contains:

```json
{
  "technical_gate_passed": true,
  "requires_explicit_approval": true,
  "may_freeze": false,
  "status": "candidate"
}
```

It cannot authorize itself.

### Explicit approval and seal

`tkr-release-freeze seal` requires a separate approval JSON object whose candidate ID, release version, and source commit exactly match the verified technical candidate. Only then can a seal contain `may_freeze=true`.

The current approval record is an operator assertion rather than a cryptographically authenticated signature. Every seal states:

```json
{
  "approval_authentication": "operator_asserted_not_cryptographically_verified"
}
```

This prevents the tool from overstating identity assurance.

## Gold case format

Each JSONL case declares the current parser predicate and exact expected decision. An answered case must include a complete structured answer Claim, at least one expected Fact ID, and at least one evidence SHA-256. Refusal cases must not contain answer or citation expectations.

Unknown fields, duplicate case IDs, parser-label mismatches, invalid hashes, vacuous answered cases, refusal cases carrying answer expectations, and hard-negative labels that contradict the case structure are rejected before scoring.

## Usage

```bash
python -m pip install .

# Run the immutable release behavior gate.
tkr-gold-benchmark run \
  project/index/knowledge.sqlite3 \
  project/benchmark/gold-release.jsonl \
  --profile release \
  --output project/benchmark/release-report.json

# Recompute and verify the release report.
tkr-gold-benchmark verify \
  project/index/knowledge.sqlite3 \
  project/benchmark/gold-release.jsonl \
  project/benchmark/release-report.json \
  --require-profile release

# Prepare a non-authorizing technical candidate.
tkr-release-freeze prepare \
  --root release-evidence \
  --version 5.8.0a1 \
  --source-commit 0123456789abcdef0123456789abcdef01234567 \
  --source-date-epoch 1700000000 \
  --artifact wheel=release-evidence/text_knowledge_reader_core-5.8.0a1-py3-none-any.whl \
  --artifact release_manifest=release-evidence/release-manifest.json \
  --artifact release_report=release-evidence/release-report.json \
  --artifact release_verification=release-evidence/release-verification.json \
  --artifact reproducible_build_report=release-evidence/reproducible-build-report.json \
  --artifact package_acceptance=release-evidence/package-acceptance-python-3.10.json \
  --artifact package_acceptance=release-evidence/package-acceptance-python-3.11.json \
  --artifact package_acceptance=release-evidence/package-acceptance-python-3.12.json

# Recompute candidate evidence and hashes.
tkr-release-freeze verify release-evidence/freeze-candidate.json \
  --root release-evidence

# Seal only after a separate explicit approval record exists.
tkr-release-freeze seal \
  release-evidence/freeze-candidate.json \
  release-evidence/freeze-approval.json \
  --root release-evidence \
  --output release-evidence/freeze-seal.json
```

## Validation

```bash
python -m compileall -q tkr tests benchmark tools
python -m unittest discover -s tests -v
```

GitHub Actions runs the complete stack, independent wheel acceptance, reproducible builds, technical-candidate assembly, and Phase 8 tests on Python 3.10, 3.11, and 3.12.

## Deliberate limits

The stack certifies measured behavior only for six closed predicates on the supplied Gold set. It does not prove open-ended novel understanding, causal reasoning, thematic interpretation, pronoun resolution, or unseen-domain generalization. Phase 8 adds an auditable technical freeze process, but the current approval identity remains operator-asserted rather than cryptographically signed.
