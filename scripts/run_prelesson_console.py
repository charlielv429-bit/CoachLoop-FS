"""Start an interactive prelesson console on loopback; never deploy or use Coze."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from build_coze_prelesson_plugin import RedactedParser


def main():
    parser = RedactedParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8767)
    parser.add_argument('--kb-dir', type=Path, default=ROOT / '.local' / 'coachloop-kb', help='Private local shared knowledge directory (0700)')
    parser.add_argument('--review-key-file',type=Path,default=None,help='Optional private local operator review key; no web approval')
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error('Invalid local port')
    import uvicorn
    from integrations.prelesson.console import create_console_app
    from integrations.curriculum_v3.persistence import SQLiteRegistry, PersistenceError
    try:
        knowledge_store = SQLiteRegistry(args.kb_dir, review_key_file=args.review_key_file)
    except (PersistenceError, OSError, ValueError):
        parser.error('Local knowledge database unavailable; check directory permissions, schema and backup. No reset performed.')
    app = create_console_app(args.port, knowledge_store=knowledge_store)
    print(f'CoachLoop-FS interactive console: http://127.0.0.1:{args.port}', flush=True)
    print('Local only. Local SQLite knowledge persistence enabled. No production database, Coze or paid model calls. Ctrl+C to stop.', flush=True)
    uvicorn.run(app, host='127.0.0.1', port=args.port, access_log=False, log_level='warning', proxy_headers=False,
                limit_concurrency=32, timeout_keep_alive=5, timeout_graceful_shutdown=5)


if __name__ == '__main__':
    main()
