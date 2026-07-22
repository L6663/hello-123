# Text Knowledge Reader

Text Knowledge Reader is an auditable Skill for turning long text corpora into source-bound, typed knowledge projects with deterministic structure, evidence-grounded Claims, SQLite retrieval, strict answers, exact citations, and refusal when evidence is insufficient.

## Current status

```yaml
version: 5.9.0
canonical_branch: main
integrated_stage_6_r1_commit: 715fd64804d7a4ceffed8f08caa79e3c6045810a
accepted_runtime_head_commit: 62565a2b28cb14f65912f39b605ab10084364a07
completed_large_stages:
  - Stage 1
  - Stage 2
  - Stage 3
  - Stage 4
  - Stage 5
  - Stage 6
project_acceptance: passed
capability_domains_passed: 18_of_18
overall_weighted_score: 9.63
minimum_domain_score: 9.34
release_status: final
release_candidate_eligible: true
release_candidate_created: true
freeze_approved: true
```

Final acceptance details:

- `docs/stage-6-r1-final-acceptance.md`
- `acceptance/stage6-r1-acceptance-summary.json`

Project acceptance, final release approval, and repository freeze are complete. The repository is sealed at version 5.9.0.

## Processing chain

```text
raw source bytes
→ strict source identity and decoding
→ anomaly, contamination, and paratext candidates
→ deterministic source-covering Unit Index
→ evidence-bound typed Claim candidates
→ factual-status and polarity separation
→ entity, alias, timeline, conflict, and ambiguity normalization
→ hash-verified SQLite typed knowledge index
→ strict QA, exact citations, and deterministic refusal
→ recoverable engineering build, cache, audit, and package verification
```

## Supported typed Claims

```text
alias
defeats
located_in
permission
count
date
```

Belief, suspicion, rumor, accusation, hypothetical statements, questions, future intent, and negated propositions remain separately represented and cannot silently become positive canonical facts.

## Install

```bash
python -m pip install text_knowledge_reader_core-5.9.0-py3-none-any.whl
```

Check the installed Skill:

```bash
tkr-skill doctor
tkr-skill audit
tkr-skill profiles
tkr-skill show-profile balanced
```

Built-in profiles:

```text
balanced
strict
high-recall
```

## Build a project

```bash
tkr-project build corpus.txt \
  --outdir project \
  --state-dir .tkr-state/project \
  --profile balanced
```

A build key binds:

```text
raw source SHA-256
+ engineering profile SHA-256
+ engineering runtime version
+ knowledge-system version
```

The mutable lock, journal, and cache stay outside the immutable project.

Disable cache for a measurement run:

```bash
tkr-project build corpus.txt \
  --outdir project \
  --state-dir .tkr-state/project \
  --profile balanced \
  --no-cache
```

Reuse or atomically replace an existing project only through explicit actions:

```bash
tkr-project build corpus.txt --outdir project --reuse
tkr-project build corpus.txt --outdir project --force
```

## Verify and query

```bash
tkr-project verify project
tkr-project query project "陆川击败了谁？"
tkr-project query project "陆川击败了谁？" --output answer.json
tkr-project verify-answer project answer.json
```

Every query verifies project provenance, Manifest membership, source hashes, SQLite identity, and index report before answering.

Unsupported literary interpretation questions and supported predicates without sufficient typed evidence are refused.

## Stage commands

```bash
tkr-anomaly-scan corpus.txt --outdir stage1-anomaly
tkr-structure-index corpus.txt --outdir stage2-structure
tkr-semantic-extract corpus.txt --outdir stage3-semantics
```

Additional commands:

```text
tkr-chunk
tkr-claim-validate
tkr-entity-normalize
tkr-retrieval
tkr-strict-qa
tkr-gold-benchmark
tkr-release-freeze
tkr-anomaly-scan
tkr-structure-index
tkr-semantic-extract
tkr-project
tkr-skill
```

## Final acceptance evidence

### Cross-work contamination

```yaml
gold_blocks: 34
candidates: 34
candidate_precision: 1.0
block_recall: 1.0
character_precision: 0.970189304207459
character_recall: 0.9823395809895779
boundary_mae_characters: 45.705882352941174
```

### Structure

```yaml
decoded_characters: 3192465
heading_candidates: 877
combined_volume_chapter_headings: 546
combined_correct_as_chapter: 546
source_coverage_ratio: 1.0
```

### Held-out semantics

```yaml
expected_samples: 204
exact_type_status_polarity: 204
direct_assertions_indexable: 144_of_144
nonassertive_propositions_blocked: 60_of_60
extra_candidates: 0
```

### Long-corpus performance

```yaml
files: 5
decoded_characters: 3192465
total_elapsed_seconds: 73.13
throughput_decoded_characters_per_second: 43654.66
peak_rss_kb: 68888
verified_projects: 5_of_5
secure_query_p95_ms: 721.13
```

Performance was accepted from isolated per-source processes. Two multi-source shell batches exceeded their outer timeout; that transient harness behavior is disclosed in the final report rather than omitted.

### Strict QA and release Gold

```yaml
cases: 108
passed: 108
decision_accuracy: 1.0
answer_claim_accuracy: 1.0
refusal_precision: 1.0
refusal_recall: 1.0
citation_entailment_rate: 1.0
wrong_answers: 0
overanswers: 0
citation_mismatches: 0
measured_hallucinations: 0
```

## Security and integrity

The Skill rejects:

- symbolic links in source, project, state, cache, or package authority paths;
- absolute, duplicate, parent-traversal, or non-normalized Manifest paths;
- undeclared, missing, or non-regular project files;
- changed source, project, database, citation, or answer identities;
- source mutation during scanning;
- replacement decoding and unsupported silent recovery;
- nonassertive propositions promoted as facts;
- unverified projects or changed answer packets.

No source text is automatically deleted or rewritten.

## Package contents

The Wheel contains:

```text
SKILL.md
README.md
PROJECT_STATUS.yaml
Python modules
21 JSON Schemas
3 engineering Profiles
executable Examples
installation, security, and migration Docs
all console entry points
```

## Release boundary

```yaml
project_acceptance: passed
release_status: final
release_candidate_eligible: true
release_candidate_created: true
freeze_approved: true
```

This release is final and frozen. Any future modification requires an explicit unfreeze decision and a new version line.