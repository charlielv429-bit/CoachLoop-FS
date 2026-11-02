"""Course pack is a view of actual pending APIs, never an approval or LMS upload."""
import hashlib
import importlib.util
import json
from pathlib import Path
import xml.etree.ElementTree as ET
from zipfile import ZipFile

import pytest
from integrations.curriculum_v3.registry import LESSONS

ROOT=Path(__file__).resolve().parents[1]
PACK=ROOT/'docs/course-mvp'
spec=importlib.util.spec_from_file_location('prepare_course_mvp',ROOT/'scripts/prepare_course_mvp.py')
course=importlib.util.module_from_spec(spec)
spec.loader.exec_module(course)


@pytest.fixture(scope='module')
def actual():
    return course.collect()


@pytest.mark.parametrize('lesson_id',[f'L0{i}' for i in range(1,9)])
def test_each_course_deliverable_matches_current_local_api(actual,lesson_id):
    summaries,exports=actual
    item=next(i for i in summaries if i['lesson']['lesson_id']==lesson_id)
    committed=json.loads((PACK/'course-inventory.json').read_text())
    saved=next(i for i in committed['lessons'] if i['lesson']['lesson_id']==lesson_id)
    assert saved==item
    assert (PACK/f'{lesson_id}-draft.md').read_text()==course.render_lesson(item)
    plan=exports[lesson_id]
    assert plan['lesson']['title']==next(l['title'] for l in LESSONS if l['lesson_id']==lesson_id)
    assert sum(p['minutes'] for p in plan['teaching_flow']['phases'])==45
    assert plan['version']==2 and len(plan['teacher_edits'])==2
    assert plan['review_status']=='pending_review' and plan['organization']['status']=='withheld'
    assert plan['technical_guidance']==plan['formal_teaching_evidence']==[]
    assert all(r['source_verification_status']==r['specialist_review_status']=='pending' for r in item['references'])
    assert all(r['source_id'] and r['source_locator'] and len(r['knowledge_digest'])==64 for r in item['references'])
    assert saved['feedback_status']=='not_received'


def test_source_provenance_and_platform_inventory_are_honest(actual):
    manifest=json.loads((PACK/'course-inventory.json').read_text())
    assert manifest['synthetic_conditions'] and not manifest['teacher_feedback_received'] and not manifest['platform_uploaded']
    for path,digest in manifest['source_packet_sha256'].items():
        assert hashlib.sha256((ROOT/path).read_bytes()).hexdigest()==digest
    catalog=json.loads((PACK/'resource-catalog.json').read_text())
    assert not catalog['platform_uploaded'] and not catalog['textbook_scans']['public_in_package']
    assert [r['lesson_id'] for r in catalog['resources']]==[l['lesson_id'] for l in LESSONS]
    for row in catalog['resources']:
        assert (PACK/row['draft_file']).is_file() and (PACK/row['teacher_feedback_file']).is_file()
        assert row['specialist_review_status']=='pending' and row['teacher_feedback_status']=='not_received'
        assert row['platform_upload_status']=='not_started'
        assert row['licensed_demo_video_status']==row['slides_status']==row['approved_observation_rubric_status']=='missing'
    l05=actual[1]['L05']
    assert l05['current_teacher_edits']['evaluation_observations'].startswith('教师评价与反馈待填写')
    assert l05['l05_teaching_design']['areas']['evaluation_observations']['review_status']=='pending_review'


def test_word_is_editable_review_text_without_scans_or_external_relationships():
    with ZipFile(PACK/'L05-teacher-review.docx') as archive:
        assert not any(n.startswith(('word/media/','word/embeddings/')) for n in archive.namelist())
        xml=ET.fromstring(archive.read('word/document.xml'))
        ns={'w':'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
        text=''.join(n.text or '' for n in xml.findall('.//w:t',ns))
        assert len(xml.findall('.//w:tbl',ns))==3
        for key in ('K010','K011','K012','K018','K019','pending','________'):
            assert key in text
        assert len(xml.findall('.//w:p',ns))>50
        entries=json.loads((ROOT/'docs/p32-input/p32-knowledge-import.json').read_text())['entries']+json.loads((ROOT/'docs/p34/knowledge-revisions.json').read_text())['entries']
        current={e['knowledge_id']:e for e in entries}
        for kid in ('K010','K011','K012','K018','K019'):
            assert current[kid]['content'] in text
            assert course.knowledge_digest(current[kid]) in text
        # No external links, hidden remote content, macros or fake signature payloads.
        for name in archive.namelist():
            if name.endswith('.rels'):
                root=ET.fromstring(archive.read(name))
                assert all(r.get('TargetMode')!='External' for r in root)
        assert not any('vbaProject' in n or 'signature' in n.lower() for n in archive.namelist())
