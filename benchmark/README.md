# v5.7 Release Gold benchmark

`release_benchmark.py` builds a deterministic, versioned release-acceptance corpus and evaluates the installed Text Knowledge Reader wheel with the immutable Phase 7 `release` policy.

## Coverage

The benchmark contains 108 curated cases:

- 48 answered cases: eight each for `alias`, `defeats`, `located_in`, `permission`, `count`, and `date`;
- 20 `refused_unsupported` cases;
- 20 `refused_insufficient_evidence` cases;
- 20 `refused_ambiguous` cases;
- at least three database-grounded cases for every required hard-negative family.

The corpus deliberately includes relation reversals, explicit permission denials, missing typed facts, lexical distractors, absence-not-negative cases, numeric-prefix collisions, contested facts, and temporal variants.

## Gold governance

Expected decisions and structured answer Claims are first-party curated in the versioned script. The complete case specifications and full 108-row Gold JSONL bytes are bound to immutable SHA-256 commitments. A candidate may materialize Fact IDs and evidence hashes only when the resulting Gold bytes reproduce the pre-existing canonical commitment exactly.

The resulting manifest records the case-spec commitment and hashes of the corpus, Unit index, accepted Claims, SQLite index, Gold JSONL, benchmark report, and verification report.

This is a real, executable release gate for the six closed predicates. It is not an independently annotated external novel corpus, does not prove open-domain understanding, and cannot grant final freeze authority. Every report and manifest keeps `may_freeze=false`.

## Run

The package must be installed before invoking the script directly from a source checkout:

```bash
python -m pip install .
python benchmark/release_benchmark.py --output build/release-benchmark
```

Successful execution requires:

- the immutable `release` profile to pass;
- `may_certify_release=true`;
- exact report recomputation to be accepted;
- zero hallucinations, overanswers, wrong answers, citation mismatches, evaluator failures, integrity failures, and ungrounded hard-negative labels.

The `release-acceptance` GitHub Actions workflow executes this benchmark from an isolated wheel installation on Python 3.10, 3.11, and 3.12 and uploads the complete evidence bundle.
