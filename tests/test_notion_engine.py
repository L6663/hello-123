from __future__ import annotations

import unittest

from tkr.notion_engine import (
    NOTION_LEDGER_SCHEMA_VERSION,
    NotionEngineError,
    SyncLedgerEntry,
    build_notion_projection,
    make_notion_page,
    make_notion_relation,
    notion_page_key,
    relation_set_hash,
)

LINEAGE = ("project-sha-a",)


def _page(
    database: str,
    record_type: str,
    record_id: str,
    title: str,
    *,
    layer: str = "",
    status: str = "published",
):
    return make_notion_page(
        database,
        record_type,
        record_id,
        title,
        properties={"记录ID": record_id, "标题": title},
        sections={"正文": f"{title}内容"},
        epistemic_layer=layer,
        publication_status=status,
        source_lineage=LINEAGE,
    )


def _ledger(page, *, remote: str = "remote-page", relation_hash: str = ""):
    return SyncLedgerEntry(
        NOTION_LEDGER_SCHEMA_VERSION,
        page.page_key,
        remote,
        page.content_sha256,
        relation_hash,
        False,
    )


class NotionPageContractTests(unittest.TestCase):
    def test_page_key_is_stable_across_title_changes(self) -> None:
        first = _page("chapters", "chapter", "chapter-1", "旧标题")
        second = _page("chapters", "chapter", "chapter-1", "新标题")
        self.assertEqual(first.page_key, second.page_key)
        self.assertNotEqual(first.content_sha256, second.content_sha256)

    def test_A_B_C_H_are_physically_isolated(self) -> None:
        for layer, database in {
            "A": "facts_a",
            "B": "synthesis_b",
            "C": "interpretations_c",
            "H": "counterfactuals_h",
        }.items():
            page = _page(database, "reasoning", layer, f"{layer}记录", layer=layer)
            self.assertEqual(page.database_key, database)
        with self.assertRaises(NotionEngineError):
            _page("facts_a", "reasoning", "bad", "错误解释", layer="C")

    def test_epistemic_database_requires_layer(self) -> None:
        with self.assertRaises(NotionEngineError):
            _page("facts_a", "assertion", "fact-1", "无层级事实")

    def test_content_hash_rejects_manual_tampering(self) -> None:
        page = _page("chapters", "chapter", "chapter-1", "标题")
        with self.assertRaises(NotionEngineError):
            type(page)(**{**page.to_dict(), "source_lineage": page.source_lineage, "title": "被篡改"})


