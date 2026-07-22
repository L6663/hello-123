# Migration from Stage 4 to Stage 5

## Command compatibility

The four Stage 4 subcommands remain available:

```bash
tkr-project build
tkr-project verify
tkr-project query
tkr-project verify-answer
```

Stage 5 changes the default build path from direct monolithic orchestration to the recoverable engineering wrapper. The generated immutable project format remains the Stage 4 knowledge-project format.

## New default profile

A build without profile arguments now uses:

```bash
--profile balanced
```

`balanced` maps to the prior Stage 4 review-mode defaults:

- review index mode;
- 200000 candidate limit;
- 50000 finding limit;
- 50000 model-task limit;
- 600-character clause limit;
- model proposal tasks enabled.

Existing explicit limit flags continue to override the selected profile for that invocation.

## New external state directory

Stage 5 creates a sibling state directory by default:

```text
.<project-name>.tkr-state/
```

It contains build locks, journal state, and content-addressed cache entries. It is not part of the immutable project and must not be copied as evidence.

Select an explicit path when project directories are moved or centrally managed:

```bash
tkr-project build corpus.txt \
  --outdir projects/corpus \
  --state-dir state/corpus
```

## Existing projects

An existing Stage 4 project can still be verified and queried. Stage 5 verification adds exact filesystem membership and symbolic-link checks.

To reuse an existing project during build:

```bash
tkr-project build corpus.txt --outdir project --reuse
```

Reuse succeeds only when:

- the full Stage 5 security verification passes;
- raw source SHA-256 matches;
- build-affecting profile fields match.

## Replacement

The prior `--force` option remains the explicit atomic-replacement signal:

```bash
tkr-project build corpus.txt --outdir project --force
```

Stage 5 records recovery state externally and can roll back an interrupted replacement only when the backup verifies.

## Cache behavior

Verified caching is enabled by built-in profiles. Disable it for one invocation:

```bash
tkr-project build corpus.txt --outdir project --no-cache
```

Cache identity changes when the source, profile, engineering version, or knowledge-system version changes. A cache entry never bypasses project verification.

## Recovery behavior

Workspace recovery runs by default before a build. Disable only for diagnosis:

```bash
tkr-project build corpus.txt --outdir project --no-resume
```

A stale lock is not removed unless explicitly requested:

```bash
tkr-project build corpus.txt --outdir project --recover-stale-lock
```

## Package checks

After upgrading, run:

```bash
tkr-skill doctor
tkr-skill audit
tkr-skill profiles
```

These verify installed data files and runtime prerequisites. They do not perform final project acceptance.

## Custom automation

Automation that parsed the old build command's top-level Stage 4 report should now read:

```text
result.project_report
```

The Stage 5 result additionally contains:

- build key;
- profile name and hash;
- external state directory;
- cache status;
- reuse status;
- recovery actions.

All acceptance and freeze authority fields remain false.
