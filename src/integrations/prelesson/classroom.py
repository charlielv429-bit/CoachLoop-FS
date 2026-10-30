"""Explicit temporary classroom boundary, separate from LocalBoundary.

Only cloudflared's direct IPv4 loopback connection is accepted. Uvicorn MUST
run with proxy_headers=False. Forwarded IPs never confer identity or rate budget.
The exact HTTPS origin is pinned once from this launch's Quick Tunnel output.
Shared classroom code authorizes mock generation, never teacher approval.
"""
from collections import deque
import hmac
import json
import re
import secrets
import threading
import time
from typing import Literal

from fastapi import APIRouter, FastAPI, Request, HTTPException
from pydantic import Field, field_validator, model_validator, model_serializer
from starlette.responses import FileResponse, HTMLResponse, JSONResponse, Response

from agents.lesson_plan_agent.adaptive import AdaptiveRequest, AdaptiveResponse, StrictModel, catalogue, generate_adaptive
from .api import PrelessonRoute
from .adaptive_api import ADAPTIVE, CATALOGUE
from .console import STATIC, SECURITY_HEADERS

COOKIE = '__Host-coachloop_classroom'
CLASSROOM_AUTH = object()
PUBLIC = {('GET', '/'), ('GET', '/classroom-login.js'), ('GET', '/console.css'), ('GET', '/health'), ('POST', '/classroom/login')}
PRIVATE = {('GET', '/console.js'), ('GET', CATALOGUE), ('POST', ADAPTIVE), ('POST', '/classroom/logout')}


def checked_origin(value):
    if not isinstance(value, str) or len(value) > 253 or re.fullmatch(r'https://[a-z0-9]+(?:-[a-z0-9]+)*\.trycloudflare\.com', value) is None:
        raise ValueError('An exact HTTPS Quick Tunnel origin is required')
    return value


class DemoState:
    def __init__(self, code, *, duration=5400, clock=time.monotonic):
        if not isinstance(code, str) or re.fullmatch(r'[A-Za-z0-9_-]{24,128}', code) is None:
            raise ValueError('A fresh strong classroom code is required')
        if type(duration) is not int or not 300 <= duration <= 10800:
            raise ValueError('Classroom lifetime must be 5 to 180 minutes')
        self._code = code
        self.clock, self.end = clock, clock() + duration
        self.origin = None
        self.closed = False
        self.sessions = {}
        self.budgets = {}
        self.lock = threading.Lock()

    def pin(self, origin):
        origin = checked_origin(origin)
        with self.lock:
            if self.origin is not None or self.closed:
                raise ValueError('Classroom origin cannot be changed during a run')
            self.origin = origin

    def active(self):
        return not self.closed and self.origin is not None and self.clock() < self.end

    def consume(self, key, maximum):
        """Sliding minute, process-global or authenticated-session budgets only."""
        with self.lock:
            now = self.clock()
            budget = self.budgets.setdefault(key, deque())
            while budget and budget[0] <= now - 60:
                budget.popleft()
            if len(budget) >= maximum:
                return False
            budget.append(now)
            return True

    def login(self, code):
        with self.lock:
            if not self.active() or not hmac.compare_digest(code.encode(), self._code.encode()):
                return None
            now = self.clock()
            for key, end in list(self.sessions.items()):
                if end <= now:
                    self.sessions.pop(key, None)
                    self.budgets.pop('session:' + key, None)
            if len(self.sessions) >= 64:
                return None
            token = secrets.token_urlsafe(32)
            self.sessions[token] = min(now + 3600, self.end)
            return token

    def authorized(self, token):
        with self.lock:
            return self.active() and bool(token) and self.sessions.get(token, 0) > self.clock()

    def logout(self, token):
        with self.lock:
            self.sessions.pop(token, None)
            self.budgets.pop('session:' + token, None)

    def close(self):
        with self.lock:
            self.closed = True
            self.sessions.clear()
            self.budgets.clear()
            self._code = ''


class ClassroomRequest(AdaptiveRequest):
    data_domain: Literal['mock']
    is_mock: Literal[True]
    class_label: str = Field(pattern=r'^MOCK-[A-Z0-9_-]{1,60}$')

    @field_validator('is_mock', mode='before')
    @classmethod
    def real_boolean(cls, value):
        if value is not True:
            raise ValueError('Explicit synthetic-data declaration required')
        return value


