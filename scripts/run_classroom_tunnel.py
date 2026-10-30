"""Explicit, temporary Quick Tunnel for synthetic classroom use only.

No account, named tunnel, production config, public bind or database. Cloudflared
and optional QR extra must already exist. Run with --enable-classroom-tunnel.
Ctrl+C or stop_classroom_tunnel.command revokes sessions and stops our child.
"""
import argparse
import contextlib
import fcntl
import hashlib
import json
import os
from pathlib import Path
import queue
import re
import secrets
import shutil
import socket
import stat
import subprocess
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))


def default_state_dir():
    suffix = hashlib.sha256(str(ROOT).encode()).hexdigest()[:12]
    return Path.home() / 'Library' / 'Caches' / 'CoachLoop-FS' / ('classroom-' + suffix)


def private_directory(path):
    path = Path(path)
    # Reject symlinked ancestors rather than writing a control channel elsewhere.
    for parent in [*reversed(path.parents), path]:
        if parent.is_symlink():
            raise RuntimeError('Classroom state directory must not use symlinks')
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    info = path.stat()
    if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
        raise RuntimeError('Classroom state directory must be owned by this user and mode 700')
    return path


def acquire_lock(directory):
    fd = os.open(directory / 'run.lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    file = os.fdopen(fd, 'w')
    try:
        fcntl.flock(file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        file.close()
        raise RuntimeError('A classroom demo is already running for this project') from None
    return file


def quick_origin(line):
    from integrations.prelesson.classroom import checked_origin
    for candidate in re.findall(r'https://[^\s"<>|]+', line):
        try:
            return checked_origin(candidate)
        except ValueError:
            continue
    return None


def tunnel_command(binary, directory, port):
    return [binary, 'tunnel', '--no-autoupdate', '--config', str(directory / 'empty-config.yml'),
            '--url', f'http://127.0.0.1:{port}', '--protocol', 'http2',
            '--metrics', '127.0.0.1:0', '--loglevel', 'info']


def tunnel_environment():
    # Do not inherit a named tunnel/account token, database or app credential.
    blocked = ('TUNNEL_', 'CLOUDFLARED_', 'CF_API', 'CLOUDFLARE_', 'PG', 'DATABASE', 'COACHLOOP_', 'TEACHING_')
    return {k: v for k, v in os.environ.items() if not k.startswith(blocked)}


def make_qr(origin, destination):
    from integrations.prelesson.classroom import checked_origin
    checked_origin(origin)
    try:
        import qrcode
        import qrcode.image.svg
    except ImportError:
        return False
    qrcode.make(origin, image_factory=qrcode.image.svg.SvgPathImage, border=4).save(destination)
    os.chmod(destination, 0o600)
    return True


def request_stop(directory):
    directory = private_directory(directory)
    # A lock, not a remembered PID, proves our supervisor is still running.
    fd = os.open(directory / 'run.lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'w') as file:
        try:
            fcntl.flock(file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            fd = os.open(directory / 'STOP', os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
            os.close(fd)
            return True
        return False


def run(directory, minutes):
    import uvicorn
    from integrations.prelesson.classroom import DemoState, create_classroom_app
    binary = shutil.which('cloudflared')
    if not binary:
        raise RuntimeError('cloudflared is missing. Install the official Cloudflare client first; no service was exposed.')
    with acquire_lock(directory):
        if (directory / 'STOP').exists():
            (directory / 'STOP').unlink()
            print('An earlier stop request was found. No classroom started; launch again explicitly.')
            return
        for filename in ('origin.json', 'classroom-qr.svg'):
            (directory / filename).unlink(missing_ok=True)
        config_path = directory / 'empty-config.yml'
        fd = os.open(config_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'w') as file:
            file.write('{}\n')
        code = secrets.token_urlsafe(24)
        state = DemoState(code, duration=minutes * 60)
        server = None; worker = None; tunnel = None
        with contextlib.closing(socket.socket()) as listener:
            listener.bind(('127.0.0.1', 0)); listener.listen(128)
            port = listener.getsockname()[1]
            try:
                server = uvicorn.Server(uvicorn.Config(create_classroom_app(state), proxy_headers=False,
                    access_log=False, log_level='error', limit_concurrency=32, timeout_keep_alive=5))
                worker = threading.Thread(target=lambda: server.run(sockets=[listener]), daemon=True)
                worker.start()
                deadline = time.monotonic() + 15
                while not server.started:
                    if not worker.is_alive() or time.monotonic() > deadline:
                        raise RuntimeError('Classroom origin failed to start')
                    time.sleep(.05)
                if (directory / 'STOP').exists(): return
                # No origin is trusted yet: all HTTP requests currently fail closed.
                tunnel = subprocess.Popen(tunnel_command(binary, directory, port), env=tunnel_environment(),
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
                lines = queue.Queue(maxsize=256)
                def read_logs():
                    for line in tunnel.stdout:
                        # Raw cloudflared logs never reach terminal or disk.
                        # Keep only bounded candidate-URL lines.
                        origin = quick_origin(line[:4096])
                        if origin:
                            try: lines.put_nowait(origin)
                            except queue.Full: pass
                reader = threading.Thread(target=read_logs, daemon=True); reader.start()
                deadline = time.monotonic() + 90
                origin = None
                while origin is None:
                    if (directory / 'STOP').exists(): return
                    if tunnel.poll() is not None or time.monotonic() > deadline:
                        raise RuntimeError('Quick Tunnel did not become ready; no usable public classroom was enabled')
                    try: origin = lines.get(timeout=.1)
                    except queue.Empty: pass
                state.pin(origin)
                meta = {'origin': origin, 'data_domain': 'mock', 'public_verified': False, 'maximum_minutes': minutes}
                (directory / 'origin.json').write_text(json.dumps(meta, indent=2)+'\n')
                os.chmod(directory / 'origin.json', 0o600)
                print('Classroom HTTPS URL: ' + origin, flush=True)
                print('Classroom access code (share separately, never put in URL/QR): ' + code, flush=True)
                print('Only synthetic data. This is not teacher identity or approval.', flush=True)
                print('Public end-to-end access is NOT verified by tunnel startup.', flush=True)
                if make_qr(origin, directory / 'classroom-qr.svg'):
                    print('URL-only QR: ' + str(directory / 'classroom-qr.svg'), flush=True)
                    if sys.platform == 'darwin':
                        subprocess.run(['/usr/bin/open', str(directory / 'classroom-qr.svg')], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                else:
                    print('QR unavailable: optional qrcode extra missing; the HTTPS URL can still be shared.', flush=True)
                print(f'Expires in {minutes} minutes. Keep this terminal open. Ctrl+C or double-click stop script to revoke access.', flush=True)
                while state.active() and not (directory / 'STOP').exists():
                    if tunnel.poll() is not None or not worker.is_alive():
                        raise RuntimeError('Classroom process stopped unexpectedly; sessions revoked')
                    time.sleep(.1)
            finally:
                # Revoke first, even while a slow cloudflared shutdown is pending.
                state.close()
                if tunnel is not None:
                    if tunnel.poll() is None:
                        tunnel.terminate()
                        try: tunnel.wait(timeout=5)
                        except subprocess.TimeoutExpired: tunnel.kill();tunnel.wait(timeout=5)
                    if tunnel.stdout: tunnel.stdout.close()
                if server is not None:
                    server.should_exit = True
                if worker is not None:
                    worker.join(timeout=5)
                (directory / 'origin.json').unlink(missing_ok=True)
                (directory / 'classroom-qr.svg').unlink(missing_ok=True)
                (directory / 'STOP').unlink(missing_ok=True)
                print('Classroom stopped; sessions revoked and tunnel closed.', flush=True)


def supervisor_running(directory):
    try:
        with acquire_lock(directory):
            return False
    except RuntimeError:
        return True


class SafeParser(argparse.ArgumentParser):
    def error(self, message):
        self.exit(2, 'Invalid classroom options; public mode requires explicit --enable-classroom-tunnel.\n')


def main():
    parser = SafeParser(description=__doc__)
    parser.add_argument('--enable-classroom-tunnel', action='store_true')
    parser.add_argument('--stop', action='store_true')
    parser.add_argument('--minutes', type=int, default=90, choices=range(5, 181), metavar='5..180')
    parser.add_argument('--state-dir', type=Path, default=default_state_dir())
    args = parser.parse_args()
    if not args.enable_classroom_tunnel and not args.stop:
        parser.error('Public mode is disabled: explicit --enable-classroom-tunnel is required')
    try:
        directory = private_directory(args.state_dir)
        if args.stop:
            if not request_stop(directory):
                print('No active classroom supervisor. Nothing was killed.')
                return 0
            deadline = time.monotonic() + 12
            while supervisor_running(directory) and time.monotonic() < deadline:
                time.sleep(.1)
            if supervisor_running(directory):
                raise RuntimeError('Stop was requested but shutdown is not yet confirmed; use the original terminal Ctrl+C')
            print('Classroom shutdown confirmed.')
            return 0
        run(directory, args.minutes)
    except KeyboardInterrupt:
        return 0
    except (RuntimeError, OSError, ImportError):
        # No command arguments, environment, access codes or child logs in errors.
        print('Classroom startup/stop failed. Check cloudflared installation, private directory permissions, network and the existing terminal. No public success is claimed.', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
