"""Standalone application factory. No server start, database initialization or main.py import."""
from uuid import UUID
from typing import Annotated

from fastapi import APIRouter,Depends,FastAPI,Header,HTTPException,Query,Request
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from starlette.responses import JSONResponse,Response

from .json_codec import encode,decode
from .schemas import ImportRequest,ImportResponse,ResultPage
from .service import TrustedIdentity,checked_connection,query_results,import_results


class ExactJSONRoute(APIRoute):
    def get_route_handler(self):
        handler=super().get_route_handler()
        async def exact(request):
            async def parsed():
                if not hasattr(request,'_json'):
                    try: request._json=decode(await request.body())
                    except (ValueError,UnicodeError,RecursionError): raise HTTPException(422,'Valid finite-number JSON required') from None
                return request._json
            request.json=parsed
            return await handler(request)
        return exact


class BodyLimit:
    """Buffer at most 1 MiB, including requests with no/false Content-Length."""
    def __init__(self,app): self.app=app
    async def __call__(self,scope,receive,send):
        if scope['type']!='http' or scope.get('method')!='POST':
            return await self.app(scope,receive,send)
        data=bytearray()
        while True:
            message=await receive()
            if message['type']=='http.disconnect': return
            data.extend(message.get('body',b''))
            if len(data)>1024*1024:
                return await JSONResponse({'detail':'Request body exceeds 1 MiB'},status_code=413)(scope,receive,send)
            if not message.get('more_body',False): break
        consumed=False
        async def replay():
            nonlocal consumed
            if not consumed:
                consumed=True;return {'type':'http.request','body':bytes(data),'more_body':False}
            return await receive()
        return await self.app(scope,replay,send)


def identity(request: Request) -> TrustedIdentity:
    provider=request.app.state.identity_provider
    if provider is None: raise HTTPException(401,'Trusted authentication provider not configured')
    value=provider(request)
    if not isinstance(value,TrustedIdentity): raise HTTPException(401,'Trusted identity required')
    return value


def exact_response(value):
    return Response(content=encode(value),media_type='application/json',headers={'Cache-Control':'no-store'})


def create_app(identity_provider=None):
    """A server-side authentication adapter supplies identity; default is closed.

    No header, body field, query parameter or upstream reviewer name is treated as
    identity. This factory deliberately contains no Coze token verification stub.
    """
    app=FastAPI(title='CoachLoop reviewed training handoff',version='0.1.0')
    app.state.identity_provider=identity_provider
    app.add_middleware(BodyLimit)

    @app.exception_handler(RequestValidationError)
    async def invalid(_request,error):
        # Do not echo untrusted notes, identifiers or input bodies in errors.
        details=[]
        for item in error.errors():
            location=list(item['loc'])
            if item['type']=='extra_forbidden' and location: location[-1]='unknown_field'
            details.append({'loc':location,'type':item['type'],'msg':'Request does not match schema'})
        return JSONResponse({'detail':details},status_code=422,headers={'Cache-Control':'no-store'})

    router=APIRouter(route_class=ExactJSONRoute)

    @router.post('/api/v1/reviewed-training-results/import',response_model=ImportResponse)
    def import_result(payload: ImportRequest,
                      idempotency_key: Annotated[UUID,Header(alias='Idempotency-Key')],
                      caller: TrustedIdentity=Depends(identity)):
        result=ImportResponse.model_validate(import_results(caller,payload,idempotency_key))
        return exact_response(result.model_dump(mode='python'))

    @router.get('/api/v1/training-sessions/{training_session_id}/reviewed-training-results',response_model=ResultPage)
    def read_result(training_session_id: UUID,analysis_run_id: UUID,
                    limit: int=Query(default=50,ge=1,le=100),cursor: UUID | None=None,
                    caller: TrustedIdentity=Depends(identity)):
        from sqlalchemy.exc import DBAPIError
        try:
            with caller.engine.begin() as connection:
                checked_connection(connection,caller)
                result=ResultPage.model_validate(query_results(connection,caller,training_session_id,analysis_run_id,limit,cursor))
                return exact_response(result.model_dump(mode='python'))
        except DBAPIError:
            raise HTTPException(503,'Training result storage unavailable') from None

    app.include_router(router)
    return app