class NotionProjectionTests(unittest.TestCase):
    def test_first_sync_creates_pages_then_relations(self) -> None:
        chapter = _page("chapters", "chapter", "chapter-1", "第一章")
        evidence = _page("evidence", "evidence", "evidence-1", "证据一")
        relation = make_notion_relation(evidence.page_key, "chapter", chapter.page_key)
        projection = build_notion_projection((chapter, evidence), (relation,))
        self.assertTrue(projection.report.projection_valid)
        page_actions = [item for item in projection.actions if item.target_type == "page"]
        relation_actions = [item for item in projection.actions if item.target_type == "relation_set"]
        self.assertTrue(all(item.action == "create" for item in page_actions))
        self.assertEqual(len(relation_actions), 1)
        self.assertEqual(relation_actions[0].action, "create")
        self.assertEqual(
            set(relation_actions[0].dependency_page_keys),
            {chapter.page_key, evidence.page_key},
        )

    def test_identical_ledger_yields_noop(self) -> None:
        chapter = _page("chapters", "chapter", "chapter-1", "第一章")
        evidence = _page("evidence", "evidence", "evidence-1", "证据一")
        relation = make_notion_relation(evidence.page_key, "chapter", chapter.page_key)
        relations = (relation,)
        ledger = (
            _ledger(chapter, remote="remote-chapter", relation_hash=relation_set_hash(chapter.page_key, relations)),
            _ledger(evidence, remote="remote-evidence", relation_hash=relation_set_hash(evidence.page_key, relations)),
        )
        projection = build_notion_projection((chapter, evidence), relations, ledger_entries=ledger)
        self.assertTrue(all(item.action == "noop" for item in projection.actions))

    def test_title_change_updates_instead_of_creating_duplicate(self) -> None:
        old = _page("chapters", "chapter", "chapter-1", "旧标题")
        new = _page("chapters", "chapter", "chapter-1", "新标题")
        projection = build_notion_projection((new,), (), ledger_entries=(_ledger(old),))
        action = next(item for item in projection.actions if item.target_type == "page")
        self.assertEqual(action.action, "update")
        self.assertEqual(action.notion_page_id, "remote-page")
        self.assertEqual(action.target_key, old.page_key)

    def test_missing_remote_id_requires_review(self) -> None:
        page = _page("characters", "character", "character-1", "甲")
        ledger = (_ledger(page, remote=""),)
        projection = build_notion_projection((page,), (), ledger_entries=ledger)
        action = projection.actions[0]
        self.assertEqual(action.action, "review_missing_remote_id")
        self.assertIn("LEDGER_ENTRY_MISSING_REMOTE_PAGE_ID", action.reason_codes)

    def test_missing_local_page_becomes_archive_candidate_not_delete(self) -> None:
        old = _page("characters", "character", "character-1", "甲")
        projection = build_notion_projection((), (), ledger_entries=(_ledger(old),))
        self.assertEqual(len(projection.actions), 1)
        action = projection.actions[0]
        self.assertEqual(action.action, "archive_candidate")
        self.assertNotIn("delete", action.action)
        self.assertIn("EXPLICIT_ARCHIVE_APPROVAL_REQUIRED", action.reason_codes)
        self.assertEqual(projection.reviews[0].rule_id, "NOTION_ARCHIVE_CANDIDATE")

    def test_remote_page_id_reuse_blocks_projection(self) -> None:
        first = _page("characters", "character", "character-1", "甲")
        second = _page("characters", "character", "character-2", "乙")
        ledger = (
            _ledger(first, remote="same-remote-id"),
            _ledger(second, remote="same-remote-id"),
        )
        projection = build_notion_projection((first, second), (), ledger_entries=ledger)
        self.assertFalse(projection.report.projection_valid)
        self.assertIn("REMOTE_NOTION_PAGE_ID_REUSED", {item.rule_id for item in projection.reviews})

    def test_unresolved_relation_endpoint_blocks_projection(self) -> None:
        first = _page("events", "event", "event-1", "重大事件")
        missing = notion_page_key("characters", "character", "missing-character")
        relation = make_notion_relation(first.page_key, "participant", missing)
        projection = build_notion_projection((first,), (relation,))
        self.assertFalse(projection.report.projection_valid)
        self.assertIn(
            "UNRESOLVED_NOTION_RELATION_ENDPOINT",
            {item.rule_id for item in projection.reviews},
        )

    def test_duplicate_page_key_is_explicit(self) -> None:
        page = _page("chapters", "chapter", "chapter-1", "第一章")
        projection = build_notion_projection((page, page), ())
        self.assertFalse(projection.report.projection_valid)
        self.assertIn("DUPLICATE_NOTION_PAGE_KEY", {item.rule_id for item in projection.reviews})

    def test_repeated_projection_is_deterministic(self) -> None:
        first = _page("facts_a", "assertion", "fact-1", "事实", layer="A")
        evidence = _page("evidence", "evidence", "evidence-1", "证据")
        relation = make_notion_relation(first.page_key, "evidence", evidence.page_key)
        one = build_notion_projection((first, evidence), (relation,))
        two = build_notion_projection((evidence, first), (relation,))
        self.assertEqual(
            [item.to_dict() for item in one.pages],
            [item.to_dict() for item in two.pages],
        )
        self.assertEqual(
            [item.to_dict() for item in one.actions],
            [item.to_dict() for item in two.actions],
        )


if __name__ == "__main__":
    unittest.main()
