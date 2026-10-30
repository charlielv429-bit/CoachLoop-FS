"""Local-console-only V1.1 extension; no change to deployed V1 routes."""
from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException, Request, Security
from fastapi.security import APIKeyCookie
from starlette.responses import Response
from agents.lesson_plan_agent.adaptive import AdaptiveRequest, AdaptiveResponse, generate_adaptive, catalogue
from .api import PrelessonRoute
from .schemas import ErrorResponse

ADAPTIVE = '/api/v1/lesson-plans/adaptive-draft'
CATALOGUE = '/api/v1/lesson-plans/themes'
LOCAL_AUTH = object()

def local_session(request: Request, cookie: Annotated[str | None, Security(APIKeyCookie(
        name="coachloop_local_console", scheme_name="LocalConsoleSession", auto_error=False))]):
    if request.scope.get('coachloop_local_auth') is not LOCAL_AUTH:
        raise HTTPException(401, 'Local console session required')


def create_adaptive_router():
    # LocalBoundary enforces cookie + exact Origin + CSRF before dispatch.
    # This router MUST NOT be attached to production main or an unguarded app.
    router = APIRouter(route_class=PrelessonRoute)

    @router.get(CATALOGUE)
    def themes():
        return {'schema_version': 'theme-catalog-v1.1', 'knowledge_status': 'unverified', 'themes': catalogue()}

    @router.post(ADAPTIVE, response_model=AdaptiveResponse,
                 openapi_extra={'parameters': [
                     {'name': 'Origin', 'in': 'header', 'required': True, 'schema': {'type': 'string'}, 'description': 'Exact http://127.0.0.1:<port> origin required by LocalBoundary'},
                     {'name': 'X-CoachLoop-Console', 'in': 'header', 'required': True, 'schema': {'type': 'string', 'const': '1'}}]},
                 dependencies=[Depends(local_session)],
                 responses={code: {'model': ErrorResponse} for code in (401, 403, 413, 422)})
    def draft(payload: AdaptiveRequest):
        result = generate_adaptive(payload.model_dump())
        return Response(result.model_dump_json(), media_type='application/json')

    return router
