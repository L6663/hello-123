from pathlib import Path

path = Path("SKILL.md")
text = path.read_text(encoding="utf-8")

replacements = [
    (
        "description: Build auditable long-text knowledge projects with strict source identity, contamination isolation, exact Evidence Units, multi-file chapter catalogs, focused event causality, scoped character modeling, A/B/C epistemic separation, evidence-first queries, and Notion-ready exports.",
        "description: Build auditable long-text knowledge projects with strict source identity, contamination isolation, exact Evidence Units, multi-file chapter catalogs, focused event and character models, A/B/C/H layered reasoning, evidence-first queries, and Notion-ready exports.",
    ),
    (
        "**Current development:** Stage 1 Evidence Engine, Stage 2 Chapter Structure Engine, and Stage 3 Event Causality Engine integrated; Stage 4 Focused Character Engine under final integration  ",
        "**Current development:** Stage 1–4 integrated; Stage 5 Layered Reasoning Engine under final integration  ",
    ),
    (
        "The v6 system has seven compatible project layers:",
        "The v6 system has eight compatible project layers:",
    ),
    (
        "6. **Character Project** — scoped core/important/placeholder people, evidence-bound attributes and states, time-bounded relationships, verified major-event links, and A/B/C-separated core-character arcs.\n7. **Notion-ready projection** — fact-separated chapter, assertion, event, and focused-character pages for external upload.",
        "6. **Character Project** — scoped core/important/placeholder people, evidence-bound attributes and states, time-bounded relationships, verified major-event links, and A/B/C-separated core-character arcs.\n7. **Reasoning Project** — verified A facts, independently supported B synthesis, explicitly attributed C interpretation, non-canon H counterfactuals, separated answer packets, and exact provenance.\n8. **Notion-ready projection** — fact-separated chapter, assertion, event, focused-character, and reasoning records for external upload.",
    ),
    (
        "- a verified Event Project and Character Project;\n- factual, structural, relational, character-state, character-arc, event, evidence, chapter-location, causal-path, or literary-analysis questions.",
        "- a verified Event Project and Character Project;\n- reviewed Reasoning Project annotation JSONL;\n- a verified Reasoning Project;\n- factual, structural, relational, character-state, character-arc, event, evidence, chapter-location, causal-path, literary-analysis, provenance, or counterfactual questions.",
    ),
    (
        "C records may discuss theme, symbolism, narrative strategy, ethics, politics, or one plausible reading. They must be labeled model interpretation, cite A/B support, disclose limitations, and never enter A-grade fact or cause properties.\n\nDo not silently promote C to B or B to A.",
        "C records may discuss theme, symbolism, narrative strategy, ethics, politics, or one plausible reading. They must be labeled model interpretation, cite A/B support, disclose limitations and alternative readings, and never enter A-grade fact or cause properties.\n\n### H — hypothetical or counterfactual inference\n\nH records are not canon. They must identify the changed premise, retained verified facts, inference rule or causal path, uncertainty, and alternative outcomes. Never present H as original plot.\n\nDo not silently promote H to C, C to B, or B to A.",
    ),
    (
        "Placeholder characters cannot receive complete ability systems, deep relationships, or character arcs. If the Event Project or Character Project is `review_required`, character conclusions must refuse.\n\n### 8. Query the appropriate layer",
        "Placeholder characters cannot receive complete ability systems, deep relationships, or character arcs. If the Event Project or Character Project is `review_required`, character conclusions must refuse.\n\n### 8. Build and verify the Layered Reasoning Project\n\nReasoning annotation JSONL may contain only reviewed `node` and `edge` envelopes. A nodes must bind exact upstream records and Evidence Anchors. B nodes require at least two independent A branches. C nodes require A/B support, model attribution, limitations, and alternative readings. H nodes require a changed premise, inference rule, uncertainty, alternatives, and non-canon attribution.\n\n```bash\npython \"${SKILL_DIR}/scripts/tkr.py\" reason build \\\n  CHAPTER_PROJECT EVENT_PROJECT EVENTS.jsonl \\\n  CHARACTER_PROJECT CHARACTERS.jsonl REASONING.jsonl \\\n  --source-project PROJECT_A \\\n  --literary-project LITERARY_PROJECT \\\n  --evidence-binding PROJECT_A LITERARY_PROJECT EVIDENCE_PROJECT \\\n  --outdir REASONING_PROJECT\n\npython \"${SKILL_DIR}/scripts/tkr.py\" reason verify \\\n  REASONING_PROJECT CHAPTER_PROJECT EVENT_PROJECT EVENTS.jsonl \\\n  CHARACTER_PROJECT CHARACTERS.jsonl REASONING.jsonl \\\n  --source-project PROJECT_A \\\n  --literary-project LITERARY_PROJECT \\\n  --evidence-binding PROJECT_A LITERARY_PROJECT EVIDENCE_PROJECT\n```\n\nQuery modes are strict ceilings:\n\n```bash\npython \"${SKILL_DIR}/scripts/tkr.py\" reason query \\\n  REASONING_PROJECT CHAPTER_PROJECT EVENT_PROJECT EVENTS.jsonl \\\n  CHARACTER_PROJECT CHARACTERS.jsonl REASONING.jsonl \\\n  --source-project PROJECT_A \\\n  --literary-project LITERARY_PROJECT \\\n  --evidence-binding PROJECT_A LITERARY_PROJECT EVIDENCE_PROJECT \\\n  --mode fact_only --intent-tag mainline_cause\n```\n\nAvailable modes: `fact_only`, `fact_and_synthesis`, `analysis`, `counterfactual`, and `provenance`. Selecting a mode never authorizes creation of missing higher-layer content.\n\n### 9. Query the appropriate layer",
    ),
    (
        "Use the Chapter Project for exact source location and order. Use the Event Project for supported causal chains. Use the Character Project for scoped profiles, time-bounded states and relationships, major-event participation, and core-character arcs. Use the literary layer for other evidence-linked records and explicitly separated analysis.\n\nDo not rewrite an A/B/C-separated response into one undifferentiated narrative.\n\n### 9. Export a Notion-ready package",
        "Use the Chapter Project for exact source location and order. Use the Event Project for supported causal chains. Use the Character Project for scoped profiles, time-bounded states and relationships, major-event participation, and core-character arcs. Use the Reasoning Project for section-separated fact, synthesis, interpretation, counterfactual, and provenance answers. Use the literary layer for other evidence-linked records.\n\nNever rewrite an A/B/C/H-separated response into one undifferentiated narrative.\n\n### 10. Export a Notion-ready package",
    ),
    (
        "A-grade character records require exact assertions and evidence anchors. B-grade character synthesis requires multiple supported A-grade records. C-grade character interpretation requires explicit model attribution and limitations. Only core characters may receive formal arc records. Alias collisions, contradictory overlapping states, unsupported event links, and placeholder depth leakage remain explicit findings.\n\n## Base deterministic predicates",
        "A-grade character records require exact assertions and evidence anchors. B-grade character synthesis requires multiple supported A-grade records. C-grade character interpretation requires explicit model attribution and limitations. Only core characters may receive formal arc records. Alias collisions, contradictory overlapping states, unsupported event links, and placeholder depth leakage remain explicit findings.\n\n## Layered Reasoning contract\n\nReasoning query modes are presentation ceilings:\n\n- `fact_only` — A only;\n- `fact_and_synthesis` — A and B in separate sections;\n- `analysis` — A, B, and C in separate sections;\n- `counterfactual` — verified A/B premises plus explicitly non-canon H inference;\n- `provenance` — support graph and Evidence lineage, including review findings.\n\nEvery answer packet keeps facts, synthesis, interpretation, counterfactuals, conflicts, limitations, alternatives, and provenance separate. A partial answer must state which requested nodes or layers were refused. Duplicate restatements of one evidence lineage cannot satisfy B independence. Ordinary answer modes refuse when the Reasoning graph is `review_required`; provenance mode may expose the graph for review without presenting its claims as conclusions.\n\n## Base deterministic predicates",
    ),
    (
        "- an Event Project or Character Project is `review_required`;\n- a placeholder is asked for an unsupported deep relationship, ability system, personality analysis, or character arc;",
        "- an Event Project, Character Project, or Reasoning Project is `review_required`;\n- an A node lacks exact upstream-bound evidence;\n- a B node lacks two independent A support branches;\n- a C node lacks attribution, support, limitations, or alternative readings;\n- an H node lacks a changed premise, inference rule, uncertainty, or non-canon labeling;\n- the query mode forbids the available reasoning layer;\n- a placeholder is asked for an unsupported deep relationship, ability system, personality analysis, or character arc;",
    ),
    (
        "13. Never answer from model memory when verified support is absent.\n14. Stop on any verification failure.",
        "13. Never collapse fact, synthesis, interpretation, and counterfactual sections.\n14. Never count duplicated evidence lineage as independent B support.\n15. Never present H counterfactuals as canon.\n16. Never answer from model memory when verified support is absent.\n17. Stop on any verification failure.",
    ),
    (
        "15. Do not combine files without explicit order.\n16. Never claim all capabilities exceed 9.0 before final private blind evaluation.\n17. Never claim v6 release or freeze from an engineering-stage check.",
        "18. Do not combine files without explicit order.\n19. Never claim all capabilities exceed 9.0 before final private blind evaluation.\n20. Never claim v6 release or freeze from an engineering-stage check.",
    ),
    (
        "Character Project:\n\n```text\ncharacters.jsonl\ncharacter-attributes.jsonl\ncharacter-states.jsonl\ncharacter-relationships.jsonl\ncharacter-event-links.jsonl\ncharacter-findings.jsonl\ncharacter.sqlite\ncharacter-project-report.json\nartifact-manifest.json\n```\n\nLiterary sidecar:",
        "Character Project:\n\n```text\ncharacters.jsonl\ncharacter-attributes.jsonl\ncharacter-states.jsonl\ncharacter-relationships.jsonl\ncharacter-event-links.jsonl\ncharacter-findings.jsonl\ncharacter.sqlite\ncharacter-project-report.json\nartifact-manifest.json\n```\n\nReasoning Project:\n\n```text\nreasoning-nodes.jsonl\nreasoning-edges.jsonl\nreasoning-findings.jsonl\nreasoning.sqlite\nreasoning-project-report.json\nartifact-manifest.json\n```\n\nLiterary sidecar:",
    ),
    (
        "character build\ncharacter verify\ncharacter query\nliterary build",
        "character build\ncharacter verify\ncharacter query\nreason build\nreason verify\nreason query\nliterary build",
    ),
    (
        "character-build\ncharacter-verify\ncharacter-query\nliterary-build",
        "character-build\ncharacter-verify\ncharacter-query\nreason-build\nreason-verify\nreason-query\nliterary-build",
    ),
    (
        "For a Character Project, report scope counts, selection reasons, A/B/C attribute counts, state and relationship intervals, major-event links, alias/state conflicts, graph status, logical hash, database hash, and placeholders kept minimal.\n\nFor an answer, report answer or refusal, epistemic tier, character scope when relevant, event component or edge type, path direction, chapter binding, supporting assertion IDs, exact evidence anchors, support chains, and limitations.",
        "For a Character Project, report scope counts, selection reasons, A/B/C attribute counts, state and relationship intervals, major-event links, alias/state conflicts, graph status, logical hash, database hash, and placeholders kept minimal.\n\nFor a Reasoning Project, report A/B/C/H counts, independent-support groups, conflicts, blocking findings, upstream binding hashes, graph status, logical hash, database hash, and available query modes.\n\nFor an answer, report answer or refusal, query mode, separately rendered facts/synthesis/interpretation/counterfactuals, character scope when relevant, chapter/event bindings, exact Evidence Anchors, support chains, conflicts, limitations, alternatives, and partial-refusal reasons.",
    ),
    (
        "6. Verify the Character Project for character profiles, states, relationships, events, and arcs.\n7. Confirm exact offsets, text, hashes, and source identity.",
        "6. Verify the Character Project for character profiles, states, relationships, events, and arcs.\n7. Verify the Reasoning Project for A/B/C/H answers and provenance.\n8. Confirm exact offsets, text, hashes, and source identity.",
    ),
    (
        "8. Confirm physical order was not rewritten.\n9. Confirm canonical order is labeled candidate.\n10. Confirm active events and modeled core/important characters are materially significant.\n11. Confirm placeholder and mention-only records were not given invented depth.\n12. Confirm every causal edge and character record has verified support.\n13. Confirm `review_required` graphs refuse presentation.\n14. Confirm A/B/C separation remains intact.\n15. Confirm downloadable files exist at the exact linked path.\n16. State that v6 remains under development until final integrated acceptance.",
        "9. Confirm physical order was not rewritten.\n10. Confirm canonical order is labeled candidate.\n11. Confirm active events and modeled core/important characters are materially significant.\n12. Confirm placeholder and mention-only records were not given invented depth.\n13. Confirm every causal edge, character record, and reasoning node has verified support.\n14. Confirm B independence groups match actual A evidence lineages.\n15. Confirm C and H disclosures are present.\n16. Confirm `review_required` graphs refuse ordinary presentation.\n17. Confirm A/B/C/H separation remains intact.\n18. Confirm downloadable files exist at the exact linked path.\n19. State that v6 remains under development until final integrated acceptance.",
    ),
    (
        "Stage 1, Stage 2, Stage 3, and Stage 4 checks are engineering evidence for the v6 development line.",
        "Stage 1, Stage 2, Stage 3, Stage 4, and Stage 5 checks are engineering evidence for the v6 development line.",
    ),
]

for old, new in replacements:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"expected one occurrence, found {count}: {old[:100]!r}")
    text = text.replace(old, new)

path.write_text(text, encoding="utf-8", newline="\n")
