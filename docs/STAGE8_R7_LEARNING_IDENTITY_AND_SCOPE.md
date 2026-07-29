# Stage 8-R7 — Learning Identity, Scope, and Reusable Results

## Objective

Stage 8-R7 closes the learning-quality gaps found by the controlled R6 long-form simulation. The target is not narrow fact replay. The target is stable, inspectable, reusable learning across chapters, volumes, and multiple books.

## Implemented capabilities

### Stable book identity

Every Literary input is bound to a `book_id` and `book_title`. Multiple files from the same book may share one identity. Identical character names in different books remain separate. Automatic inference removes common volume, part, copy, and numeric filename suffixes; explicit CLI identities override inference.

### Same-book entity consolidation

Entity profiles are consolidated by canonical name and aliases only within one book. Mentions, source projects, chapter IDs, predicates, aliases, and storylines are merged into one stable source-ordered learning identity. Review-only fragment entities never merge into accepted identities.

### Structural chapter discipline

Only narrative chapter units become chapter learning cards and deep-learning tasks. Volume and part headings remain structural context and are not counted as chapters.

### Multi-book isolation

A query that matches the same name in more than one book refuses unless the book title, `book_id`, or an explicit cross-book analysis request resolves the scope. Cross-book mixing is false by default.

### Reusable learning queries

Queries return learned statements rather than only counters or IDs. Supported learning views include:

- book learning summary;
- chapter summary and chapter-level observations;
- entity profile and source-ordered storyline;
- direct relationships and events;
- motivations and character states;
- causal candidates;
- foreshadowing and mainline candidates;
- grouped world model and observed entity candidates.

### World-model enrichment

The world model is separated by book and groups characters, places, factions, abilities, items, species, concepts, direct relationships, direct events, reviewed learning observations, and evidence-bound learned entity candidates.

## Controlled simulation

The R7 controlled simulation reused the same original two-volume, sixteen-chapter narrative and same-name cross-book adversarial sample used for the R6 audit. Results:

- 2 books and 3 source projects;
- 18 narrative chapters, with volume headings excluded;
- 18 complete private chapter packets and 18 deep-learning tasks;
- 44 evidence-bound model observations across 9 learning dimensions;
- 19 accepted consolidated entity profiles and 3 review-only fragment profiles;
- same-book identities consolidated across volumes;
- identical names across books isolated;
- ambiguous unscoped entity queries refused;
- scoped chapter, entity, event, causality, motivation, foreshadowing, mainline, and world queries returned actual learned statements;
- Learning Project verification passed.

## Quality evidence

- repository tests: 692 passed;
- schemas: 84;
- Skill Audit: 0 findings;
- Skill Doctor: 7/7;
- formal private blind acceptance: not performed;
- technical Candidate, approval, release, and freeze authority: not created or granted.

## Boundary

The controlled simulation may support an engineering learning-capability score. It does not replace independent blind review and cannot self-grant formal acceptance, public release, or repository freeze.
