# Stage 8-R4 — Final Private Intake Lock and Non-Authoritative Simulation

## Scope

This record reconciles two safe milestones completed after Stage 8-R3:

1. exact-byte intake and owner attestation for the untouched final private corpus candidate;
2. a non-authoritative acceptance simulation using only the public R3 execution bundle.

No private corpus text, file-level corpus inventory, Gold content, questions, observations, reviewer packets, or scoring details are stored in this repository or GitHub Actions.

## Final private intake lock

- corpus ZIP SHA-256: `be0899cb697e7726991be4026f1ddf71f61bb7b925bd87dd2bb63de38b5b8622`;
- exact bytes received and recomputed outside the repository;
- owner untouched-use exclusion statement recorded;
- source encoding, newline, byte, character, and archive-path identities checked outside the repository;
- known structural anomalies accepted as raw source properties;
- source bytes remain unmodified;
- corpus has not been used for product remediation, rule tuning, or simulation observations;
- private runtime remains outside the repository.

The intake lock does not authorize observation generation. Formal use remains blocked until distinct blind roles are attested and Gold is hash-locked before any answer-system run.

## Non-authoritative simulation

The simulation used the public Stage 8-R3 execution bundle only.

- R3 source commit: `afc4eb732dfc749662697d3e472cce0689239ae9`;
- public execution bundle SHA-256: `6f8381f4df7bd224e47e7e066986df1e891d264a7b5942b4e44ac2e01bfce39b`;
- Wheel SHA-256: `ba270e9571cc7eb36af66df899a6e94b673fd1d189038a578acfbef30aa574a3`;
- focused final-acceptance, Gold, role, provenance, authority, and tamper tests: 57 passed;
- full repository regression: 609 passed;
- Skill Audit: passed with zero findings;
- Skill Doctor: 7/7 passed;
- private-artifact path guard: passed with zero findings.

The final private corpus was not used as simulation input. No formal observations, Stage 7 release report, Candidate, approval, or Seal were generated.

## Current formal gate

Formal Stage 7 / Stage 8 execution remains blocked on external evidence that the answer system cannot self-create:

- distinct Gold Custodian;
- distinct Evaluator;
- two independent Reviewers;
- completed role-separation attestation;
- Gold SHA-256 lock created before observation generation;
- case statistics satisfying the release profile;
- evidence that Gold remains inaccessible to the answer-system operator.

## Authority state

```yaml
simulation_only: true
final_private_corpus_raw_identity_locked: true
owner_untouched_attestation_recorded: true
final_private_corpus_used_for_simulation: false
final_private_corpus_used_for_remediation: false
blind_roles_attested: false
gold_locked: false
answer_system_run_started: false
private_blind_acceptance_performed: false
technical_acceptance_candidate_created: false
explicit_acceptance_approval_received: false
final_acceptance_seal_created: false
project_acceptance_performed: false
release_candidate: false
release_approved: false
freeze_approved: false
may_accept_project: false
may_release: false
may_freeze: false
```

## Next valid action

Receive completed role-separation and Gold-lock receipts containing hashes, timestamps, case counts, domain counts, refusal-case counts, and verification references only. Do not provide Gold content, standard answers, questions, scoring rubrics, or private observations to the answer system.
