# Security Model

## Trust boundaries

Text Knowledge Reader separates three trust domains:

1. **Raw source** — immutable external evidence identified by SHA-256.
2. **Immutable project** — source, Stage 1–3 artifacts, bridge, index, report, and Manifest.
3. **Mutable engineering state** — lock, journal, cache records, and cached project copies.

Mutable engineering state must never be stored inside the immutable project.

## Path safety

The Stage 5 build path rejects:

- symbolic-link sources;
- symbolic-link output or state directories;
- output directories containing the source;
- overlapping output and state directories;
- path components longer than the supported bound;
- unsafe replacement backups;
- symbolic links in project, cache, package, or recovery trees.

Project Manifest paths must be normalized relative POSIX paths. Absolute paths, parent traversal, duplicate paths, undeclared roots, and a Manifest entry pointing to the Manifest itself are rejected.

## Exact filesystem membership

Project verification requires the actual regular-file set to equal:

```text
all files declared by project-manifest.json
+ project-manifest.json itself
```

Extra files and missing files both invalidate the project. The top-level layout must contain exactly:

```text
source
stage1-anomaly
stage2-structure
stage3-semantics
bridge
index
project-report.json
project-manifest.json
```

## Build lock

The external state directory contains one exclusive `build.lock`.

A lock records:

- random ownership token;
- PID;
- hostname;
- start time;
- source SHA-256;
- output directory.

A lock is not removed automatically merely because another invocation requests it. `--recover-stale-lock` is required, the lock must exceed the profile threshold, and a same-host recorded PID must no longer be alive.

## Recovery

Recovery can restore only a project that passes the full hash chain. It may:

- restore an orphaned valid backup when the destination is missing;
- remove a redundant backup when the current destination is valid;
- roll back an invalid destination when its backup is valid;
- remove old temporary build/cache directories after the configured threshold.

If both current and backup projects are invalid, recovery stops.

## Cache

The cache key includes source, profile, engineering runtime, and knowledge-system identities. A cache hit additionally requires:

- valid cache record;
- matching build key;
- matching source SHA-256;
- matching profile SHA-256;
- matching system versions;
- complete project verification;
- exact build-affecting policy equality.

An invalid cache entry is discarded as non-authoritative. Cache restoration occurs through a temporary copy followed by verification and atomic publication.

## Bounded control files

Profiles, build state, cache records, project reports, project Manifests, audit inputs, and answer packets are read with bounded size checks in Stage 5 product paths. Large corpus and SQLite data remain governed by their dedicated streaming or database logic.

## Query safety

Every unified query first runs enhanced project verification. Strict QA then verifies the database and report hash chain. Answers are limited to the closed supported predicate set and must cite typed Fact evidence.

Unsupported questions, insufficient evidence, conflict, ambiguity, tampering, or filesystem mismatch produce refusal or rejection rather than an inferred answer.

## Reporting a vulnerability

Do not include private corpus contents, raw Evidence, credentials, or personally sensitive project data in public reports. Report the smallest reproducible case, affected version, platform, command, expected boundary, and observed result.

## Acceptance boundary

Security-focused developer tests in Stage 5 are not the final hostile-input campaign. The integrated Stage 6 acceptance must still measure traversal, symlink, malformed input, corruption, recovery, concurrency, and resource-exhaustion cases against the final frozen candidate.
