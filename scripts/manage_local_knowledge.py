"""Offline local KB JSON backup/restore and review export. Stop console first.

No approval flags, teacher authentication, production DB or remote IO.
"""
import argparse
import os
from pathlib import Path
import sys
import json

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from integrations.curriculum_v3.persistence import SQLiteRegistry, DEFAULT_DIRECTORY, review_materials, PersistenceError
from integrations.curriculum_v3.registry import Archive, RegistryError
from integrations.reviewed_training.json_codec import decode


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--kb-dir',type=Path,default=DEFAULT_DIRECTORY)
    parser.add_argument('action',choices=['backup','restore','review'])
    parser.add_argument('--file',type=Path,required=True)
    args = parser.parse_args()
    store = None
    try:
        if args.action == 'restore':
            # Bounded even if stat/size is misleading; reject duplicate keys.
            with args.file.open('rb') as source:
                raw = source.read(1024*1024+1)
            if len(raw)>1024*1024:
                raise ValueError('Archive too large')
            archive = Archive.model_validate(decode(raw))
        store = SQLiteRegistry(args.kb_dir)
        if args.action == 'restore':
            result = store.import_archive(archive)
            print('Restored versions:',result['imported_versions'])
        else:
            result = store.export() if args.action == 'backup' else review_materials(store)
            raw = (json.dumps(result,ensure_ascii=False,indent=2)+'\n').encode()
            # Exclusive creation: never overwrite a backup or follow a symlink.
            fd = os.open(args.file,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
            try:
                with os.fdopen(fd,'wb') as output:
                    output.write(raw); output.flush(); os.fsync(output.fileno())
            except Exception:
                args.file.unlink(missing_ok=True)
                raise
            print('Local JSON exported; pending review only')
    except (RegistryError, PersistenceError, ValueError, OSError, RecursionError):
        parser.exit(1,'Local knowledge operation rejected; check schema, version conflicts, private directory and output path. No reset performed.\n')
    finally:
        if store is not None:
            store.close()


if __name__=='__main__':main()
