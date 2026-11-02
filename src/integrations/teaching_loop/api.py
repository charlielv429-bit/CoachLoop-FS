"""Only mounted in the existing local console. No caller supplied identity/status."""
from pydantic import field_validator
from fastapi import APIRouter, Depends, HTTPException, Query
from typing import Literal
from integrations.prelesson.api import PrelessonRoute
from integrations.curriculum_v3.api import plan_owner
from integrations.curriculum_v3.registry import Strict, RegistryError
from integrations.local_video.api import owner as video_owner
from .service import BASE, ID, Link, Edit, Confirm, Key
from .synthetic import install_demo


class Demo(Strict):
    synthetic_demo: Literal[True]

    @field_validator("synthetic_demo",mode="before")
    @classmethod
    def exact(cls,value):
        if value is not True:raise ValueError("Explicit synthetic demo acknowledgement required")
        return value


def create_router(store):
    router = APIRouter(route_class=PrelessonRoute)

    def run(action):
        try:return action()
        except RegistryError as error:raise HTTPException(409,str(error)) from error

    @router.post(BASE+'/demo-analysis')
    def demo(body: Demo,owner: str=Depends(plan_owner),token: str=Depends(video_owner)):
        return install_demo(store.videos,token)

    @router.post(BASE+'/link')
    def link(body: Link,owner: str=Depends(plan_owner),token: str=Depends(video_owner)):
        return run(lambda:store.link(body,owner,token))

    @router.post(BASE+'/edit')
    def edit(body: Edit,owner: str=Depends(plan_owner),token: str=Depends(video_owner)):
        return run(lambda:store.change(body,owner,token))

    @router.post(BASE+'/confirm')
    def confirm(body: Confirm,owner: str=Depends(plan_owner),token: str=Depends(video_owner)):
        return run(lambda:store.change(body,owner,token,confirm=True))

    @router.get(BASE+'/export')
    def export(loop_id: str=Query(pattern=ID),owner: str=Depends(plan_owner),token: str=Depends(video_owner)):
        return run(lambda:store.read(loop_id,owner,token))

    @router.get(BASE+'/history')
    def history(loop_id: str=Query(pattern=ID),owner: str=Depends(plan_owner),token: str=Depends(video_owner)):
        return run(lambda:store.read(loop_id,owner,token))

    @router.get(BASE+'/current')
    def current(owner: str=Depends(plan_owner),token: str=Depends(video_owner)):
        return run(lambda:store.current(owner,token))

    @router.post(BASE+'/delete')
    def delete(body: Key,owner: str=Depends(plan_owner),token: str=Depends(video_owner)):
        return run(lambda:store.delete(body.loop_id,owner,token))

    return router
