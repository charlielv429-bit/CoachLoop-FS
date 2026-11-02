"""Only mounted by the loopback console, never production or classroom."""
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from integrations.prelesson.adaptive_api import local_session
from integrations.prelesson.api import PrelessonRoute
from .planning import LessonRequest, EditRequest
from .registry import Archive, Knowledge, RegistryError, CATEGORIES

BASE = '/api/v3'
READ_PATHS = {BASE + path for path in ('/lessons', '/knowledge', '/history', '/export', '/plans/export', '/plans/history')}
WRITE_PATHS = {BASE + path for path in ('/knowledge', '/import', '/plans/draft', '/plans/edit')}


def plan_owner(request: Request):
    owner = request.scope.get('coachloop_plan_owner')
    if not isinstance(owner, str) or len(owner) != 64:
        raise HTTPException(401, 'Local plan session required')
    return owner


def create_router(store, plans):
    router = APIRouter(route_class=PrelessonRoute, dependencies=[Depends(local_session)])

    @router.get(BASE + '/lessons')
    def lessons(lesson_id: str | None = Query(None, pattern=r'^L0[1-8]$')):
        return {'lessons': store.lessons(lesson_id), 'categories': CATEGORIES,
                'storage': '进程内存；所有本机控制台会话共享；重启或退出清空，请导出备份。'}

    @router.get(BASE + '/knowledge')
    def search(category: str | None = Query(None, pattern=r'^KB-[SPAE]$'),
               lesson_id: str | None = Query(None, pattern=r'^L0[1-8]$'),
               keyword: str = Query('', max_length=200)):
        return {'entries': store.search(category, lesson_id, keyword)}

    @router.get(BASE + '/history')
    def history(knowledge_id: str = Query(pattern=r'^[A-Za-z0-9_-]{1,64}$')):
        return {'entries': store.history(knowledge_id)}

    @router.get(BASE + '/export')
    def export():
        return store.export()

    @router.post(BASE + '/knowledge')
    def save(entry: Knowledge):
        try:
            return store.save(entry)
        except RegistryError as error:
            raise HTTPException(409, str(error)) from error

    @router.post(BASE + '/import')
    def import_archive(archive: Archive):
        try:
            return store.import_archive(archive)
        except RegistryError as error:
            raise HTTPException(409, str(error)) from error

    @router.post(BASE + '/plans/draft')
    def draft(request: LessonRequest, owner: str = Depends(plan_owner)):
        try:
            return plans.create(request, store, owner=owner)
        except RegistryError as error:
            raise HTTPException(409, str(error)) from error

    @router.post(BASE + '/plans/edit')
    def edit(request: EditRequest, owner: str = Depends(plan_owner)):
        try:
            return plans.edit(request, owner=owner)
        except RegistryError as error:
            raise HTTPException(409, str(error)) from error

    @router.get(BASE + '/plans/export')
    def export_plan(plan_id: str = Query(pattern=r'^[a-f0-9]{32}$'), owner: str = Depends(plan_owner)):
        try:
            return plans.read(plan_id, owner=owner)
        except RegistryError as error:
            raise HTTPException(404, str(error)) from error

    @router.get(BASE + '/plans/history')
    def plan_history(plan_id: str = Query(pattern=r'^[a-f0-9]{32}$'), owner: str = Depends(plan_owner)):
        try:
            return {'versions': plans.read(plan_id, history=True, owner=owner)}
        except RegistryError as error:
            raise HTTPException(404, str(error)) from error

    return router
