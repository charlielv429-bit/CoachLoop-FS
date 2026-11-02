"""Offline local operator workflow, separate from ordinary edits/imports.

A machine authentication tag does not certify a specialist identity or signature.
All reviewer/date/content fields must come from supplied human evidence.
"""
import argparse
import json
import os
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from integrations.reviewed_training.json_codec import decode
from integrations.curriculum_v3.review import EvidenceReport, EvidenceBundle, ReviewDecision, AuthenticatedDecision, read_key, seal
from integrations.curriculum_v3.persistence import SQLiteRegistry, DEFAULT_DIRECTORY


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['register-report','register-reports','seal-decision','apply-decision'])
    parser.add_argument('--input',type=Path,required=True)
    parser.add_argument('--kb-dir',type=Path,default=DEFAULT_DIRECTORY)
    parser.add_argument('--review-key-file',type=Path)
    parser.add_argument('--output',type=Path)
    parser.add_argument('--source-artifact',type=Path)
    parser.add_argument('--specialist-artifact',type=Path)
    args=parser.parse_args();store=None
    try:
        with args.input.open('rb') as file:raw=file.read(1024*1024+1)
        if len(raw)>1024*1024:raise ValueError('Input too large')
        value=decode(raw)
        if args.action=='seal-decision':
            if args.output is None or args.review_key_file is None:raise ValueError('Private key/output required')
            result=seal(ReviewDecision.model_validate(value).model_dump(),read_key(args.review_key_file)).model_dump()
            fd=os.open(args.output,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
            with os.fdopen(fd,'w') as file:json.dump(result,file,ensure_ascii=False,indent=2);file.flush();os.fsync(file.fileno())
        else:
            store=SQLiteRegistry(args.kb_dir,review_key_file=args.review_key_file)
            if args.action=='register-report':result=store.save_report(EvidenceReport.model_validate(value))
            elif args.action=='register-reports':result=store.save_reports(EvidenceBundle.model_validate(value).reports)
            else:result=store.apply_decision(AuthenticatedDecision.model_validate(value),source_artifact=args.source_artifact,specialist_artifact=args.specialist_artifact)
        print('Offline operation completed; machine authentication is not professional certification')
    except Exception:
        parser.exit(1,'Review operation rejected; verify bindings, source evidence, private key and schema. No approval inferred.\n')
    finally:
        if store is not None:store.close()

if __name__=='__main__':main()
