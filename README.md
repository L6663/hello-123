# Text Knowledge Reader — staged hardening workspace

Text Knowledge Reader is developed as a sequence of independently reviewable implementation stages. Phase 9 substages optimize the Skill itself; they do not certify the project, declare acceptance, create a release candidate, or authorize a freeze. Project-level acceptance is deferred until the final integrated product is complete.

## Current repository status

```yaml
main_baseline: c76d3b39e1a7d58f38b78c837e25aafff3ba2b07
main_version: 5.8.0-alpha1
development_version: 5.9.0-alpha1
completed_development_stages:
  - Phase 9.0
  - Phase 9.1
  - Phase 9.2
  - Phase 9.3
current_development_stage: Phase 9.4
current_development_scope: anomaly_and_corpus_contamination_candidate_detection
development_mode: skill_optimization_only
intermediate_project_acceptance: disabled
project_acceptance: deferred_until_final_integrated_product
development_status: alpha
release_candidate: false
freeze_approved: false
```

The canonical Phase 9 development base is `feature/phase9-0-baseline-cleanup`, created directly from `main`. Phase 9.4 development must branch from this base so that the completed Phase 9.0–9.3 implementation remains intact. The earlier encoded-payload draft PR #9 is closed and is not an accepted implementation source.

The branch `feature/anomaly-pollution-v5.9-phase9.4` was created directly from `main` before the completed Phase 9.2/9.3 lineage was re-confirmed. It is not the Phase 9.4 implementation source and must not be merged. The canonical Phase 9.4 implementation branch is `feature/phase9-4-anomaly-contamination`.

## Implemented stack on `main`

- **v5.2 Phase 2:** deterministic bounded chunking;
- **v5.3 Phase 3:** typed Claim evidence validation;
- **v5.4 Phase 4:** entity, alias, homonym, timeline, and conflict normalization;
- **v5.5 Phase 5:** hash-verified SQLite indexing and predicate-aware hybrid retrieval;
- **v5.6 Phase 6:** strict answers, evidence packets, citation entailment, and refusal decisions;
- **v5.7 Phase 7:** immutable Gold Benchmark coverage, accuracy, refusal, citation, and hallucination gates;
- **v5.8 Phase 8:** artifact-chain manifests, reproducible wheel checks, Git-backed source provenance, explicit approval, and freeze seals.

## Phase 9 development lineage

The following work is implemented on the canonical Phase 9 development base and is not yet integrated into `main`:

- **Phase 9.0:** clean baseline, version identity, and stage boundaries;
- **Phase 9.1:** shared bounded-memory streaming SHA-256 utilities;
- **Phase 9.2:** raw-byte source identity admission;
- **Phase 9.3:** strict encoding selection and Unicode-quality inspection.

These stages are development-complete. That status means their intended Skill changes are present in the Phase 9 development line; it does not mean that the final project has passed project acceptance.

## Remaining integration layers

The following capabilities are not yet integrated into `main` and must not be described as final-product capabilities:

- anomaly and cross-work contamination candidate detection;
- heading candidate detection and recovery;
- deterministic Unit Index generation;
- Unit continuity and structure validation;
- conservative Claim candidate extraction before Phase 3 validation;
- migration of existing large-artifact hashing call sites to the shared streaming helper;
- raw-corpus end-to-end orchestration;
- independent long-corpus evaluation and result-drift measurement;
- final integrated packaging and project acceptance.

## Phase 9 — full ingestion integration

Phase 9 connects the existing Phase 2–8 components to a raw-corpus entry point. It is intentionally split into narrow implementation stages so each Skill change can be reviewed, corrected, and reverted independently.

| Stage | Skill optimization scope | Project acceptance during stage |
|---|---|---:|
| 9.0 | clean baseline, version identity, phase boundaries | No |
| 9.1 | shared streaming SHA-256 module | No |
| 9.2 | source identity admission | No |
| 9.3 | encoding and Unicode inspection | No |
| 9.4 | anomaly and corpus-contamination candidates | No |
| 9.5 | heading candidate detection | No |
| 9.6 | deterministic Unit Index generation | No |
| 9.7 | Unit continuity and structure validation | No |
| 9.8 | Claim candidate schema | No |
| 9.9 | six-predicate deterministic extraction | No |
| 9.10 | fact, belief, suspicion, rumor, and accusation separation | No |
| 9.11 | constrained model-extraction task interface | No |
| 9.12 | raw text to Claim-candidate orchestration | No |
| 9.13 | private long-corpus evaluation contracts | No |
| 9.14 | Skill documentation and Alpha package layout | No |
| 9.15 | final integration assembly and acceptance handoff | No |

The complete Python 3.10/3.11/3.12 regression matrix, full long-corpus execution, performance measurement, drift comparison, final packaging audit, and project-level acceptance are deferred until all implementation stages and the final integrated product are complete.

Focused unit tests and deterministic developer checks may be added while implementing a stage to prevent regressions. They are development evidence only and must never be reported as project acceptance, release certification, or final-product validation.

## Phase 9.1 result — shared streaming SHA-256

`tkr/hashing.py` provides a bounded-memory hashing foundation for later admission and artifact migration work:

- `sha256_stream()` hashes binary streams from their current position;
- `sha256_file()` hashes regular files without `read_bytes()`;
- `inspect_file()` returns deterministic path, size, SHA-256, and block-size metadata and rejects files that change during hashing;
- `verify_file_sha256()` validates a 64-character hexadecimal expectation and performs exact comparison;
- the default block size is 4 MiB and invalid block sizes, text streams, missing paths, and directories are rejected.

