from pathlib import Path

path = Path("SKILL.md")
text = path.read_text(encoding="utf-8")

replacements = [
    (
        "description: Build auditable long-text knowledge projects with strict source identity, contamination isolation, exact Evidence Units, multi-file chapter catalogs, focused event causality, A/B/C epistemic separation, evidence-first queries, and Notion-ready exports.",
        "description: Build auditable long-text knowledge projects with strict source identity, contamination isolation, exact Evidence Units, multi-file chapter catalogs, focused event causality, scoped character modeling, A/B/C epistemic separation, evidence-first queries, and Notion-ready exports.",
    ),
    (
        "**Current development:** Stage 1 Evidence Engine and Stage 2 Chapter Structure Engine integrated; Stage 3 Event Causality Engine under final integration  ",
        "**Current development:** Stage 1 Evidence Engine, Stage 2 Chapter Structure Engine, and Stage 3 Event Causality Engine integrated; Stage 4 Focused Character Engine under final integration  ",
    ),
    (
        "The v6 system has six compatible project layers:",
        "The v6 system has seven compatible project layers:",
    ),
    (
        "5. **Event Project** — selected major events, A/B/C-separated event components, supported causal edges, temporal validation, path queries, and cycle/review findings.\n6. **Notion-ready projection** — fact-separated chapter, assertion, entity, and event pages for external upload.",
        "5. **Event Project** — selected major events, A/B/C-separated event components, supported causal edges, temporal validation, path queries, and cycle/review findings.\n6. **Character Project** — scoped core/important/placeholder people, evidence-bound attributes and states, time-bounded relationships, verified major-event links, and A/B/C-separated core-character arcs.\n7. **Notion-ready projection** — fact-separated chapter, assertion, event, and focused-character pages for external upload.",
    ),
    (
        "- reviewed Event Project annotation JSONL;\n- factual, structural, relational, event, evidence, chapter-location, causal-path, or literary-analysis questions.",
        "- reviewed Event Project annotation JSONL;\n- reviewed Character Project annotation JSONL;\n- a verified Event Project and Character Project;\n- factual, structural, relational, character-state, character-arc, event, evidence, chapter-location, causal-path, or literary-analysis questions.",
    ),
    (
        "If the Event Project status is `review_required`, causal answers must refuse until cycles or other high-severity findings are reviewed.\n\n### 7. Query the appropriate layer",
        "If the Event Project status is `review_required`, causal answers must refuse until cycles or other high-severity findings are reviewed.\n\n### 7. Build and verify the Focused Character Project\n\nCharacter annotation JSONL may contain only reviewed `character`, `attribute`, `state`, `relationship`, and `event_link` envelopes. Core characters require material mainline impact; important characters require major-event, major-faction, core-character, or world-state impact; placeholders remain minimal. Mention frequency alone cannot promote a character.\n\n```bash\npython \"${SKILL_DIR}/scripts/tkr.py\" character build \\\n  CHAPTER_PROJECT EVENT_PROJECT EVENTS.jsonl CHARACTERS.jsonl \\\n  --source-project PROJECT_A \\\n  --source-project PROJECT_B \\\n  --literary-project LITERARY_PROJECT \\\n  --outdir CHARACTER_PROJECT\n\npython \"${SKILL_DIR}/scripts/tkr.py\" character verify \\\n  CHARACTER_PROJECT CHAPTER_PROJECT EVENT_PROJECT EVENTS.jsonl CHARACTERS.jsonl \\\n  --source-project PROJECT_A \\\n  --source-project PROJECT_B \\\n  --literary-project LITERARY_PROJECT\n```\n\nQuery a profile, state at a chapter position, relationship interval, major-event links, selection reason, or core-character arc:\n\n```bash\npython \"${SKILL_DIR}/scripts/tkr.py\" character query \\\n  CHARACTER_PROJECT CHAPTER_PROJECT EVENT_PROJECT EVENTS.jsonl CHARACTERS.jsonl \\\n  --source-project PROJECT_A \\\n  --source-project PROJECT_B \\\n  --literary-project LITERARY_PROJECT \\\n  --name \"应飞扬\"\n\npython \"${SKILL_DIR}/scripts/tkr.py\" character query \\\n  CHARACTER_PROJECT CHAPTER_PROJECT EVENT_PROJECT EVENTS.jsonl CHARACTERS.jsonl \\\n  --source-project PROJECT_A \\\n  --source-project PROJECT_B \\\n  --literary-project LITERARY_PROJECT \\\n  --arc \"应飞扬\"\n```\n\nPlaceholder characters cannot receive complete ability systems, deep relationships, or character arcs. If the Event Project or Character Project is `review_required`, character conclusions must refuse.\n\n### 8. Query the appropriate layer",
    ),
    (
        "Use the Chapter Project for exact source location and order. Use the Event Project for supported causal chains. Use the literary layer for relationships, selected profiles, and explicitly separated analysis.",
        "Use the Chapter Project for exact source location and order. Use the Event Project for supported causal chains. Use the Character Project for scoped profiles, time-bounded states and relationships, major-event participation, and core-character arcs. Use the literary layer for other evidence-linked records and explicitly separated analysis.",
    ),
    (
        "### 8. Export a Notion-ready package",
        "### 9. Export a Notion-ready package",
    ),
    (
        "Forward relations cannot silently point backward in time. `recovers` explicitly references an earlier clue or event. Causal cycles remain findings; they are never silently broken. Every query path must return its supporting assertions and evidence anchors.\n\n## Base deterministic predicates",
        "Forward relations cannot silently point backward in time. `recovers` explicitly references an earlier clue or event. Causal cycles remain findings; they are never silently broken. Every query path must return its supporting assertions and evidence anchors.\n\n## Focused Character contract\n\nCharacter scopes are strict:\n\n- `core` — deep evidence-bound identity, goals, choices, states, major relationships, major events, and A/B/C-separated arcs;\n- `important` — moderate identity, role, state, major relationships, and major-event modeling;\n- `placeholder` — minimal identity, role, chapter location, and necessary event participation only;\n- mention-only — no canonical Character Project entity unless later evidence establishes material impact.\n\nA-grade character records require exact assertions and evidence anchors. B-grade character synthesis requires multiple supported A-grade records. C-grade character interpretation requires explicit model attribution and limitations. Only core characters may receive formal arc records. Alias collisions, contradictory overlapping states, unsupported event links, and placeholder depth leakage remain explicit findings.\n\n## Base deterministic predicates",
    ),
    (
        "- an Event Project is `review_required`;\n- no supported causal path exists;",
        "- an Event Project or Character Project is `review_required`;\n- a placeholder is asked for an unsupported deep relationship, ability system, personality analysis, or character arc;\n- no supported causal path exists;",
    ),
    (
        "9. Never silently break causal cycles or contradictions.\n10. Never answer from model memory when verified support is absent.",
        "9. Never silently break causal cycles or contradictions.\n10. Never promote mention frequency into character importance.\n11. Never invent identity merges, personality, morality, growth, relationships, abilities, or character arcs.\n12. Never allow placeholder records to acquire core-character depth.\n13. Never answer from model memory when verified support is absent.",
    ),
    (
        "11. Stop on any verification failure.\n12. Do not combine files without explicit order.\n13. Never claim all capabilities exceed 9.0 before final private blind evaluation.\n14. Never claim v6 release or freeze from an engineering-stage check.",
        "14. Stop on any verification failure.\n15. Do not combine files without explicit order.\n16. Never claim all capabilities exceed 9.0 before final private blind evaluation.\n17. Never claim v6 release or freeze from an engineering-stage check.",
    ),
    (
        "Event Project:\n\n```text\nevents.jsonl\nevent-components.jsonl\nevent-causal-edges.jsonl\nevent-findings.jsonl\nevent.sqlite\nevent-project-report.json\nartifact-manifest.json\n```\n\nLiterary sidecar:",
        "Event Project:\n\n```text\nevents.jsonl\nevent-components.jsonl\nevent-causal-edges.jsonl\nevent-findings.jsonl\nevent.sqlite\nevent-project-report.json\nartifact-manifest.json\n```\n\nCharacter Project:\n\n```text\ncharacters.jsonl\ncharacter-attributes.jsonl\ncharacter-states.jsonl\ncharacter-relationships.jsonl\ncharacter-event-links.jsonl\ncharacter-findings.jsonl\ncharacter.sqlite\ncharacter-project-report.json\nartifact-manifest.json\n```\n\nLiterary sidecar:",
    ),
    (
        "event build\nevent verify\nevent query\nliterary build",
        "event build\nevent verify\nevent query\ncharacter build\ncharacter verify\ncharacter query\nliterary build",
    ),
    (
        "event-build\nevent-verify\nevent-query\nliterary-build",
        "event-build\nevent-verify\nevent-query\ncharacter-build\ncharacter-verify\ncharacter-query\nliterary-build",
    ),
    (
        "For an answer, report answer or refusal, tier, event component or edge type, path direction, chapter binding, supporting assertion IDs, exact evidence anchors, and limitations.",
        "For a Character Project, report scope counts, selection reasons, A/B/C attribute counts, state and relationship intervals, major-event links, alias/state conflicts, graph status, logical hash, database hash, and placeholders kept minimal.\n\nFor an answer, report answer or refusal, epistemic tier, character scope when relevant, event component or edge type, path direction, chapter binding, supporting assertion IDs, exact evidence anchors, support chains, and limitations.",
    ),
    (
        "5. Verify the Event Project for causal answers.\n6. Confirm exact offsets, text, hashes, and source identity.",
        "5. Verify the Event Project for causal answers and character-event links.\n6. Verify the Character Project for character profiles, states, relationships, events, and arcs.\n7. Confirm exact offsets, text, hashes, and source identity.",
    ),
    (
        "7. Confirm physical order was not rewritten.\n8. Confirm canonical order is labeled candidate.\n9. Confirm active events are materially significant.\n10. Confirm every causal edge has verified support and valid temporal direction.\n11. Confirm `review_required` graphs refuse causal presentation.\n12. Confirm A/B/C separation remains intact.\n13. Confirm downloadable files exist at the exact linked path.\n14. State that v6 remains under development until final integrated acceptance.",
        "8. Confirm physical order was not rewritten.\n9. Confirm canonical order is labeled candidate.\n10. Confirm active events and modeled core/important characters are materially significant.\n11. Confirm placeholder and mention-only records were not given invented depth.\n12. Confirm every causal edge and character record has verified support.\n13. Confirm `review_required` graphs refuse presentation.\n14. Confirm A/B/C separation remains intact.\n15. Confirm downloadable files exist at the exact linked path.\n16. State that v6 remains under development until final integrated acceptance.",
    ),
    (
        "Stage 1, Stage 2, and Stage 3 checks are engineering evidence for the v6 development line.",
        "Stage 1, Stage 2, Stage 3, and Stage 4 checks are engineering evidence for the v6 development line.",
    ),
]

for old, new in replacements:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"expected one occurrence for replacement, found {count}: {old[:80]!r}")
    text = text.replace(old, new)

path.write_text(text, encoding="utf-8", newline="\n")
