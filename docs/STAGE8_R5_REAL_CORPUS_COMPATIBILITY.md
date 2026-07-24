# Stage 8-R5 — Long-form Literary Corpus Compatibility and Precision Hardening

## Scope

Stage 8-R5 records product defects discovered during an isolated engineering run on a large private long-form literary corpus. The private source text, file inventory, questions, observations, and private runtime artifacts are not included in this repository or GitHub Actions.

Because the corpus was used to discover and remediate product defects, it is now classified as an engineering regression corpus and is no longer eligible to serve as an untouched final private blind-acceptance corpus.

## Product defects found and fixed

### Numbered-section chapter convention

The corpus primarily used `第X节` as its top-level chapter heading. The prior Chapter Engine indexed only explicit `chapter` units, producing 26 canonical chapters from more than 2,300 real sections.

R5 now detects a high-confidence numbered-section convention when a source contains a large, consistent `第X节` sequence and no competing high-confidence chapter sequence. Those sections are promoted to chapter units without modifying source bytes. Compact low-confidence prose boundaries remain rejected.

### Cross-file volume context

Volume context now carries across split source files. A backward volume heading is ignored only when it occurs inside the same file after valid chapter content; an explicit volume at the start of a new file remains authoritative.

### Exact contamination-span isolation

A short footer or injected fragment previously contaminated an entire chapter. R5 subtracts exact contaminated spans while preserving clean chapter text as evidence. The fail-closed boundary remains unchanged for `non_body` and `needs_review` findings, which continue to block the complete chapter.

### Semantic precision

The deterministic fact layer was tightened against:

- negated or future/conditional victory claims;
- substring collisions in alias markers;
- adverbial, clause-like, demonstrative, or function-only subjects;
- approximate and malformed counts;
- transient or historical locations published as current locations;
- broad modal language promoted to permission facts.

The policy remains precision-first: unsupported or ambiguous material is refused or routed to review rather than published as canonical knowledge.

### Query compatibility

Closed typed queries now support natural count wording such as `X有几座Y`. The Stage 7 Literary query layer also supports directional Tier-A victory questions such as `X击败了谁` and `谁击败了X`, with exact evidence citations and fail-closed handling of contested facts.

## Isolated real-chain aggregate result

The final R5 rebuild produced the following aggregate engineering metrics:

- 7 source projects;
- 2,349 structural source units;
- 2,336 canonical cross-file chapters;
- 100% chapter-number coverage;
- 66 high-confidence deterministic facts from 252 candidates;
- 66 Tier-A literary assertions and 170 exact evidence anchors;
- 12,182 Evidence Units;
- 2,203 evidence-eligible chapters and 146 fail-closed chapters;
- 100% minimum Evidence coverage across all source projects;
- all Base, Literary, Evidence, and Chapter project verifications passed.

The Chapter Project preserved 12 source numbering gaps, 9 duplicate keys, and 6 ordering inversions as review findings instead of silently rewriting source structure.

## Regression evidence

- full repository tests: 651 passed;
- subtests: 84 passed;
- natural count strict QA returned a typed answer with exact Fact citation;
- Literary directional victory query returned a Tier-A assertion with exact source evidence;
- unsupported identity questions continued to refuse rather than infer.

## Authority and acceptance boundary

This is an engineering compatibility and usability milestone, not a formal private blind acceptance.

```yaml
real_private_corpus_used_for_engineering_validation: true
real_private_corpus_used_for_product_remediation: true
corpus_eligible_for_untouched_final_blind_acceptance: false
formal_gold_locked: false
formal_independent_roles_attested: false
private_blind_acceptance_performed: false
technical_acceptance_candidate_created: false
project_acceptance_performed: false
release_approved: false
freeze_approved: false
may_accept_project: false
may_release: false
may_freeze: false
```

A later formal blind acceptance requires a new untouched corpus, Gold locked before observations, distinct external roles, independent review, exact Candidate verification, and explicit owner approval.
