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
from integrations.curriculum_v3.full_backup import FullBackup, MAX_FULL_BACKUP_BYTES
from integrations.curriculum_v3.registry import Archive, RegistryError
from integrations.reviewed_training.json_codec import decode


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--kb-dir',type=Path,default=DEFAULT_DIRECTORY)
    parser.add_argument('action',choices=['backup','restore','review','full-backup','full-restore'])
    parser.add_argument('--file',type=Path,required=True)
    parser.add_argument('--review-key-file',type=Path,default=None,help='Private key required for a complete backup containing review history')
    args = parser.parse_args()
    store = None
    try:
        if args.action in ('restore','full-restore'):
            # Bounded even if stat/size is misleading; reject duplicate keys.
            with args.file.open('rb') as source:
                limit=MAX_FULL_BACKUP_BYTES if args.action=='full-restore' else 1024*1024
                raw = source.read(limit+1)
            if len(raw)>limit:
                raise ValueError('Archive too large')
            archive = FullBackup.model_validate(decode(raw)) if args.action=='full-restore' else Archive.model_validate(decode(raw))
        store = SQLiteRegistry(args.kb_dir,review_key_file=args.review_key_file)
        if args.action == 'full-restore':
            result=store.restore_full(archive)
            print('Complete snapshot restored:',result)
        elif args.action == 'restore':
            result = store.import_archive(archive)
            print('Restored versions:',result['imported_versions'])
        else:
            if args.action=='full-backup':result=store.export_full()
            elif args.action=='backup':
                result=store.export()
                print('WARNING: knowledge-only JSON excludes evidence and review/revocation history. Use full-backup for complete recovery.')
            else:result=review_materials(store)
            raw = (json.dumps(result,ensure_ascii=False,indent=2)+'\n').encode()
            # Exclusive creation: never overwrite a backup or follow a symlink.
            fd = os.open(args.file,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
            try:
                with os.fdopen(fd,'wb') as output:
                    output.write(raw); output.flush(); os.fsync(output.fileno())
            except Exception:
                args.file.unlink(missing_ok=True)
                raise
            print('Complete snapshot exported; key not included' if args.action=='full-backup' else 'Local JSON exported; not a complete review-history backup')
    except (RegistryError, PersistenceError, ValueError, OSError, RecursionError):
        parser.exit(1,'Local knowledge operation rejected; check schema, version conflicts, private directory and output path. No reset performed.\n')
    finally:
        if store is not None:
            store.close()


if __name__=='__main__':main()