class ClassroomResult(StrictModel):
    data_domain: Literal['mock'] = 'mock'
    is_mock: Literal[True] = True
    human_review_performed: Literal[False] = False
    draft: AdaptiveResponse

    @model_validator(mode='after')
    def check_mock(self):
        if self.data_domain != 'mock' or self.is_mock is not True or self.human_review_performed is not False:
            raise ValueError('Classroom result must remain synthetic and unreviewed')
        ClassroomRequest.model_validate({**self.draft.request.model_dump(), 'data_domain': 'mock', 'is_mock': True})
        return self

    @model_serializer(mode='wrap')
    def guarded_export(self, handler):
        self.check_mock()
        return handler(self)


class LoginRequest(StrictModel):
    code: str = Field(min_length=1, max_length=128, pattern=r'^[A-Za-z0-9_-]+$')
    mock_acknowledged: Literal[True]

    @field_validator('mock_acknowledged', mode='before')
    @classmethod
    def acknowledged(cls, value):
        if value is not True:
            raise ValueError('Synthetic data acknowledgement required')
        return value


def classroom_session(request):
    if request.scope.get('classroom_auth') is not CLASSROOM_AUTH:
        raise HTTPException(401, 'Classroom login required')


class ClassroomBoundary:
    def __init__(self, app, state):
        self.app, self.state = app, state

    async def __call__(self, scope, receive, send):
        if scope['type'] == 'websocket':
            return await send({'type': 'websocket.close', 'code': 1008})
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        async def secured(message):
            if message['type'] == 'http.response.start':
                headers = {**SECURITY_HEADERS, 'Strict-Transport-Security': 'max-age=3600'}
                names = {k.lower().encode() for k in headers}
                message = {**message, 'headers': [(k, v) for k, v in message.get('headers', []) if k.lower() not in names]
                           + [(k.lower().encode(), v.encode()) for k, v in headers.items()]}
            await send(message)
        async def reject(status, detail):
            return await JSONResponse({'detail': detail}, status_code=status,
                headers={'Retry-After': '60'} if status == 429 else {})(scope, receive, secured)
        if not self.state.active():
            return await reject(503, 'Classroom demo is not active')
        headers = scope.get('headers', [])
        def values(name):
            return [v.decode('latin1') for k, v in headers if k.lower() == name]
        host = self.state.origin.removeprefix('https://')
        # Inspect raw peer/scheme, never an X-Forwarded-For rewritten scope.
        if (not scope.get('client') or scope['client'][0] != '127.0.0.1' or scope['scheme'] != 'http'
                or values(b'host') != [host] or values(b'x-forwarded-proto') != ['https']
                or values(b'forwarded') or values(b'authorization')
                or values(b'x-forwarded-host') not in ([], [host])):
            return await reject(403, 'Classroom proxy boundary refused request')
        visitor = values(b'cf-visitor')
        if visitor:
            try:
                if len(visitor) != 1 or json.loads(visitor[0]) != {'scheme': 'https'}:
                    return await reject(403, 'HTTPS proxy metadata required')
            except (ValueError, TypeError):
                return await reject(403, 'HTTPS proxy metadata required')
        request = Request(scope)
        # Sharing a link from a classroom chat may be a cross-site top-level
        # navigation. Permit ONLY the inert root document, never fetches/iframes
        # or actions; no cookie/session is issued by GET.
        shared_navigation = (scope['method'] == 'GET' and scope['path'] == '/'
            and request.headers.get('sec-fetch-mode') == 'navigate'
            and request.headers.get('sec-fetch-dest') == 'document' and not values(b'origin'))
        if (values(b'origin') not in ([], [self.state.origin])
                or (request.headers.get('sec-fetch-site') == 'cross-site' and not shared_navigation)):
            return await reject(403, 'Same-origin classroom access required')
        pair = scope['method'], scope['path']
        if pair not in PUBLIC | PRIVATE:
            return await reject(404, 'Route unavailable in classroom demo')
        if scope.get('query_string'):
            return await reject(400, 'Query parameters are not accepted')
        if not self.state.consume('requests', 900):
            return await reject(429, 'Classroom request limit reached')
        cookies = request.cookies
        token = cookies.get(COOKIE, '')
        authenticated = self.state.authorized(token)
        if pair in PRIVATE and not authenticated:
            return await reject(401, 'Classroom login required')
        if pair[0] == 'POST':
            if (values(b'origin') != [self.state.origin] or values(b'x-coachloop-console') != ['1']
                    or len(values(b'content-type')) != 1
                    or request.headers.get('content-type', '').split(';')[0].strip().lower() != 'application/json'):
                return await reject(403, 'Same-origin JSON and CSRF header required')
            if pair[1] == '/classroom/login' and not self.state.consume('login', 10):
                return await reject(429, 'Classroom login limit reached')
            if pair[1] == ADAPTIVE:
                if not self.state.consume('session:' + token, 6) or not self.state.consume('generation', 30):
                    return await reject(429, 'Classroom generation limit reached')
            # Bound even streamed bodies before JSON decoding; do not trust length.
            body = bytearray()
            while True:
                message = await receive()
                if message['type'] == 'http.disconnect':
                    return
                body.extend(message.get('body', b''))
                if len(body) > 32768:
                    return await reject(413, 'Classroom input exceeds 32 KiB')
                if not message.get('more_body', False):
                    break
            used = False
            async def replay():
                nonlocal used
                if not used:
                    used = True
                    return {'type': 'http.request', 'body': bytes(body), 'more_body': False}
                return await receive()
        else:
            replay = receive
        if pair in PRIVATE and not self.state.authorized(token):
            return await reject(401, 'Classroom session expired')
        scope = {**scope, 'classroom_auth': CLASSROOM_AUTH if authenticated else None,
                 'classroom_session': token, 'headers': [(k, v) for k, v in headers if k.lower() not in
                    (b'x-forwarded-for', b'x-real-ip', b'cf-connecting-ip', b'x-forwarded-host', b'forwarded')]}
        return await self.app(scope, replay, secured)


