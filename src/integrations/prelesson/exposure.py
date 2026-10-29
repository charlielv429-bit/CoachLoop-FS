"""Opt-in public surface for the prelesson-only deployment profile."""
import os
from starlette.responses import JSONResponse


def prelesson_only_enabled():
    value=os.environ.get('COACHLOOP_PRELESSON_ONLY','0')
    if value not in ('0','1'):
        raise RuntimeError('COACHLOOP_PRELESSON_ONLY must be 0 or 1')
    return value=='1'


class PrelessonExposureGuard:
    """Deny all other paths/methods before legacy handlers can run.

    This is a route boundary, not teacher identity or upstream gateway proof.
    Main uses the same frozen profile to skip its legacy database lifespan.
    """
    ALLOWED={('GET','/health'),('POST','/api/v1/lesson-plans/draft'),('POST','/prelesson/draft')}

    def __init__(self,app,enabled=False):self.app,self.enabled=app,enabled

    async def __call__(self,scope,receive,send):
        if self.enabled and scope['type']=='websocket':
            return await send({'type':'websocket.close','code':1008})
        if (self.enabled and scope['type']=='http'
                and (scope['method'],scope['path']) not in self.ALLOWED):
            return await JSONResponse({'detail':'Route not exposed in prelesson-only profile'},
                status_code=404,headers={'Cache-Control':'no-store'})(scope,receive,send)
        return await self.app(scope,receive,send)
