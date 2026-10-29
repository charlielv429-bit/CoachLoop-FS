"""PYTHONPATH=src python -m integrations.prelesson --input synthetic-request.json"""
import argparse
import sys
from pathlib import Path
from pydantic import ValidationError
from graphs.prelesson_graph import run_prelesson
from integrations.reviewed_training.json_codec import decode


def main():
    parser=argparse.ArgumentParser(description='Local prelesson draft workflow; no database or network')
    parser.add_argument('--input',required=True,help='JSON file or - for stdin')
    args=parser.parse_args()
    try:
        if args.input=='-':
            raw=sys.stdin.buffer.read(1024*1024+1)
        else:
            with Path(args.input).open('rb') as stream:raw=stream.read(1024*1024+1)
        if len(raw)>1024*1024:raise ValueError('Input exceeds 1 MiB')
        result=run_prelesson(decode(raw))
    except (OSError,ValueError,ValidationError,RecursionError):
        print('Invalid prelesson input; use the published schema.',file=sys.stderr)
        return 2
    print(result.model_dump_json(indent=2))
    return 0


if __name__=='__main__':
    raise SystemExit(main())
