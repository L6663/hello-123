from __future__ import annotations
import json
from pathlib import Path
import tempfile
import unittest

from tkr.semantic_artifacts import publish_semantic_artifacts
from tkr.semantic_cli import main
from tkr.semantic_extraction import inspect_source_semantics, validate_semantic_report
from tkr.semantic_model_tasks import make_model_task, validate_model_proposal
from tkr.semantic_models import SemanticExtractionError, SemanticPolicy


class SemanticExtractionTests(unittest.TestCase):
    def scan(self, text: str, *, policy: SemanticPolicy | None = None, encoding='utf-8'):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'corpus.txt'
            if encoding=='utf-8-sig': path.write_bytes(b'\xef\xbb\xbf'+text.encode())
            elif encoding=='utf-16-le': path.write_bytes(b'\xff\xfe'+text.encode('utf-16-le'))
            else: path.write_text(text,encoding='utf-8')
            return inspect_source_semantics(path,policy=policy)

    def one(self,text,kind):
        r=self.scan(text); rows=[x for x in r.candidates if x.claim_type==kind]; self.assertEqual(len(rows),1); return r,rows[0]

    def test_alias_assertion_is_accepted(self):
        r,c=self.one('玄霄又称青帝。','alias'); self.assertTrue(c.may_index); self.assertEqual(c.factual_status,'asserted_fact'); self.assertEqual(c.subject,'玄霄'); self.assertEqual(c.object,'青帝')

    def test_defeat_assertion(self):
        r,c=self.one('陆川击败韩岳。','defeats'); self.assertTrue(c.may_index)

    def test_location_assertion(self):
        r,c=self.one('听雪楼位于北境。','located_in'); self.assertTrue(c.may_index)

    def test_positive_permission(self):
        r,c=self.one('守门人允许陆川进入内殿。','permission'); self.assertTrue(c.may_index); self.assertTrue(c.polarity)

    def test_negative_permission(self):
        r,c=self.one('守门人禁止陆川进入内殿。','permission'); self.assertTrue(c.may_index); self.assertFalse(c.polarity)

    def test_count_arabic(self):
        r,c=self.one('剑阵共有十二柄飞剑。','count'); self.assertEqual(c.value,12); self.assertTrue(c.may_index)

    def test_count_decimal(self):
        r,c=self.one('灵液总计12.5升。','count'); self.assertEqual(c.value,12.5)

    def test_date(self):
        r,c=self.one('大战发生于2026年7月22日。','date'); self.assertEqual(c.value,'2026年7月22日'); self.assertTrue(c.may_index)

    def test_rumor_is_not_indexed(self):
        r,c=self.one('据说陆川击败韩岳。','defeats'); self.assertEqual(c.discourse_status,'rumor'); self.assertFalse(c.may_index); self.assertEqual(c.validation_status,'not_validated_nonassertive')

    def test_belief_is_not_indexed(self):
        r,c=self.one('林晚认为陆川击败韩岳。','defeats'); self.assertEqual(c.discourse_status,'belief'); self.assertEqual(c.attributor,'林晚'); self.assertFalse(c.may_index)

    def test_suspicion_is_not_indexed(self):
        r,c=self.one('林晚怀疑陆川击败韩岳。','defeats'); self.assertEqual(c.discourse_status,'suspicion'); self.assertFalse(c.may_index)

    def test_accusation_is_not_indexed(self):
        r,c=self.one('林晚指控陆川击败韩岳。','defeats'); self.assertEqual(c.discourse_status,'accusation'); self.assertFalse(c.may_index)

    def test_hypothetical_is_not_indexed(self):
        r,c=self.one('如果陆川击败韩岳。','defeats'); self.assertEqual(c.discourse_status,'hypothetical'); self.assertFalse(c.may_index)

    def test_question_is_not_indexed(self):
        r,c=self.one('陆川击败韩岳？','defeats'); self.assertEqual(c.discourse_status,'question'); self.assertFalse(c.may_index)

    def test_future_intent_is_not_indexed(self):
        r,c=self.one('陆川计划击败韩岳。','defeats'); self.assertEqual(c.discourse_status,'future_intent'); self.assertFalse(c.may_index)

    def test_negated_defeat_not_accepted(self):
        r,c=self.one('陆川并未击败韩岳。','defeats'); self.assertFalse(c.polarity); self.assertEqual(c.factual_status,'negated_fact'); self.assertFalse(c.may_index); self.assertEqual(c.validation_status,'rejected')

    def test_exact_evidence_span_and_hash(self):
        text='前句。陆川击败韩岳。后句。'; r,c=self.one(text,'defeats'); self.assertEqual(text[c.evidence_start:c.evidence_end],c.evidence_text); validate_semantic_report(r)

    def test_heading_text_is_not_extracted(self):
        r=self.scan('第一章 陆川击败韩岳\n正文无关系。'); self.assertEqual(r.candidate_count,0)

    def test_deterministic_ids(self):
        a=self.scan('陆川击败韩岳。'); b=self.scan('陆川击败韩岳。'); self.assertEqual(a.candidates[0].candidate_id,b.candidates[0].candidate_id)

    def test_ambiguous_clause_emits_model_task(self):
        r=self.scan('陆川可能拥有古剑。'); self.assertEqual(r.model_task_count,1); self.assertFalse(r.model_tasks[0].may_accept_directly)

    def test_model_proposal_rejects_authority_fields(self):
        task=make_model_task(source_id='s',source_sha256='a'*64,unit_id='u',evidence_start=10,evidence_end=14,evidence_text='甲乙丙丁')
        with self.assertRaises(SemanticExtractionError): validate_model_proposal(task,{'claim_type':'alias','evidence_start':10,'evidence_end':12,'evidence_text':'甲乙','may_index':True})

    def test_model_proposal_rejects_escaped_span(self):
        task=make_model_task(source_id='s',source_sha256='a'*64,unit_id='u',evidence_start=10,evidence_end=14,evidence_text='甲乙丙丁')
        with self.assertRaises(SemanticExtractionError): validate_model_proposal(task,{'claim_type':'alias','evidence_start':9,'evidence_end':12,'evidence_text':'甲乙丙'})

    def test_model_proposal_envelope(self):
        task=make_model_task(source_id='s',source_sha256='a'*64,unit_id='u',evidence_start=10,evidence_end=14,evidence_text='甲乙丙丁')
        row=validate_model_proposal(task,{'claim_type':'alias','evidence_start':10,'evidence_end':12,'evidence_text':'甲乙'})
        self.assertTrue(row['requires_deterministic_validation']); self.assertFalse(row['may_accept_directly'])

    def test_normalization_summary(self):
        r=self.scan('玄霄又称青帝。陆川击败韩岳。'); self.assertEqual(r.normalization['report']['accepted_claim_count'],2); self.assertEqual(len(r.normalization['facts']),2)

    def test_bom_offsets(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'x.txt'; p.write_bytes(b'\xef\xbb\xbf'+ '陆川击败韩岳。'.encode())
            r=inspect_source_semantics(p); self.assertEqual(r.candidates[0].evidence_start,0)

    def test_utf16(self):
        r=self.scan('陆川击败韩岳。',encoding='utf-16-le'); self.assertEqual(r.candidate_count,1)

    def test_candidate_limit_does_not_corrupt_report(self):
        r=self.scan('甲击败乙。丙击败丁。',policy=SemanticPolicy(max_candidates=1,run_entity_normalization=False)); self.assertEqual(r.candidate_count,1); self.assertIn('CANDIDATE_LIMIT_REACHED',r.warnings)

    def test_upstream_contamination_overlap_blocks_indexing(self):
        r,c=self.one('陆川击败韩岳，请记住本站。','defeats')
        self.assertFalse(c.may_index)
        self.assertIn('EVIDENCE_OVERLAPS_UPSTREAM_ANOMALY',c.validation_reason_codes)

    def test_artifacts_are_deterministic(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'x.txt'; p.write_text('陆川击败韩岳。',encoding='utf-8'); r=inspect_source_semantics(p)
            a=publish_semantic_artifacts(r,Path(td)/'a'); b=publish_semantic_artifacts(r,Path(td)/'b'); self.assertEqual(a,b)
            self.assertTrue((Path(td)/'a'/'accepted-claims.jsonl').exists()); self.assertTrue((Path(td)/'a'/'facts.jsonl').exists())

    def test_cli(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'x.txt'; p.write_text('陆川击败韩岳。',encoding='utf-8'); out=Path(td)/'out'
            self.assertEqual(main([str(p),'--outdir',str(out)]),0); self.assertTrue((out/'semantic-report.json').exists())

    def test_policy_validation(self):
        with self.assertRaises(SemanticExtractionError): SemanticPolicy(max_candidates=0)


if __name__=='__main__': unittest.main()