def create_classroom_app(state):
    if not isinstance(state, DemoState):
        raise ValueError('An explicit classroom configuration is required')
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    router = APIRouter(route_class=PrelessonRoute)

    @router.get('/')
    def index(request: Request):
        if state.authorized(request.cookies.get(COOKIE, '')):
            page = (STATIC / 'index.html').read_text(encoding='utf-8')
            return HTMLResponse(page.replace('<head>', '<head><meta name="coachloop-mode" content="classroom_mock_demo">', 1))
        return FileResponse(STATIC / 'classroom-login.html', media_type='text/html')

    @router.get('/console.js')
    def javascript(request: Request):
        classroom_session(request)
        return FileResponse(STATIC / 'console.js', media_type='text/javascript')

    @router.get('/classroom-login.js')
    def login_js():
        return FileResponse(STATIC / 'classroom-login.js', media_type='text/javascript')

    @router.get('/console.css')
    def stylesheet():
        return FileResponse(STATIC / 'console.css', media_type='text/css')

    @router.get('/health')
    def health():
        return {'status': 'ok', 'mode': 'classroom_mock_demo', 'database': 'not_used'}

    @router.post('/classroom/login')
    def login(payload: LoginRequest):
        token = state.login(payload.code)
        if token is None:
            raise HTTPException(401, 'Classroom login refused')
        response = JSONResponse({'status': 'signed_in', 'data_domain': 'mock'})
        response.set_cookie(COOKIE, token, httponly=True, secure=True, samesite='strict', path='/',
                            max_age=max(0, int(min(3600, state.end-state.clock()))))
        return response

    @router.post('/classroom/logout')
    def logout(request: Request):
        classroom_session(request)
        state.logout(request.scope['classroom_session'])
        response = JSONResponse({'status': 'signed_out'})
        response.delete_cookie(COOKIE, path='/', secure=True, httponly=True, samesite='strict')
        return response

    @router.get(CATALOGUE)
    def themes(request: Request):
        classroom_session(request)
        return {'schema_version': 'theme-catalog-v1.1', 'knowledge_status': 'unverified', 'themes': catalogue()}

    @router.post(ADAPTIVE, response_model=ClassroomResult)
    def draft(payload: ClassroomRequest, request: Request):
        classroom_session(request)
        try:
            result = generate_adaptive(payload.model_dump(exclude={'data_domain', 'is_mock'}))
            content = ClassroomResult(draft=result).model_dump_json()
        except Exception:
            raise HTTPException(503, 'Classroom generation unavailable') from None
        return Response(content, media_type='application/json')

    app.include_router(router)
    app.add_middleware(ClassroomBoundary, state=state)
    return app
