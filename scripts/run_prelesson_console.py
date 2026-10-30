"""Start an interactive prelesson console on loopback; never deploy or use Coze."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from build_coze_prelesson_plugin import RedactedParser


def main():
    parser = RedactedParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8767)
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error('Invalid local port')
    import uvicorn
    from integrations.prelesson.console import create_console_app
    app = create_console_app(args.port)
    print(f'CoachLoop-FS interactive console: http://127.0.0.1:{args.port}', flush=True)
    print('Local only. No Coze, production credentials, database or paid model calls. Ctrl+C to stop.', flush=True)
    uvicorn.run(app, host='127.0.0.1', port=args.port, access_log=False, log_level='warning')


if __name__ == '__main__':
    main()
