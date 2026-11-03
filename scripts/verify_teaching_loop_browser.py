"""Chromium L05 loop acceptance with explicitly synthetic keypoints, no real video.

Reuses the existing browser runner, local console, geometry, events and review.
No real teacher confirmation or MediaPipe inference is claimed by this fixture.
"""
import argparse
import base64
import json
from pathlib import Path
import subprocess
import sys
import time


def exercise_loop(evaluate,wait_for,command,work,output):
    if output is not None:
        output.mkdir(parents=True,exist_ok=False)
    wait_for("Boolean(document.querySelector('#teaching-loop') && !document.querySelector('#teaching-loop').hidden)")
    evaluate("document.querySelector('[data-stage=video]').click();document.querySelector('#loop-demo-analysis').click();true")
    wait_for("document.querySelector('#video-message').textContent.includes('合成关键点演示已生成')")
    assert evaluate("document.querySelector('#video-quality').textContent.includes('未调用MediaPipe')")
    wait_for("document.querySelectorAll('#video-events select').length===1")
    evaluate("document.querySelector('#video-events select').value='confirmed';document.querySelector('#video-events input').value='合成浏览器观察，非技术错误';document.querySelector('#video-events article button:last-child').click();true")
    wait_for("document.querySelector('#video-message').textContent.includes('操作已追加')")
    evaluate("document.querySelector('#lp-loop').click();true")
    wait_for("document.querySelector('#loop-context').textContent.includes('合成关键点演示')")
    evaluate("(()=>{const f=document.querySelector('#loop-form');f.elements.learner_code.value='ANON-005';f.elements.observation.value='合成验收：可见候选二维角度变化，事件状态仅作本地观察；不能认定技术错误。';f.elements.practice_task.value='合成复练任务：先复核拍摄条件与L05教材定位，专项与现场安全未确认前不安排冰上实操。';f.dispatchEvent(new Event('input',{bubbles:true}));f.requestSubmit();return true;})()")
    wait_for("document.querySelector('#loop-message').textContent.includes('闭环版本1')")
    assert evaluate("document.querySelector('#loop-review-label').textContent.includes('反馈草稿')")
    evaluate("document.querySelector('#loop-confirm').click();true")
    wait_for("document.querySelector('#loop-message').textContent.includes('显式勾选')")
    evaluate("document.querySelector('#loop-ack').checked=true;document.querySelector('#loop-confirm').click();true")
    wait_for("document.querySelector('#loop-message').textContent.includes('闭环版本2')")
    assert evaluate("document.querySelector('#loop-review-label').textContent.includes('身份未认证')")

    def download(name):
        directory=work/name;directory.mkdir()
        command('Browser.setDownloadBehavior',{'behavior':'allow','downloadPath':str(directory)})
        evaluate("document.querySelector('#loop-export').click();true")
        for _ in range(100):
            files=list(directory.glob('*.json'))
            if files:break
            time.sleep(.1)
        assert files,'Actual loop download missing'
        result=json.loads(files[0].read_text())
        assert result['is_mock'] and result['data_origin']=='synthetic_keypoints_demo'
        assert result['technical_error_assessment']=='not_assessed' and not result['authenticated_teacher']
        assert result['specialist_review_status']=='pending' and result['plan']['formal_teaching_evidence']==[]
        assert result['learner_code']=='ANON-005' and 'keypoints' not in result
        if output is not None:(output/(name+'.json')).write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
        return result

    confirmed=download('L05-loop-confirmed-local.SYNTHETIC')
    assert confirmed['confirmation_current'] and len(confirmed['history'])==2
    evaluate("document.querySelector('#loop-form').elements.observation.value='合成验收追加观察：仍需专项确认与拍摄质量复核。';document.querySelector('#loop-form').dispatchEvent(new Event('input',{bubbles:true}));document.querySelector('#loop-export').click();true")
    wait_for("document.querySelector('#loop-message').textContent.includes('未保存修改')")
    evaluate("document.querySelector('#loop-save').click();true")
    wait_for("document.querySelector('#loop-message').textContent.includes('闭环版本3')")
    assert evaluate("document.querySelector('#loop-review-label').textContent.includes('反馈草稿')")
    evaluate("document.querySelector('#loop-ack').checked=true;document.querySelector('#loop-confirm').click();true")
    wait_for("document.querySelector('#loop-message').textContent.includes('闭环版本4')")
    evaluate("document.querySelector('[data-stage=video]').click();document.querySelector('#video-events select').value='uncertain';document.querySelector('#video-events input').value='合成验收：后续证据不足，需重新复核';document.querySelector('#video-events article button:last-child').click();true")
    wait_for("document.querySelector('#video-events article p').textContent.includes('当前：证据不足')")
    assert evaluate("document.querySelector('#loop-report').hidden")
    evaluate("document.querySelector('[data-stage=feedback]').click();document.querySelector('#loop-refresh').click();true")
    wait_for("document.querySelector('#loop-message').textContent.includes('反馈草稿')")
    stale=download('L05-loop-demo.SYNTHETIC')
    assert not stale['confirmation_current'] and stale['evidence_changed'] and len(stale['history'])==4
    assert stale['analysis']['candidate_changes'][0]['status']=='uncertain'
    assert stale['saved_analysis']['candidate_changes'][0]['status']=='confirmed'
    # Rechecking changed evidence must not trap or discard an unsaved teacher note.
    evaluate("document.querySelector('#loop-form').elements.observation.value='SYNTHETIC_UNSAVED_NOTE';document.querySelector('#loop-form').dispatchEvent(new Event('input',{bubbles:true}));document.querySelector('#loop-refresh').click();true")
    wait_for("document.querySelector('#loop-message').textContent.includes('保留未保存文字')")
    assert evaluate("document.querySelector('#loop-form').elements.observation.value==='SYNTHETIC_UNSAVED_NOTE'")
    evaluate("document.querySelector('#loop-export').click();true")
    wait_for("document.querySelector('#loop-message').textContent.includes('未保存修改')")
    # Same-session restore after a full browser refresh, without leaking to KB.
    evaluate("location.reload();true")
    wait_for("Boolean(document.querySelector('#loop-list') && !document.querySelector('#teaching-loop').hidden)")
    evaluate("document.querySelector('#teaching-loop').open=true;document.querySelector('#loop-list').click();true")
    wait_for("document.querySelector('#loop-records').options.length===1")
    evaluate("document.querySelector('#loop-open').click();true")
    wait_for("!document.querySelector('#loop-report').hidden")
    assert evaluate("document.querySelector('#loop-report-text').textContent.includes('ANON-005')")
    if output is not None:
        evaluate("document.querySelector('#loop-report').scrollIntoView();true")
        shot=command('Page.captureScreenshot',{'format':'png','captureBeyondViewport':False})
        (output/'L05-loop.SYNTHETIC.png').write_bytes(base64.b64decode(shot['result']['data']))
    # Reload clears the old runner's plan DOM; restore it to its normal scenario.
    evaluate("document.querySelector('#lesson-planning-mode').open=true;true")
    wait_for("document.querySelector('#lp-lesson').options.length===8")
    evaluate("(()=>{const f=document.querySelector('#lp-form');f.elements.venue_conditions.value='合成恢复场地';f.elements.equipment_conditions.value='合成恢复装备';f.elements.safe_waiting_area.checked=true;f.requestSubmit();return true;})()")
    wait_for("!document.querySelector('#lp-output').hidden")
    print('L05 loop Chromium PASS: synthetic geometry/events, review, L05 link, anonymous ID, draft/explicit local confirmation, edits, stale confirmation, actual JSON downloads, refresh restore')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir',type=Path,default=None,help='Optional NEW directory for synthetic JSON/screenshot')
    args=parser.parse_args()
    cmd=[sys.executable,str(Path(__file__).with_name('verify_l05_application_browser.py')),'--teaching-loop']
    if args.output_dir is not None:cmd+=['--loop-output-dir',str(args.output_dir)]
    raise SystemExit(subprocess.call(cmd))
