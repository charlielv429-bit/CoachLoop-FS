"""Standalone local HTTP factory; no existing service/DB initialization."""
import hmac
import os
from typing import Annotated

from fastapi import APIRouter,Depends,FastAPI,HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.security import HTTPAuthorizationCredentials,HTTPBearer
from starlette.responses import JSONResponse,Response

from graphs.prelesson_graph import run_prelesson
from integrations.reviewed_training.api import BodyLimit,ExactJSONRoute
from .schemas import DraftRequest,DraftResponse,ErrorResponse


class PrelessonRoute(ExactJSONRoute):
    """Keep size limits and sanitized validation errors local to these routes."""
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self.app=BodyLimit(self.app)

    def get_route_handler(self):
        handler=super().get_route_handler()
        async def guarded(request):
            try:return await handler(request)
            except RequestValidationError as error:
                return JSONResponse({'detail':[{
                    'loc':list(e['loc'][:-1])+['unknown_field'] if e['type']=='extra_forbidden' else list(e['loc']),
                    'type':e['type'],'msg':'Request does not match prelesson schema'} for e in error.errors()]},
                    status_code=422,headers={'Cache-Control':'no-store'})
        return guarded


def create_router(access_token: str | None=None,*,include_alias: bool=False):
    """Token is server config, never a teacher role/approval supplied in the body.

    Default closed without COACHLOOP_PRELESSON_TOKEN. This service credential
    authorizes generation only; it does not attest a teacher's review identity.
    """
    token=access_token if access_token is not None else os.environ.get('COACHLOOP_PRELESSON_TOKEN')
    bearer=HTTPBearer(auto_error=False)

    def caller(credentials: Annotated[HTTPAuthorizationCredentials | None,Depends(bearer)]):
        if not token:raise HTTPException(503,'Draft workflow credential not configured')
        if credentials is None:raise HTTPException(401,'Bearer credential required')
        if not hmac.compare_digest(credentials.credentials.encode(),token.encode()):
            raise HTTPException(403,'Invalid workflow credential')

    router=APIRouter(route_class=PrelessonRoute)

    @router.post('/api/v1/lesson-plans/draft',response_model=DraftResponse,dependencies=[Depends(caller)],
                 responses={code:{'model':ErrorResponse} for code in (401,403,413,422,503)})
    def draft(payload: DraftRequest):
        result=run_prelesson(payload.model_dump())
        return Response(content=result.model_dump_json(),media_type='application/json',headers={'Cache-Control':'no-store'})

    if include_alias:
        router.add_api_route('/prelesson/draft',draft,methods=['POST'],response_model=DraftResponse,
            dependencies=[Depends(caller)],responses={code:{'model':ErrorResponse} for code in (401,403,413,422,503)})
    return router


def create_app(access_token: str | None=None):
    """Retain the standalone factory and its existing public contract."""
    app=FastAPI(title='CoachLoop pre-class draft workflow',version='0.1.0')
    app.include_router(create_router(access_token))
    return app
