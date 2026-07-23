# Stage 8-R1 — Private Acceptance Operations

## Purpose

Stage 8-R1 is the operational completion phase for Text Knowledge Reader v6. It begins after the Stage 8 engineering framework is integrated and ends only when a real private blind benchmark has produced a verified technical Candidate and the repository owner has explicitly approved that exact Candidate ID.

This phase is tracked by GitHub issue #37.

## Stewardship model

The assistant coordinates and executes all safe engineering, evidence assembly, packaging, verification, CI, documentation, and repository integration work. The repository owner remains the sole explicit final product-acceptance approver.

The following authority boundaries are immutable:

- the assistant may prepare and verify a technical Candidate;
- the assistant may not invent or self-issue the product-acceptance approval;
- release approval is separate from product acceptance;
- repository freeze approval is separate from both acceptance and release.

## Private-data boundary

Private corpus bytes, Gold cases, answer observations, reviewer packets, and the private blind attestation must remain outside this public repository and outside GitHub Actions.

The recommended runtime root is outside the Git checkout:

```text
<secure-parent>/.tkr-private-acceptance/
```

Do not place the acceptance root under the repository directory. The repository includes a path-only leak guard as defense in depth, but the primary protection is physical separation.

The guard intentionally does not inspect contents. It only examines tracked path names so private material cannot be echoed into CI logs.

Run it locally with:

```bash
python -m tkr.private_artifact_guard --root .
```

## Recovered private assets

The project owner’s File Library currently contains:

- the original multi-file `步剑庭` corpus used by earlier engineering acceptance;
- a 50-question large-corpus blind bank;
- a 40-question fiction multi-file blind bank;
- a 40-question technical multi-file blind bank.

The three question banks total 130 questions, which exceeds the Stage 7 release minimum of 120. Question count alone does not satisfy the release profile: every required domain, refusal quota, reviewer requirement, source identity, and exact recomputation gate still applies.

File Library search can locate and inspect these files, but the active acceptance runtime must receive exact regular-file bytes before SHA-256 recomputation and local command execution are valid.

## Required role separation

A valid private blind run requires distinct identities for:

1. Gold custodian;
2. answer-system operator;
3. evaluator;
4. independent reviewer A;
5. independent reviewer B.

The evaluator, Gold custodian, and reviewers must be distinct. Gold must be locked before the answer-system run and unavailable to the answer system while observations are generated.

The assistant may coordinate the process but must not collapse these roles or attest to independence that did not occur.

## Execution sequence

### 1. Recover and bind exact source bytes

- restore the private source files into the isolated acceptance root;
- compute SHA-256, byte size, encoding, and line-ending identity;
- compare against prior source identities where available;
- stop on any mismatch until the provenance difference is resolved.

### 2. Freeze release-profile Gold

- map at least 120 cases across all 12 Stage 7 domains;
- include at least 8 cases per domain;
- include at least 24 refusal/safety cases;
- bind every case to exact corpus identities and evidence spans;
- require two independent reviewers or documented adjudication;
- lock the Gold artifact before answer generation.

### 3. Generate blind observations

- build the v6 knowledge projects from the private corpus;
- run the answer system without Gold access;
- preserve answer packets, citations, status, confidence, and logs;
- do not mutate Gold after seeing the observations.

### 4. Evaluate and recompute

- evaluate every observation against locked Gold;
- adjudicate reviewer disagreements;
- generate the Stage 7 release report;
- independently recompute the report and produce verification;
- block on any wrong answer, overanswer, citation mismatch, hallucination, malformed packet, epistemic-layer leakage, or unauthorized authority flag.

### 5. Assemble Stage 8 evidence

Generate and bind:

- private blind attestation;
- Python 3.10, 3.11, and 3.12 package acceptance reports;
- canonical Wheel and at least two byte-identical reproducible Wheels;
- reproducible-build report;
- source bundle and provenance;
- successful exact-commit engineering validation;
- zero-finding Skill audit;
- passing Skill doctor;
- `PROJECT_STATUS.yaml`, `SKILL.md`, and `README.md` identities.

### 6. Prepare and verify Candidate

Run `tkr-final-acceptance prepare`, followed by a separate `verify` invocation against the same isolated acceptance root.

A valid Candidate must still state:

```yaml
project_acceptance_performed: false
may_accept_project: false
release_candidate: false
may_release: false
may_freeze: false
```

### 7. Request explicit approval

Present the repository owner with:

- exact Candidate ID;
- source commit;
- release version;
- all domain, correctness, and safety scores;
- blocker count;
- corpus and artifact hash summary;
- independent verification result.

Only the repository owner may supply the exact approval record naming that Candidate ID.

### 8. Seal, release, and freeze

After explicit Candidate approval, create and verify the Acceptance Seal. Public release and repository freeze each require a later, separate explicit approval.

## Current blocking condition

The private files are discoverable in File Library but are not mounted as exact regular-file bytes in the active acceptance runtime. Candidate generation remains fail-closed until that byte-level boundary is resolved.

No score, Candidate ID, approval, seal, release, or freeze authority may be inferred from earlier engineering acceptance reports.
