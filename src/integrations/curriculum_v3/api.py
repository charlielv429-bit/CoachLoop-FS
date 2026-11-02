"""Only mounted by the loopback console, never production or classroom."""
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from integrations.prelesson.adaptive_api import local_session
from integrations.prelesson.api import PrelessonRoute
from .review import EvidenceReport
from .planning import LessonRequest, EditRequest, guard_current_evidence
from .persistence import review_materials
from .registry import Archive, Knowledge, RegistryError, CATEGORIES

BASE = '/api/v3'
READ_PATHS = {BASE + path for path in ('/lessons', '/knowledge', '/history', '/export', '/plans/export', '/plans/history', '/review-materials', '/evidence')}
WRITE_PATHS = {BASE + path for path in ('/knowledge', '/import', '/plans/draft', '/plans/edit', '/evidence')}


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
                'storage': store.storage_description}

    @router.get(BASE + '/review-materials')
    def offline_review():
        return review_materials(store)

    @router.get(BASE + '/evidence')
    def reports(knowledge_id: str | None = Query(None,pattern=r'^[A-Za-z0-9_-]{1,64}$')):
        return {'reports':store.evidence_reports(knowledge_id),'warning':'材料声明不是系统可信审核'}

    @router.post(BASE + '/evidence')
    def register_report(report: EvidenceReport):
        if not hasattr(store,'save_report'):raise HTTPException(409,'Persistent evidence storage required')
        try:return store.save_report(report)
        except RegistryError as error:raise HTTPException(409,str(error)) from error

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
            return guard_current_evidence(plans.create(request, store, owner=owner),store)
        except RegistryError as error:
            raise HTTPException(409, str(error)) from error

    @router.post(BASE + '/plans/edit')
    def edit(request: EditRequest, owner: str = Depends(plan_owner)):
        try:
            return guard_current_evidence(plans.edit(request, owner=owner),store)
        except RegistryError as error:
            raise HTTPException(409, str(error)) from error

    @router.get(BASE + '/plans/export')
    def export_plan(plan_id: str = Query(pattern=r'^[a-f0-9]{32}$'), owner: str = Depends(plan_owner)):
        try:
            return guard_current_evidence(plans.read(plan_id, owner=owner),store)
        except RegistryError as error:
            raise HTTPException(404, str(error)) from error

    @router.get(BASE + '/plans/history')
    def plan_history(plan_id: str = Query(pattern=r'^[a-f0-9]{32}$'), owner: str = Depends(plan_owner)):
        try:
            return {'versions': [guard_current_evidence(plan,store) for plan in plans.read(plan_id, history=True, owner=owner)]}
        except RegistryError as error:
            raise HTTPException(404, str(error)) from error

    return router
