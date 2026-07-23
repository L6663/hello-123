from pathlib import Path

path = Path("tkr/reasoning_engine.py")
text = path.read_text(encoding="utf-8")
old = '''        if self.layer == "A":
            if not self.upstream_record_ids or not self.evidence_anchor_ids:
                raise ReasoningEngineError("layer A requires upstream records and exact evidence")
            if self.support_node_ids:
'''
new = '''        if self.layer == "A":
            if not self.upstream_record_ids or not self.evidence_anchor_ids:
                raise ReasoningEngineError("layer A requires upstream records and exact evidence")
            if not self.chapter_ids:
                raise ReasoningEngineError("layer A requires at least one chapter location")
            if len(self.independence_groups) != 1:
                raise ReasoningEngineError("layer A requires exactly one evidence-independence group")
            if self.support_node_ids:
'''
if text.count(old) != 1:
    raise SystemExit(f"expected one layer A contract block, found {text.count(old)}")
path.write_text(text.replace(old, new), encoding="utf-8", newline="\n")
