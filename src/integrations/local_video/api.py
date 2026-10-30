"""Loopback console routes only. Never mount in classroom or production main."""
import asyncio
import os
import re
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Request, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator
from starlette.responses import StreamingResponse, Response
from starlette.background import BackgroundTask
from integrations.prelesson.api import PrelessonRoute
from integrations.prelesson.adaptive_api import LOCAL_AUTH
from .service import BASE, COOKIE, VideoError, feedback, MAX_BYTES


class Input(BaseModel):
    model_config=ConfigDict(extra='forbid')


class Create(Input):
    side: Literal['left','right']
    authorized_use: Literal[True]
    privacy_acknowledged: Literal[True]
    single_subject_side_view: Literal[True]

    @field_validator('authorized_use','privacy_acknowledged','single_subject_side_view',mode='before')
    @classmethod
    def exact_ack(cls,value):
        if value is not True:raise ValueError('Explicit local use acknowledgement required')
        return value


class Key(Input):
    job_id: UUID


class Review(Key):
    event_id: str=Field(pattern=r'^evt_[0-9a-f]{12}$')
    status: Literal['pending','confirmed','normal_movement','tracking_error','uncertain']
    note: str=Field(default='',max_length=500)
    expected_sequence: int=Field(strict=True,ge=0,le=256)
    request_id: UUID

    @field_validator('note')
    @classmethod
    def plain(cls,value):
        if any(ord(c)<32 or ord(c)==127 for c in value):raise ValueError('Single-line note required')
        return value.strip()


def owner(request: Request):
    if request.scope.get('coachloop_local_auth') is not LOCAL_AUTH:
        raise HTTPException(401,'Local video session required')
    return request.app.state.video_store.authorized(request.cookies.get(COOKIE,''))


def create_router():
    router=APIRouter(route_class=PrelessonRoute,dependencies=[Depends(owner)])
    raw=APIRouter(dependencies=[Depends(owner)])

    @router.get(BASE+'/capabilities')
    def capabilities(request: Request):return request.app.state.video_store.capabilities()

    @router.post(BASE+'/jobs')
    def create(payload: Create,request: Request,token: str=Depends(owner)):
        key=request.app.state.video_store.create(token,payload.side)
        return {'job_id':key,'state':'created','authenticated_coach':False}

    @raw.post(BASE+'/upload')
    async def upload(request: Request,job_id: UUID,format: Literal['mp4','mov'],token: str=Depends(owner)):
        store=request.app.state.video_store
        path=store.upload_path(token,job_id.hex)
        count=0
        try:
            # The filename is fixed and server-owned; ignore the user's filename.
            import os
            with os.fdopen(os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600),'wb') as file:
                async with asyncio.timeout(120):
                    async for chunk in request.stream():
                        store.authorized(token)
                        with store.lock:
                            if store.get(token,job_id.hex).state!='uploading':raise VideoError(409,'video_upload_state')
                        count+=len(chunk)
                        if count>MAX_BYTES:raise VideoError(413,'video_size_limit')
                        file.write(chunk)
            with path.open('rb') as file:prefix=file.read(12)
            if count<12 or prefix[4:8]!=b'ftyp':raise VideoError(422,'unsupported_container')
            store.submit(token,job_id.hex)
            return {'job_id':job_id.hex,'state':'queued','uploaded_bytes':count}
        except TimeoutError:
            store.upload_failed(token,job_id.hex,'upload_timeout')
            raise VideoError(408,'upload_timeout') from None
        except VideoError as error:
            store.upload_failed(token,job_id.hex,error.code);raise
        except Exception:
            store.upload_failed(token,job_id.hex,'upload_interrupted')
            raise VideoError(400,'upload_interrupted') from None

    @router.get(BASE+'/current')
    def current(request: Request,token: str=Depends(owner)):
        return request.app.state.video_store.current(token)

    @router.get(BASE+'/status')
    def status(request: Request,job_id: UUID,token: str=Depends(owner)):
        return request.app.state.video_store.status(token,job_id.hex)

    @router.get(BASE+'/result')
    def result(request: Request,job_id: UUID,token: str=Depends(owner)):
        return request.app.state.video_store.result(token,job_id.hex)

    @router.get(BASE+'/media')
    def media(request: Request,job_id: UUID,token: str=Depends(owner)):
        file=request.app.state.video_store.media(token,job_id.hex)
        size=os.fstat(file.fileno()).st_size
        start,end=0,size-1
        supplied=request.headers.get('range')
        if supplied:
            match=re.fullmatch(r'bytes=([0-9]{0,20})-([0-9]{0,20})',supplied)
            if not match or not any(match.groups()):
                file.close();return Response(status_code=416,headers={'Content-Range':f'bytes */{size}'})
            first,last=match.groups()
            if first:start=int(first);end=min(int(last),size-1) if last else size-1
            else:start=max(0,size-int(last))
            if start>end or start>=size:
                file.close();return Response(status_code=416,headers={'Content-Range':f'bytes */{size}'})
        count=end-start+1
        def chunks():
            try:
                file.seek(start);remaining=count
                while remaining:
                    data=file.read(min(65536,remaining))
                    if not data:break
                    remaining-=len(data);yield data
            finally:file.close()
        headers={'Accept-Ranges':'bytes','Content-Length':str(count),
                 'Content-Disposition':'inline; filename="local-analysis-preview.mp4"'}
        if supplied:headers['Content-Range']=f'bytes {start}-{end}/{size}'
        return StreamingResponse(chunks(),status_code=206 if supplied else 200,
            media_type='video/mp4',headers=headers,background=BackgroundTask(file.close))

    @router.post(BASE+'/review')
    def review(payload: Review,request: Request,token: str=Depends(owner)):
        return request.app.state.video_store.review(token,payload.job_id.hex,payload.event_id,
            payload.status,payload.note,payload.expected_sequence,payload.request_id.hex)

    @router.get(BASE+'/feedback')
    def report(request: Request,job_id: UUID,token: str=Depends(owner)):
        return feedback(request.app.state.video_store.result(token,job_id.hex),job_id.hex)

    @router.post(BASE+'/delete')
    def delete(payload: Key,request: Request,token: str=Depends(owner)):
        request.app.state.video_store.delete(token,payload.job_id.hex)
        return {'state':'deleted'}

    return [router,raw]
