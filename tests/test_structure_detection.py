import json
import tempfile
import unittest
from pathlib import Path

from tkr.structure_artifacts import publish_structure_artifacts
from tkr.structure_cli import main as cli_main
from tkr.structure_detection import (
    StructureInspectionError,
    StructurePolicy,
    inspect_source_structure,
    parse_ordinal,
    validate_structure_report,
)

class StructureTests(unittest.TestCase):
    def make_file(self, root: Path, text: str, name='corpus.txt', encoding='utf-8', bom=False):
        p=root/name
        data=text.encode(encoding)
        if bom:
            prefix={'utf-8':b'\xef\xbb\xbf','utf-16-le':b'\xff\xfe','utf-16-be':b'\xfe\xff'}[encoding]
            data=prefix+data
        p.write_bytes(data)
        return p

    def test_parse_ordinals(self):
        cases={'1':1,'００２':2,'十':10,'十二':12,'二十':20,'一百零二':102,'两百三十一':231,'一万零三':10003}
        for raw,expected in cases.items(): self.assertEqual(parse_ordinal(raw),expected)
        self.assertIsNone(parse_ordinal('甲'))

    def test_numbered_chapters_cover_entire_source(self):
        with tempfile.TemporaryDirectory() as d:
            p=self.make_file(Path(d),'前置说明\n第一章 风起\n正文甲。\n第二章 云涌\n正文乙。\n')
            r=inspect_source_structure(p)
            validate_structure_report(r)
            self.assertEqual([u.unit_type for u in r.units],['front_matter','chapter','chapter'])
            self.assertEqual([u.ordinal for u in r.units],[None,1,2])
            self.assertEqual(r.coverage_ratio,1.0); self.assertEqual(r.gap_count,0); self.assertEqual(r.overlap_count,0)
            self.assertEqual(r.units[0].start_char,0); self.assertEqual(r.units[-1].end_char,len(p.read_text()))

    def test_volume_chapter_section_parent_hierarchy(self):
        with tempfile.TemporaryDirectory() as d:
            text='第一卷 上卷\n第一章 起\n正文\n第一节 初见\n细节\n第二章 承\n正文\n第二卷 下卷\n第一章 新篇\n正文\n'
            p=self.make_file(Path(d),text); r=inspect_source_structure(p)
            types=[u.unit_type for u in r.units]; self.assertEqual(types,['volume','chapter','section','chapter','volume','chapter'])
            self.assertEqual(r.units[1].parent_unit_id,r.units[0].unit_id)
            self.assertEqual(r.units[2].parent_unit_id,r.units[1].unit_id)
            self.assertEqual(r.units[3].parent_unit_id,r.units[0].unit_id)
            self.assertEqual(r.units[5].parent_unit_id,r.units[4].unit_id)

    def test_special_units(self):
        with tempfile.TemporaryDirectory() as d:
            p=self.make_file(Path(d),'序章 起源\n文\n第一章 正文\n文\n终章 落幕\n文\n番外 小事\n文\n后记\n文\n')
            r=inspect_source_structure(p)
            self.assertEqual([u.unit_type for u in r.units],['prologue','chapter','epilogue','extra_story','afterword'])

    def test_english_and_markdown_headings(self):
        with tempfile.TemporaryDirectory() as d:
            p=self.make_file(Path(d),'# Volume 1 Dawn\nintro\n## Chapter 1 Start\nbody\n### Free Form\nsection body\n',name='doc.md')
            r=inspect_source_structure(p)
            self.assertEqual([u.unit_type for u in r.units],['volume','chapter','section'])
            self.assertEqual(r.headings[-1].rule_id,'MARKDOWN_GENERIC_HEADING')

    def test_inline_title_and_body_same_line(self):
        with tempfile.TemporaryDirectory() as d:
            text='第一章 风起。天色已晚，陆川入城。\n第二章 云涌  正文从这里开始。\n'
            p=self.make_file(Path(d),text); r=inspect_source_structure(p)
            self.assertEqual(r.units[0].title,'风起')
            self.assertLess(r.units[0].body_start_char,r.units[0].end_char)
            self.assertEqual(r.units[1].title,'云涌')
            rules={f.rule_id for f in r.findings}; self.assertNotIn('EMPTY_UNIT_BODY_CANDIDATE',rules)

    def test_split_numbered_heading_across_lines(self):
        with tempfile.TemporaryDirectory() as d:
            p=self.make_file(Path(d),'第十二\n章 风雪\n正文。\n第十三章 归来\n正文。\n')
            r=inspect_source_structure(p)
            self.assertEqual(r.units[0].ordinal,12)
            self.assertEqual(r.headings[0].start_line,1); self.assertEqual(r.headings[0].end_line,2)
            self.assertEqual(r.units[0].start_char,0)

    def test_spaced_chinese_number_heading(self):
        with tempfile.TemporaryDirectory() as d:
            p=self.make_file(Path(d),'第 十 二 章 风雪\n正文\n')
            r=inspect_source_structure(p)
            self.assertEqual(r.units[0].ordinal,12)

    def test_fenced_code_heading_is_ignored(self):
        with tempfile.TemporaryDirectory() as d:
            p=self.make_file(Path(d),'```\n第一章 不是标题\n```\n第一章 真标题\n正文\n',name='doc.md')
            r=inspect_source_structure(p)
            self.assertEqual(r.accepted_heading_count,1)
            self.assertEqual(r.units[0].unit_type,'front_matter'); self.assertEqual(r.units[1].title,'真标题')

    def test_no_heading_fallback_document_unit(self):
        with tempfile.TemporaryDirectory() as d:
            text='只有正文，没有章节标题。\n第二行。\n'; p=self.make_file(Path(d),text)
            r=inspect_source_structure(p); self.assertEqual(len(r.units),1); self.assertEqual(r.units[0].unit_type,'document')
            self.assertEqual(r.units[0].content_sha256, __import__('hashlib').sha256(text.encode()).hexdigest())

    def test_duplicate_gap_and_inversion_findings(self):
        with tempfile.TemporaryDirectory() as d:
            text='第一章 A\n文\n第三章 C\n文\n第三章 D\n文\n第二章 B\n文\n'; p=self.make_file(Path(d),text)
            r=inspect_source_structure(p); rules={f.rule_id for f in r.findings}
            self.assertIn('ORDINAL_GAP_CANDIDATE',rules); self.assertIn('DUPLICATE_ORDINAL_CANDIDATE',rules); self.assertIn('ORDINAL_INVERSION_CANDIDATE',rules)

    def test_duplicate_title_and_empty_body(self):
        with tempfile.TemporaryDirectory() as d:
            p=self.make_file(Path(d),'第一章 同名\n第二章 同名\n正文\n')
            r=inspect_source_structure(p); rules={f.rule_id for f in r.findings}
            self.assertIn('DUPLICATE_TITLE_CANDIDATE',rules); self.assertIn('EMPTY_UNIT_BODY_CANDIDATE',rules)

    def test_epilogue_placement_candidates(self):
        with tempfile.TemporaryDirectory() as d:
            p=self.make_file(Path(d),'第一章 A\n文\n终章 Z\n文\n第二章 B\n文\n序章 P\n文\n')
            r=inspect_source_structure(p); rules={f.rule_id for f in r.findings}
            self.assertIn('CHAPTER_AFTER_EPILOGUE_CANDIDATE',rules); self.assertIn('LATE_FRONT_MATTER_CANDIDATE',rules)

    def test_utf8_bom_and_utf16_offsets(self):
        for encoding in ('utf-8','utf-16-le','utf-16-be'):
            with self.subTest(encoding=encoding), tempfile.TemporaryDirectory() as d:
                text='第一章 起\n正文\n'; p=self.make_file(Path(d),text,encoding=encoding,bom=True)
                r=inspect_source_structure(p); self.assertEqual(r.scanned_character_count,len(text)); self.assertEqual(r.units[0].start_char,0)

    def test_unsupported_source_is_blocked(self):
        with tempfile.TemporaryDirectory() as d:
            p=self.make_file(Path(d),'第一章\n正文\n',name='x.bin')
            r=inspect_source_structure(p); self.assertEqual(r.scan_status,'blocked'); self.assertFalse(r.units); self.assertFalse(r.may_accept_project)

    def test_policy_validation(self):
        with self.assertRaises(StructureInspectionError): StructurePolicy(max_units=0)
        with self.assertRaises(StructureInspectionError): StructurePolicy(accept_markdown_headings=1)

    def test_deterministic_results(self):
        with tempfile.TemporaryDirectory() as d:
            p=self.make_file(Path(d),'第一章 A\n正文\n第二章 B\n正文\n')
            a=inspect_source_structure(p); b=inspect_source_structure(p)
            self.assertEqual(a.to_dict(),b.to_dict())

    def test_artifact_publication_is_deterministic(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); p=self.make_file(root,'第一章 A\n正文\n第二章 B\n正文\n')
            r=inspect_source_structure(p); m1=publish_structure_artifacts(r,root/'out1'); m2=publish_structure_artifacts(r,root/'out2')
            self.assertEqual(m1,m2)
            names={x['name'] for x in m1['files']}
            self.assertEqual(names,{'structure-report.json','heading-candidates.jsonl','unit-index.jsonl','structure-anomalies.jsonl','unit-ledger.csv','stage-result.json'})
            stage=json.loads((root/'out1/stage-result.json').read_text()); self.assertFalse(stage['project_acceptance_performed'])

    def test_cli_writes_standard_artifacts(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); p=self.make_file(root,'第一章 A\n正文\n')
            self.assertEqual(cli_main([str(p),'--outdir',str(root/'out')]),0)
            self.assertTrue((root/'out/unit-index.jsonl').exists()); self.assertTrue((root/'out/artifact-manifest.json').exists())

    def test_detached_title_recovery_candidate(self):
        with tempfile.TemporaryDirectory() as d:
            p=self.make_file(Path(d),'第一章\n风雪夜归人\n正文从这里开始。\n')
            r=inspect_source_structure(p)
            finding=next(f for f in r.findings if f.rule_id=='DETACHED_TITLE_CANDIDATE')
            self.assertEqual(finding.start_line,2)
            self.assertIn('candidate_text=风雪夜归人',finding.signals)

    def test_unit_limit_does_not_truncate_source_scan(self):
        with tempfile.TemporaryDirectory() as d:
            text='第一章 A\n正文\n第二章 B\n正文\n第三章 C\n正文\n'
            p=self.make_file(Path(d),text)
            r=inspect_source_structure(p,policy=StructurePolicy(max_units=2))
            self.assertEqual(r.scanned_character_count,len(text))
            self.assertEqual(r.coverage_character_count,len(text))
            self.assertEqual(len(r.units),2)
            self.assertIn('UNIT_LIMIT_REACHED',r.warnings)
            self.assertTrue(any(not h.accepted_as_boundary for h in r.headings))

if __name__=='__main__': unittest.main()
