# Phase 8 security notes

The Phase 8 freeze pipeline treats technical readiness and release authority as separate decisions.

## Candidate provenance

Independent candidate verification validates the release version, a lowercase 40-character Git commit SHA, and a non-negative source-date epoch before artifact evidence or candidate identity is accepted. Recomputing a candidate ID cannot legitimize malformed provenance.

## Evidence path safety

The CI assembly tool requires its output directory to be disjoint from the downloaded matrix evidence. It also refuses an output directory that contains either reproducible-wheel input. These checks run before any existing output directory is removed.

## Authority boundary

A verified technical candidate remains `may_freeze=false`. A separate approval object must identify the exact candidate, release version, and source commit before a seal can be created. The current approval identity is explicitly described as operator-asserted rather than cryptographically authenticated.
