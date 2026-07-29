# Stage 8-R6 — Learning Panorama and Long-Text Study Output

## Purpose

R6 changes the main testing question from “did the typed query reproduce its own fact?” to “what did the system actually learn from the books?”

A verified Learning Project is built from one or more verified Literary projects and produces:

- chapter learning cards;
- entity learning profiles with invalid-name review isolation;
- direct relationship records and clearly labeled co-occurrence candidates;
- direct event records;
- source-ordered character storylines;
- a grouped world model;
- explicit learning gaps;
- chapter-level model-learning tasks for summaries, motivations, causal links, world rules, relationships, and foreshadowing.

## Authority boundary

Direct Tier-A facts remain exact source facts. Co-occurrence does not establish a relationship. Model-learning tasks cannot publish directly and require exact evidence validation before they may become reviewed B or C annotations.

Internet sources may validate author, title, edition, and public metadata. They may not fill gaps in uploaded source knowledge or overwrite source-grounded conclusions.

## Build

```bash
tkr-learning build LITERARY_A LITERARY_B --source-project BASE_A --source-project BASE_B --outdir LEARNING_PROJECT

tkr-learning verify LEARNING_PROJECT \
  --literary-project LITERARY_A \
  --literary-project LITERARY_B \
  --source-project BASE_A \
  --source-project BASE_B
```

## Query

```bash
tkr-learning query LEARNING_PROJECT "这本书学到了什么？"
tkr-learning query LEARNING_PROJECT "陆川学到了什么？"
tkr-learning query LEARNING_PROJECT "第12章学到了什么？"
tkr-learning query LEARNING_PROJECT "有哪些地点和势力？"
```

## Creative-generation boundary

When the user asks for an original story based on learning results, the default is to reuse only abstract narrative structures and learned organizational patterns. Do not reuse source characters, proper nouns, unique settings, named artifacts, or cross-book mashups unless the user explicitly requests them.


## Complete-chapter learning and observation integration

When Base projects are supplied, `chapter-source-packets.jsonl` stores the exact complete normalized chapter text, source offsets, chapter content hash, and source binding. This is a **private local artifact** and is explicitly marked `may_upload_to_public_ci: false`.

The first build creates one `model-learning-tasks.jsonl` record per chapter. A model may then produce a JSONL observation file using `schemas/model-learning-observation.schema.json`. Every row must:

- reference a deterministic task ID;
- remain Tier B or C and `status: proposed`;
- use an allowed learning dimension;
- cite at least one exact source span or task-owned Evidence Anchor;
- carry no direct-publication authority.

Rebuild to integrate the observations:

```bash
tkr-learning build LITERARY_A LITERARY_B \
  --source-project BASE_A \
  --source-project BASE_B \
  --observations MODEL_OBSERVATIONS.jsonl \
  --outdir LEARNING_PROJECT --force

tkr-learning verify LEARNING_PROJECT \
  --literary-project LITERARY_A \
  --literary-project LITERARY_B \
  --source-project BASE_A \
  --source-project BASE_B
```

Integrated observations appear in `model-learning-observations.jsonl`, chapter cards, entity storylines, learning summaries, and world-model observation counts. They remain reviewable learning products rather than canonical facts.

## R6 validation evidence

R6 was designed against consolidated failure classes reported from a private four-long-novel test. The private novels, their file inventory, extracted observations, and detailed report are not stored in this repository or GitHub Actions.

Public-safe local validation completed before integration:

- 689 repository tests passed;
- Skill Audit: 0 findings across 84 schemas;
- Skill Doctor: 7/7 checks passed;
- two fixed-epoch Wheels were byte-identical;
- a clean Wheel installation completed the GB18030 Base → Literary → Evidence → Learning chain;
- the clean-install chain verified three complete chapter packets, three chapter-learning tasks, and one exact-evidence Tier-C motivation observation;
- a five-source development regression corpus completed 5/5 Base verification and 5/5 Literary verification;
- that regression produced 880 chapter cards, 880 complete private chapter packets, 880 deep-learning tasks, 26 accepted entity profiles, 10 direct Tier-A relationships, 26 source-ordered entity storylines, 21 exact assertions, and 52 exact evidence anchors;
- the combined Learning Project passed its complete file, hash, source-binding, and authority-boundary verification.

These figures establish engineering usability and learning-product generation. They do not claim formal private blind acceptance, independent semantic scoring, Candidate approval, public-release approval, or repository-freeze approval.
