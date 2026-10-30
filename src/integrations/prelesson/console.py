"""Loopback-only interactive console; separate from production main and Coze.

A same-origin HttpOnly session authorizes the browser. After CSRF/host checks,
this local boundary injects an ephemeral internal Bearer into the unchanged API.
No production credential, external service, database or teacher approval is used.
"""
import hmac
from pathlib import Path
import secrets

from fastapi import FastAPI
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse

from .api import create_router
from .adaptive_api import create_adaptive_router, ADAPTIVE, CATALOGUE, LOCAL_AUTH

STATIC = Path(__file__).with_name('console_static')
COOKIE = 'coachloop_local_console'
CANONICAL = '/api/v1/lesson-plans/draft'
ALLOWED = {('GET', '/'), ('GET', '/console.js'), ('GET', '/console.css'),
           ('GET', '/health'), ('POST', CANONICAL), ('GET', CATALOGUE), ('POST', ADAPTIVE)}
SECURITY_HEADERS = {
    'Cache-Control': 'no-store', 'Referrer-Policy': 'no-referrer',
    'X-Content-Type-Options': 'nosniff', 'X-Frame-Options': 'DENY',
    'Content-Security-Policy': "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
    'Permissions-Policy': 'camera=(), microphone=(), geolocation=()',
}


class LocalBoundary:
    def __init__(self, app, port, session, bearer):
        self.app, self.host = app, f'127.0.0.1:{port}'
        self.origin, self.session, self.bearer = 'http://' + self.host, session, bearer

    async def __call__(self, scope, receive, send):
        if scope['type'] == 'websocket':
            return await send({'type': 'websocket.close', 'code': 1008})
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        async def secured(message):
            if message['type'] == 'http.response.start':
                original = message.get('headers', [])
                names = {name.lower().encode() for name in SECURITY_HEADERS}
                message = {**message, 'headers': [(k, v) for k, v in original if k.lower() not in names]
                    + [(k.lower().encode(), v.encode()) for k, v in SECURITY_HEADERS.items()]}
            await send(message)
        async def reject(status, detail):
            return await JSONResponse({'detail': detail}, status_code=status)(scope, receive, secured)
        request = Request(scope)
        headers = scope.get('headers', [])
        hosts = [v.decode('latin1') for k, v in headers if k.lower() == b'host']
        if (not scope.get('client') or scope['client'][0] != '127.0.0.1'
                or scope.get('scheme') != 'http' or hosts != [self.host]
                or any(k.lower() in (b'forwarded', b'x-forwarded-for', b'x-forwarded-host', b'x-real-ip') for k, _ in headers)):
            return await reject(403, 'Local console accepts direct loopback requests only')
        if (scope['method'], scope['path']) not in ALLOWED:
            return await reject(404, 'Route unavailable in local console')
        if request.headers.get('sec-fetch-site') == 'cross-site':
            return await reject(403, 'Cross-site access refused')
        if request.headers.get('origin') not in (None, self.origin):
            return await reject(403, 'Cross-origin access refused')
        if scope['method'] == 'POST':
            cookie = request.cookies.get(COOKIE, '')
            if not cookie or not hmac.compare_digest(cookie.encode(), self.session.encode()):
                return await reject(401, 'Open the local console to start a session')
            origins = [v.decode('latin1') for k, v in headers if k.lower() == b'origin']
            if (origins != [self.origin] or request.headers.get('x-coachloop-console') != '1'
                    or request.headers.get('content-type', '').split(';')[0].strip().lower() != 'application/json'
                    or any(k.lower() == b'authorization' for k, _ in headers)):
                return await reject(403, 'Local session and same-origin JSON request required')
            scope = {**scope, 'coachloop_local_auth': LOCAL_AUTH, 'headers': [*headers, (b'authorization', ('Bearer ' + self.bearer).encode())]}
        return await self.app(scope, receive, secured)


def create_console_app(port: int = 8767):
    if type(port) is not int or not 1 <= port <= 65535:
        raise ValueError('Local port must be an integer from 1 to 65535')
    session, bearer = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    app.include_router(create_router(access_token=bearer))
    app.include_router(create_adaptive_router())
    @app.get('/')
    def index():
        response = FileResponse(STATIC / 'index.html', media_type='text/html')
        response.set_cookie(COOKIE, session, httponly=True, samesite='strict', secure=False)
        return response
    @app.get('/console.js')
    def javascript():
        return FileResponse(STATIC / 'console.js', media_type='text/javascript')
    @app.get('/console.css')
    def stylesheet():
        return FileResponse(STATIC / 'console.css', media_type='text/css')
    @app.get('/health')
    def health():
        return {'status': 'ok', 'mode': 'local_interactive_console', 'database': 'not_used'}
    app.add_middleware(LocalBoundary, port=port, session=session, bearer=bearer)
    return app
