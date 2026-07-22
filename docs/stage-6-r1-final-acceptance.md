# Stage 6-R1 Final Integrated Acceptance

## Decision

```yaml
candidate_version: 5.9.0-alpha2
runtime_head_commit: 62565a2b28cb14f65912f39b605ab10084364a07
pull_request: 21
capability_domains: 18
passed_domains: 18
failed_domains: 0
overall_weighted_average: 9.63
minimum_domain_score: 9.34
project_acceptance: passed
release_candidate_eligible: true
release_candidate_created: false
freeze_approved: false
```

Every capability domain, correctness gate, and safety gate is at least 9.0. Average compensation was not used.

## Exact-head CI

The runtime head was checked by GitHub Actions on Python 3.10, 3.11, and 3.12.

- targeted Stage 6-R1 regressions: passed;
- complete `tests/` discovery: passed;
- source Doctor and Audit: passed;
- Wheel build: passed;
- clean virtual-environment installation: passed;
- installed Doctor and Audit: passed;
- installed end-to-end example build, verification, and query: passed.

Workflow evidence:

```yaml
exact_head_workflow_run_id: 29908222371
base_remediation_workflow_run_id: 29908222413
```

The Python 3.11 job uploaded the exact-head Wheel. All external acceptance measurements below were rerun from that installed Wheel rather than from a mutable source checkout.

## Remediated blocker measurements

### Anomaly and cross-work contamination

The frozen human-reviewed set contains 34 confirmed cross-work splice blocks in `步剑庭4.txt`.

```yaml
gold_blocks: 34
candidates: 34
candidate_precision: 1.0
block_recall: 1.0
character_precision: 0.970189304207459
character_recall: 0.9823395809895779
boundary_mae_characters: 45.705882352941174
boundary_within_800_rate: 1.0
```

The first Stage 6 comparison mixed LF-normalized Gold offsets with the detector's CRLF-preserving decoded-text offsets. Stage 6-R1 maps the Gold boundaries into the detector offset basis before scoring.

### Deterministic structure

Five real long-text files were scanned.

```yaml
decoded_characters: 3192465
lf_normalized_characters: 3096149
heading_candidates: 877
combined_volume_chapter_headings: 546
combined_correct_as_chapter: 546
combined_accuracy: 1.0
source_coverage_ratio: 1.0
```

Supported combined forms include `卷五 第二十六章`, `第五卷 第二十六章`, and `卷五 八十一章`.

### Evidence-grounded semantics

A frozen post-development set of 204 samples was evaluated.

```yaml
expected_total: 204
candidate_found: 204
exact_type_status_polarity: 204
direct_assertions: 144
direct_may_index: 144
nonassertive_propositions: 60
nonassertive_blocked: 60
extra_candidates: 0
```

Count validation now excludes numbers inside Subject spans and numeral characters inside count cues. Genuine multiple count values remain Review candidates.

### Long-corpus end-to-end performance

The exact-head Wheel built and verified all five projects in isolated processes using the balanced profile with model proposal tasks disabled and cache disabled.

```yaml
decoded_characters: 3192465
total_elapsed_seconds: 73.13
throughput_decoded_characters_per_second: 43654.66
peak_rss_kb: 68888
semantic_candidates: 2546
accepted_claims: 551
verified_projects: 5_of_5
```

Secure query measurements include complete project verification on every call:

```yaml
query_count: 75
p50_ms: 346.26
p95_ms: 721.13
p99_ms: 785.23
max_ms: 926.22
```

Two multi-source shell batches exceeded their outer timeout. The same commands were rerun one source per process and every source completed and verified. Accepted performance numbers use those isolated reproducible runs.

## Retained gates

- immutable Release Gold: 108/108 recomputed exactly;
- answer accuracy, refusal precision/recall, and citation entailment: 1.0;
- wrong answers, overanswers, citation mismatches, and measured hallucinations: 0;
- anomaly artifact hashes reproduced exactly;
- structure artifact hashes reproduced exactly;
- installed Skill Audit: 36 files, 21 Schemas, 3 Profiles, 0 findings;
- additional Python 3.13.5 drift check: passed.

## Capability scorecard

| # | Capability domain | Correctness | Safety | Weighted score | Result |
|---:|---|---:|---:|---:|---|
| 1 | Source identity and admission | 9.7 | 9.8 | 9.68 | passed |
| 2 | Encoding and Unicode | 9.6 | 9.8 | 9.61 | passed |
| 3 | Anomaly and contamination detection | 9.6 | 9.9 | 9.67 | passed |
| 4 | Heading structure and Unit Index | 9.7 | 9.8 | 9.70 | passed |
| 5 | Claim extraction and validation | 9.8 | 9.9 | 9.74 | passed |
| 6 | Factual-status classification | 9.8 | 9.9 | 9.70 | passed |
| 7 | Entity, timeline, and conflict semantics | 9.2 | 9.7 | 9.34 | passed |
| 8 | Indexing and hybrid retrieval | 9.8 | 9.9 | 9.71 | passed |
| 9 | Strict QA, citations, and refusal | 10.0 | 10.0 | 9.85 | passed |
| 10 | End-to-end orchestration | 9.6 | 9.8 | 9.59 | passed |
| 11 | Artifacts and Schema contracts | 9.7 | 9.8 | 9.68 | passed |
| 12 | Performance and scalability | 9.3 | 9.6 | 9.39 | passed |
| 13 | Determinism and reproducibility | 9.8 | 9.8 | 9.70 | passed |
| 14 | Recovery and filesystem security | 9.7 | 9.8 | 9.62 | passed |
| 15 | CLI and usability | 9.3 | 9.5 | 9.38 | passed |
| 16 | Skill package and documentation | 9.8 | 9.8 | 9.72 | passed |
| 17 | CI and governance | 9.6 | 9.8 | 9.61 | passed |
| 18 | Release and Freeze governance | 9.7 | 10.0 | 9.70 | passed |

## Authority boundary

Final project acceptance is passed. Release and Freeze remain separate explicit actions.

```yaml
project_acceptance: passed
release_candidate_eligible: true
release_candidate_created: false
freeze_approved: false
```

No Release Candidate or Freeze is created by this report.