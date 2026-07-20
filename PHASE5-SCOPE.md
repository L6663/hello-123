# Phase 5 scope

This branch implements hash-verified SQLite indexing and predicate-aware hybrid retrieval for the closed typed Claim family. It does not grant freeze authority and does not treat lexical similarity as answerability evidence.

Follow-up hardening additionally requires Phase 5 to regenerate Phase 4 artifacts from the source and accepted Claims before indexing, so a forged artifact plus a recomputed report hash cannot bypass semantic validation. Compatible date-precision refinements resolve to the most precise supported value instead of producing a false ambiguity.

Current complete local regression: 148 tests passed.