The focused Phase 9.1 suite contains 11 development tests covering empty files, UTF-8 Chinese text, multi-block bounded reads, current stream position, metadata output, uppercase expected hashes, mismatch detection, malformed hashes, invalid block sizes, missing files, and directories. Existing Phase 2–8 call sites are intentionally not migrated in this stage. These tests are not project acceptance.

## Phase 9.2 result — source identity admission

`tkr/admission.py` performs raw-byte source identity admission without decoding or modifying the source:

- only regular files are inspected and all byte hashing uses the Phase 9.1 streaming helper;
- `.txt` and `.md` suffixes are supported case-insensitively;
- the report binds the exact SHA-256, byte size, filename, suffix, stable content-derived source ID, empty-file state, NUL presence, raw newline family, newline counts, and byte-level line count;
- CRLF sequences split across read-block boundaries are counted exactly once;
- files with mixed newline families, empty content, or NUL bytes are routed to `review` rather than silently accepted;
- unsupported suffixes are marked `unsupported` with an explicit blocker;
- NUL-bearing input keeps `line_count=null` and `line_count_reliable=false` because encoding inspection has not yet distinguished UTF-16 from binary content.

The focused Phase 9.2 suite contains 11 development tests covering supported TXT and Markdown files, content-derived identity, LF, CRLF boundary handling, mixed newlines, trailing and non-trailing lines, empty input, UTF-16-like NUL bytes, unsupported suffixes, report serialization, missing files, and directories. No decoding, normalization, contamination analysis, heading recognition, full regression, or project acceptance is performed in this stage.

## Phase 9.3 result — encoding and Unicode inspection

`tkr/encoding_inspection.py` performs bounded-memory strict decoding and Unicode-quality inspection:

- UTF-8, UTF-8 BOM, UTF-16 LE BOM, and UTF-16 BE BOM are decoded strictly;
- BOM-free UTF-16 is selected only when byte-position or encoded-newline signals exist and remains a `review` candidate;
- GB18030 is a strict fallback candidate and remains `review`, because successful legacy decoding does not prove the historical source encoding;
- UTF-32 BOMs are detected explicitly and rejected as unsupported rather than being misclassified as UTF-16;
- incremental decoders preserve multibyte sequences across read-block boundaries;
- the report records the selected decoder, selection basis, confidence, attempted decoders, decoded character and line counts, decoded newline family, replacement characters, abnormal controls, Unicode noncharacters, NUL characters, and embedded BOM characters;
- strict decoding failure produces an explicit blocker and never substitutes replacement decoding.

The focused Phase 9.3 suite contains 15 development tests covering UTF-8 Chinese text, UTF-8 BOM, UTF-16 LE/BE BOMs, BOM-free UTF-16 review routing, GB18030 fallback, replacement characters, controls, NUL, Unicode noncharacters, embedded BOMs, unsupported UTF-32 BOMs, invalid byte sequences, unsupported suffixes, empty files, missing paths, and directories. Text normalization, anomaly classification, contamination analysis, heading recognition, full regression, and project acceptance remain outside this stage.

## Phase 9.4 active scope — anomaly and contamination candidates

Phase 9.4 now has one objective: add conservative, auditable anomaly and corpus-contamination candidate detection to the Skill implementation inherited from Phase 9.3.

This stage may implement detector code, typed findings, deterministic identifiers, span evidence, severity and review routing, output serialization, CLI integration, and narrow developer tests. It must not run the final project acceptance corpus, issue a project pass/fail decision, score the completed project, create a release candidate, or authorize a freeze.

Real corpora may be used later by the final integrated-product acceptance workflow. Intermediate corpus scans are not Phase 9.4 deliverables and must not be represented as Skill completion.

## Current console commands

Only commands backed by code already present in the repository are registered:

```text
tkr-chunk
tkr-claim-validate
tkr-entity-normalize
tkr-retrieval
tkr-strict-qa
tkr-gold-benchmark
tkr-release-freeze
```

Phase 0, Phase 1, extraction, long-corpus evaluation, and full-pipeline commands will be registered only when their implementations exist. Command registration is an implementation change, not an acceptance decision.

## Evidence and interpretation boundary

The deterministic runtime is responsible for source integrity, stable structure, evidence localization, typed factual validation, strict retrieval, and refusal when evidence is insufficient. It must not present character motivation, foreshadowing resolution, theme, or narrative interpretation as mechanically proven fact.

Future novel-semantic records will distinguish:

- **A:** directly stated source fact;
- **B:** high-confidence synthesis supported by multiple source passages;
- **C:** literary interpretation;
- **X:** contamination, conflict, missing text, or insufficient evidence.

A character's suspicion, rumor, accusation, or stated belief may itself be an A-level fact when directly quoted, while the proposition being suspected remains unconfirmed.

## Phase 7 contract

Phase 7 evaluates strict QA against a bound JSONL Gold set. A passing release-profile report may set `may_certify_release=true`, but Phase 7 must always keep `may_freeze=false`.

## Phase 8 contract

Phase 8 separates technical verification from release authority. A technical candidate binds exact artifacts, source provenance, package version, and reproducible wheel evidence. It cannot authorize itself. A freeze seal requires a separate explicit approval record matching the verified candidate.

The current approval model is an operator assertion and is not described as a cryptographically authenticated identity signature.

## Development rule

Each Phase 9 implementation substage must provide:

1. a narrow Skill implementation scope;
2. explicit inputs, outputs, and safety boundaries;
3. focused developer checks where needed to prevent regressions;
4. no hidden encoded source payloads;
5. no intermediate project acceptance, certification, release-candidate, or freeze claim;
6. no use of a real-corpus scan as a substitute for Skill implementation;
7. project-level acceptance only after the final integrated product is complete.
