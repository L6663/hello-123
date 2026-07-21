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

Expected decisions and structured answer Claims are first-party curated in the versioned script. Fact IDs and evidence hashes are mechanical bindings produced only after the generated strict-QA packet exactly matches the curated decision and Claim.

The resulting manifest records the case-spec hash and hashes of the corpus, Unit index, accepted Claims, SQLite index, Gold JSONL, benchmark report, and verification report.

This is a real, executable release gate for the six closed predicates. It is not an independently annotated external novel corpus, does not prove open-domain understanding, and cannot grant final freeze authority. Every report and manifest keeps `may_freeze=false`.

## Run

```bash
python benchmark/release_benchmark.py --output build/release-benchmark
```

Successful execution requires:

- the immutable `release` profile to pass;
- `may_certify_release=true`;
- exact report recomputation to be accepted;
- zero hallucinations, overanswers, wrong answers, citation mismatches, evaluator failures, integrity failures, and ungrounded hard-negative labels.

The `release-acceptance` GitHub Actions workflow executes this benchmark from an isolated wheel installation on Python 3.10, 3.11, and 3.12 and uploads the complete evidence bundle.
