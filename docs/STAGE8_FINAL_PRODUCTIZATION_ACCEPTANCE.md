# Stage 8 — Final Productization and Acceptance

## Objective

Stage 8 turns the integrated v6 literary engine into an installable, auditable release-candidate product and defines the only valid route to final project acceptance.

It does **not** infer acceptance from a high test score, a successful CI run, a generated Wheel, or a Stage 7 benchmark report. Those are technical evidence only.

The authority chain is intentionally separated:

1. **Technical candidate** — all evidence is recomputed and hash-bound, but every authority flag remains false.
2. **Explicit product-acceptance approval** — a separate human-controlled record must name the exact candidate ID.
3. **Acceptance Seal** — project acceptance and Release Candidate eligibility become true; publication and freeze remain false.
4. **Release or freeze** — requires a later, separate explicit decision and is outside automatic Stage 8 execution.

## Product version

The Stage 8 engineering line is packaged as:

```text
6.0.0rc1
```

This denotes a release candidate, not a final public release. The historical v5.9.0 release remains frozen and unchanged.

## Required evidence

A final-acceptance technical candidate binds the following artifact roles.

### Singletons

- `wheel` — canonical v6 Wheel;
- `skill_audit` — zero-finding Stage 8 Skill audit;
- `skill_doctor` — fully passing runtime doctor report;
- `literary_cases` — Stage 7 release-profile Gold cases;
- `literary_observations` — answers generated without Gold access;
- `literary_report` — passing Stage 7 release-profile report;
- `literary_verification` — independent exact recomputation;
- `blind_attestation` — private blind protocol attestation;
- `engineering_validation` — exact CI source commit and gate summary;
- `reproducible_build_report` — byte-reproducibility report;
- `source_bundle` and `source_provenance` — source-to-Wheel binding;
- `project_status`, `skill_contract`, and `readme` — product documentation identities.

### Repeated roles

- exactly three `package_acceptance` reports, for Python 3.10, 3.11, and 3.12;
- at least two `reproducible_wheel` artifacts with byte-identical hashes.

Every artifact must be a safe regular file under the selected acceptance root. Absolute paths, parent traversal, symbolic links, missing files, duplicate declarations, size changes, and hash changes are rejected.

## Private blind evaluation contract

The private blind attestation is an explicit protocol record, not a model-generated claim. It binds:

- corpus SHA-256 identities, which must exactly equal the source identities in Stage 7 Gold;
- Gold, observation, and report file hashes;
- confirmation that Gold was locked before the run;
- confirmation that the answer system could not access Gold;
- confirmation that observations were generated without Gold access;
- confirmation that the private corpus was not used during v6 development;
- a distinct evaluator, Gold custodian, and at least two independent reviewers;
- an approved status, statement, and UTC timestamp.

Stage 8 can verify the structure, identities, separation of named roles, and file bindings. It cannot independently prove a human attestation was truthful; therefore the attestation remains visible evidence rather than hidden automation.

## Stage 7 release benchmark gate

The literary benchmark must:

- use `policy_profile=release`;
- contain at least 120 cases;
- pass with an empty blocker list;
- independently recompute exactly;
- bind the same private corpus identities as the blind attestation;
- keep project-acceptance, release, and freeze authority false.

Any wrong answer, overanswer, citation mismatch, malformed answer packet, A/B/C/H leakage, measurable hallucination, or unauthorized authority flag blocks Stage 8.

## Package and reproducibility gate

All three package reports must agree on:

- release version;
- Wheel filename;
- Wheel SHA-256;
- the complete required console-script set;
- passing installed Skill audit and doctor results.

The Python matrix is exactly 3.10, 3.11, and 3.12.

The reproducible-build report must bind the same version, `SOURCE_DATE_EPOCH`, Wheel name, and Wheel SHA-256 as the package reports. At least two separately built Wheels must be byte-identical.

## Engineering validation gate

The engineering validation record binds:

- exact source commit;
- successful GitHub Actions run ID;
- positive focused-test count;
- full repository regression success;
- public Schema contract success;
- CLI contract success;
- Python 3.10/3.11/3.12 package matrix success;
- reproducible Wheel success.

