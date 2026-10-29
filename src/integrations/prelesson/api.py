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


def create_app(access_token: str | None=None):
    """Token is server config, never a teacher role/approval supplied in the body.

    Default closed without COACHLOOP_PRELESSON_TOKEN. This service credential
    authorizes generation only; it does not attest a teacher's review identity.
    """
    token=access_token if access_token is not None else os.environ.get('COACHLOOP_PRELESSON_TOKEN')
    app=FastAPI(title='CoachLoop pre-class draft workflow',version='0.1.0')
    app.add_middleware(BodyLimit)
    bearer=HTTPBearer(auto_error=False)

    def caller(credentials: Annotated[HTTPAuthorizationCredentials | None,Depends(bearer)]):
        if not token:raise HTTPException(503,'Draft workflow credential not configured')
        if credentials is None:raise HTTPException(401,'Bearer credential required')
        if not hmac.compare_digest(credentials.credentials.encode(),token.encode()):
            raise HTTPException(403,'Invalid workflow credential')

    @app.exception_handler(RequestValidationError)
    async def invalid(_request,error):
        # Never echo free-text classroom conditions or unknown input keys.
        return JSONResponse({'detail':[{'loc':list(e['loc'][:-1])+['unknown_field'] if e['type']=='extra_forbidden' else list(e['loc']),
            'type':e['type'],'msg':'Request does not match prelesson schema'} for e in error.errors()]},
            status_code=422,headers={'Cache-Control':'no-store'})

    router=APIRouter(route_class=ExactJSONRoute)

    @router.post('/api/v1/lesson-plans/draft',response_model=DraftResponse,dependencies=[Depends(caller)],
                 responses={code:{'model':ErrorResponse} for code in (401,403,413,422,503)})
    def draft(payload: DraftRequest):
        result=run_prelesson(payload.model_dump())
        return Response(content=result.model_dump_json(),media_type='application/json',headers={'Cache-Control':'no-store'})

    app.include_router(router)
    return app
