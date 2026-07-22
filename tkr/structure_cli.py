"""CLI for deterministic heading candidates, Unit Index, and structure findings."""
from __future__ import annotations
import argparse, json
from pathlib import Path
from typing import Sequence
from .structure_artifacts import publish_structure_artifacts
from .structure_detection import StructureInspectionError, StructurePolicy, inspect_source_structure

def build_parser():
    p=argparse.ArgumentParser(prog="tkr-structure-index",description="Build a deterministic source-covering Unit Index; no project acceptance is performed.")
    p.add_argument("source",type=Path)
    out=p.add_mutually_exclusive_group(); out.add_argument("--output",type=Path); out.add_argument("--outdir",type=Path)
    p.add_argument("--max-heading-characters",type=int,default=160)
    p.add_argument("--max-units",type=int,default=200000)
    p.add_argument("--max-findings",type=int,default=50000)
    p.add_argument("--no-markdown-headings",action="store_true")
    p.add_argument("--no-split-numbered-headings",action="store_true")
    p.add_argument("--no-empty-body-candidates",action="store_true")
    return p

def main(argv:Sequence[str]|None=None)->int:
    args=build_parser().parse_args(argv)
    try:
        policy=StructurePolicy(max_heading_characters=args.max_heading_characters,max_units=args.max_units,max_findings=args.max_findings,
                               accept_markdown_headings=not args.no_markdown_headings,
                               accept_split_numbered_heading=not args.no_split_numbered_headings,
                               emit_empty_body_candidates=not args.no_empty_body_candidates)
        report=inspect_source_structure(args.source,policy=policy)
        if args.outdir is not None:
            print(json.dumps(publish_structure_artifacts(report,args.outdir),ensure_ascii=False,sort_keys=True)); return 0
        payload=json.dumps(report.to_dict(),ensure_ascii=False,indent=2,sort_keys=True)+"\n"
        if args.output is None: print(payload,end="")
        else:
            args.output.parent.mkdir(parents=True,exist_ok=True); tmp=args.output.with_name(f".{args.output.name}.tmp")
            tmp.write_text(payload,encoding="utf-8",newline="\n"); tmp.replace(args.output)
    except (OSError,TypeError,ValueError,StructureInspectionError) as exc:
        raise SystemExit(f"structure index failed: {exc}") from exc
    return 0
if __name__=="__main__": raise SystemExit(main())