It must keep project acceptance, release, and freeze authority false.

## Commands

Installed command:

```bash
tkr-final-acceptance prepare --help
tkr-final-acceptance verify --help
tkr-final-acceptance seal --help
tkr-final-acceptance verify-seal --help
```

Bundled Skill command:

```bash
python scripts/tkr.py acceptance prepare --help
python scripts/tkr.py acceptance verify --help
python scripts/tkr.py acceptance seal --help
python scripts/tkr.py acceptance verify-seal --help
```

### Prepare a technical candidate

```bash
tkr-final-acceptance prepare \
  --root ACCEPTANCE_ROOT \
  --version 6.0.0rc1 \
  --source-commit COMMIT_SHA \
  --source-date-epoch UNIX_SECONDS \
  --artifact wheel=PATH_TO_WHEEL \
  --artifact skill_audit=skill-audit.json \
  --artifact skill_doctor=skill-doctor.json \
  --artifact literary_cases=literary-cases.jsonl \
  --artifact literary_observations=literary-observations.jsonl \
  --artifact literary_report=literary-report.json \
  --artifact literary_verification=literary-verification.json \
  --artifact blind_attestation=private-blind-attestation.json \
  --artifact engineering_validation=engineering-validation.json \
  --artifact reproducible_build_report=reproducible-build.json \
  --artifact source_bundle=source.bundle \
  --artifact source_provenance=source-provenance.json \
  --artifact project_status=PROJECT_STATUS.yaml \
  --artifact skill_contract=SKILL.md \
  --artifact readme=README.md \
  --artifact package_acceptance=package-3.10.json \
  --artifact package_acceptance=package-3.11.json \
  --artifact package_acceptance=package-3.12.json \
  --artifact reproducible_wheel=build-a.whl \
  --artifact reproducible_wheel=build-b.whl \
  --output final-acceptance-candidate.json
```

The candidate always contains:

```yaml
technical_gate_passed: true
requires_explicit_approval: true
project_acceptance_performed: false
may_accept_project: false
release_candidate: false
may_release: false
may_freeze: false
```

### Verify a candidate

```bash
tkr-final-acceptance verify \
  final-acceptance-candidate.json \
  --root ACCEPTANCE_ROOT
```

Verification recomputes every artifact identity and every technical gate. It does not grant authority.

### Explicit approval record

The approval must be created separately and use this exact decision:

```json
{
  "schema_version": "tkr-final-acceptance-approval-v1",
  "candidate_id": "final_acceptance_candidate_<24 hex>",
  "release_version": "6.0.0rc1",
  "source_commit": "<40 hex>",
  "approver": "<explicit approver identity>",
  "decision": "approve_final_product_acceptance",
  "statement": "I explicitly approve final product acceptance for final_acceptance_candidate_<24 hex>.",
  "approved_at_utc": "YYYY-MM-DDTHH:MM:SSZ"
}
```

The CLI never fabricates this approval.

### Seal acceptance

```bash
tkr-final-acceptance seal \
  final-acceptance-candidate.json \
  final-acceptance-approval.json \
  --root ACCEPTANCE_ROOT \
  --output final-acceptance-seal.json
```

A valid Seal sets:

```yaml
project_acceptance_performed: true
may_accept_project: true
release_candidate: true
may_release: false
may_freeze: false
```

The Release Candidate is technically accepted but not authorized for publication or repository freeze.

## Standard artifacts

Stage 8 introduces:

```text
private-blind-attestation.json
package-3.10.json
package-3.11.json
package-3.12.json
engineering-validation.json
reproducible-build.json
final-acceptance-candidate.json
final-acceptance-approval.json   # external explicit decision
final-acceptance-seal.json       # only after approval
```

## Current acceptance boundary

Merging the Stage 8 engineering implementation proves that the acceptance mechanism, package contracts, product documentation, CI matrix, and adversarial tests work.

It does **not** mean the real private blind corpus has been evaluated. Until those real artifacts exist and an explicit approval record is supplied:

```yaml
private_corpus_acceptance_performed: false
project_acceptance_performed: false
release_candidate: false
may_release: false
may_freeze: false
```
