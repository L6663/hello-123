# Security Model

## Trust domains

Text Knowledge Reader `6.0.0rc1` separates six trust domains:

1. **Raw source** — immutable external bytes identified by SHA-256.
2. **Immutable knowledge projects** — verified Base, Literary, Evidence, Chapter, Event, Character, Reasoning, and Notion artifacts.
3. **Mutable engineering state** — locks, journals, cache records, and temporary build copies.
4. **Benchmark evidence** — Gold cases, answer observations, report, and independent recomputation.
5. **Product evidence** — Wheel, package matrix, reproducible builds, source provenance, CI record, audit, doctor, and documentation identities.
6. **Human authority records** — private blind attestation and explicit product-acceptance approval.

Mutable engineering state must never be stored inside immutable project or acceptance authority roots.

## Path safety

Source, project, state, cache, package, benchmark, and final-acceptance paths reject:

- symbolic links;
- unsafe or missing regular files;
- absolute stored artifact paths;
- parent traversal;
- duplicate declarations;
- paths escaping the selected root;
- output/state overlap;
- changed file sizes or SHA-256 identities;
- unsafe replacement backups.

Project Manifest paths are normalized relative POSIX paths. Acceptance candidate paths are relative to one explicit acceptance root.

## Exact filesystem membership

Every immutable project verifies its declared file set, hashes, report identities, database identities, and Manifest membership. Extra or missing files invalidate the relevant package.

The Stage 8 candidate separately binds all product evidence records. Candidate verification recomputes each artifact size and SHA-256 before interpreting its contents.

## Source integrity

The product:

- preserves original source bytes;
- performs strict decoding without replacement characters;
- never rewrites original source files in place;
- keeps physical source order separate from canonical-order candidates;
- keeps contamination and clean Evidence separate;
- binds source bundles and runtime files to the candidate Wheel.

Any source mutation or provenance mismatch blocks acceptance.

## Build lock and recovery

The external state directory contains one exclusive build lock with an ownership token, PID, hostname, start time, source SHA-256, and output path.

Stale-lock recovery is explicit and bounded. Recovery may publish only a project that passes the complete hash chain. If both the current destination and its backup are invalid, recovery stops.

## Cache

The cache key includes source, profile, engineering runtime, and knowledge-system identities. A cache hit also requires complete project verification and exact build-affecting policy equality.

An invalid cache record is non-authoritative and is discarded. Cache restoration uses a temporary copy, full verification, and atomic publication.

## Evidence and epistemic safety

A records require exact Evidence. B synthesis requires independent A-support branches. C interpretation requires attribution, limitations, support, and alternatives. H counterfactuals require a changed premise, rule, uncertainty, alternatives, and a non-canon label.

The engine never silently promotes H→C, C→B, or B→A. A graph marked `review_required` refuses outside provenance-only inspection.

## Query safety

Every query verifies its project and supporting reports before answering. Unsupported questions, insufficient evidence, conflict, ambiguity, contamination, tampering, malformed packets, or filesystem mismatch produce refusal or rejection.

A refusal is a correct result.

## Notion safety

The Notion projection uses physically separated A/B/C/H databases. Relation endpoints must resolve before application. Missing remote IDs enter review. Removed local pages become reversible archive candidates. Automatic remote deletion is forbidden.

## Literary benchmark safety

Stage 7 evaluates already-produced answer packets and never asks a model to grade itself. The release profile is non-compensating across twelve domains.

Hard blockers include:

- insufficient or unreviewed Gold coverage;
- wrong answers and overanswers;
- missing or wrong-node evidence;
- malformed layered packets;
- A/B/C/H leakage;
- measurable hallucinations;
- benchmark packets claiming acceptance, release, or freeze authority.

The report binds byte and logical SHA-256 identities and is fully recomputed by verification.

## Private blind boundary

A private blind attestation must explicitly bind:

- corpus, Gold, observation, and report hashes;
- Gold locked before the run;
- Gold hidden from the answer system;
- observations generated without Gold access;
- the private corpus not used during v6 development;
- distinct evaluator and Gold custodian;
- at least two additional independent reviewers.

Stage 8 can validate file identities, declared flags, role separation, timestamps, and exact report recomputation. It cannot independently prove an external human statement was truthful. The attestation therefore remains visible evidence and must not be fabricated by the model or CLI.

Do not place private corpus text, raw Evidence, credentials, or personal data in public CI logs or repository artifacts. Public records should expose hashes and the smallest necessary protocol metadata.

## Package and reproducible-build safety

Stage 8 package acceptance requires clean installations on Python 3.10, 3.11, and 3.12. All reports must agree on the package version, Wheel name, Wheel SHA-256, installed commands, Skill audit, and doctor status.

At least two candidate Wheels built with one fixed `SOURCE_DATE_EPOCH` must be byte-identical. A successful build alone grants no acceptance authority.

## Final acceptance authority

A technical candidate is immutable, hash-bound evidence with:

```yaml
technical_gate_passed: true
requires_explicit_approval: true
project_acceptance_performed: false
may_accept_project: false
release_candidate: false
may_release: false
may_freeze: false
```

The CLI cannot generate the explicit approval record. An approval must name the exact candidate ID and exact acceptance statement.

A valid acceptance Seal may set:

```yaml
project_acceptance_performed: true
may_accept_project: true
release_candidate: true
may_release: false
may_freeze: false
```

Project acceptance never implies publication or repository freeze. Those require later, separate explicit decisions.

Benchmark reports, CI runs, package reports, candidates, and models cannot self-grant authority. Changed approval or Seal bytes invalidate verification.

## Historical release boundary

The v5.9.0 release remains frozen and unchanged. Stage 8 operates on a separate v6 line and does not silently unfreeze, overwrite, or reinterpret historical release evidence.

## Reporting a vulnerability

Do not include private corpus contents, raw Evidence, credentials, approval secrets, or personally sensitive project data in public reports. Report the smallest reproducible case, affected version, platform, command, expected boundary, and observed result.

## Acceptance boundary

Passing Stage 8 engineering CI proves that the productization and acceptance mechanism works. It does not prove that the real private blind protocol has been executed.

Until actual private blind evidence and an explicit approval exist:

```yaml
private_blind_acceptance_performed: false
project_acceptance_performed: false
release_candidate: false
may_release: false
may_freeze: false
```
