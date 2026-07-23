# Stage 8-R3 — Semantic Precision and Ambiguity Blocking

## Objective

Stage 8-R3 hardens deterministic literary extraction after an isolated five-source development regression exposed false-positive and identity-ambiguity publication risks. The private source text remains outside the repository and GitHub Actions.

## Product changes

- deterministic alias, location, defeat, count, and permission extraction now requires stronger noun-like and clause-bounded grammar;
- broad ability and modal phrases are review material rather than automatic canonical permissions;
- count numbers must be adjacent to an accepted cue, units stop at a supported classifier, and descriptive/discourse fragments are removed from subjects;
- subjectless or ambiguous permission assertions cannot enter the canonical index;
- unresolved same-surface entity ambiguity is materialized as an `AMBIGUOUS_ENTITY_REFERENCE` review conflict;
- every fact attached to an unresolved ambiguous entity is marked `contested`;
- fact `conflict_ids` remain real `cnf_*` identifiers, while the exact `amb_*` identity is bound in conflict details;
- runtime identities are bumped so projects and caches created before R3 cannot be reused as R3 evidence.

## Runtime identities

```text
Knowledge System: 6.0.0rc1-r3
Engineering Runtime: 6.0.0rc1-r3
Claim Validator: tkr-claim-validator-v2-r3
Entity Normalizer: tkr-entity-normalizer-v3
```

## Real development-regression result

The exact five-source corpus was rebuilt from fresh state and cache roots. Only aggregate, non-textual results are recorded publicly:

| Gate | Result |
|---|---:|
| Source projects verified | 5 / 5 |
| Structural units | 880 |
| Deterministic facts | 26 |
| Canonical facts | 24 |
| Contested facts | 2 |
| Ambiguity groups | 1 |
| Bound ambiguity conflicts | 1 |
| Literary chapters | 880 |
| Cross-file chapters | 863 |
| Evidence units | 1,926 |
| Claim edges | 26 |
| Literary evidence traceability | 100% |
| Evidence coverage | 100% |

The contradictory pair remains contested through one unresolved identity-ambiguity conflict. Neither value is silently selected, discarded, or published as canonical.

## Test gate

The local final runtime passed 609 repository tests before publication. The pull request must additionally pass the exact-head Python 3.10/3.11/3.12 package matrix, clean Wheel installs, reproducible-Wheel gate, private-artifact guard, and public execution-bundle scan.

## Acceptance boundary

This corpus is a development regression corpus because it was used to discover and remediate defects. It is ineligible to serve as the final untouched private blind corpus.

R3 does not create a technical Candidate and grants no product acceptance, release, or freeze authority. Final acceptance still requires a separate untouched private corpus, Gold locked before observation generation, distinct blind roles, two independent reviewers, a passing Stage 7 release report, exact verification, and explicit approval of the resulting Candidate ID.
