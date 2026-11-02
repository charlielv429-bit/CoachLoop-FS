# P3.4 修订包使用与验收

## 数据与生命周期

知识库沿用.local/coachloop-kb/knowledge.sqlite3：目录0700、数据库0600，本地授权控制台共享，重启保留。
不存学生资料或私有教案。扫描原件与渲染图只在ignored work/p34；不随Git交付。原件需由资料持有人离线妥善保管，
仅凭公开哈希无法重建原页。删除本地扫描可删除work/p34/originals和work/p34/render，不会删除知识历史。

教师教案仍为浏览器会话隔离的进程内存版本，退出清空；教师须自行保存JSON。
本阶段不新增存储、认证或AI功能，不修改视频、生产数据库或mock隔离。

## 先备份，再增量导入

停止本地控制台，避免其他编辑并发。下列文件名须未存在，备份命令拒绝覆盖。
有受控审核历史的其他实例必须显式提供其原有私钥；本次真实库无审核决定，不生成私钥。

```sh
PYTHONPATH=src .venv/bin/python -B scripts/manage_local_knowledge.py full-backup --file .local/backups/p34-before.kb-full-backup.json
PYTHONPATH=src .venv/bin/python -B scripts/manage_local_knowledge.py restore --file docs/p34/knowledge-revisions.json
PYTHONPATH=src .venv/bin/python -B scripts/manage_knowledge_reviews.py register-reports --input docs/p34/source-evidence-reports.json
PYTHONPATH=src .venv/bin/python -B scripts/manage_local_knowledge.py full-backup --file .local/backups/p34-after.kb-full-backup.json
```

修订包通过现有严格Schema校验：4条v2，必须已存在对应v1，严格追加，不更新旧行。
版本不符、重复导入整批拒绝，不强制覆盖。声明登记同样整批校验摘要绑定及ID唯一性。
两个步骤各自事务原子；不是跨两个命令的大事务。如知识导入成功而声明登记失败，知识仍pending，
排查后只重试声明登记，不重复导入版本，不重置数据库。需要完整回退时恢复到独立空目录并核对后由操作者选择使用，
不向已有库覆盖恢复。

原p32知识导入包、46条声明及P3.3文档保持历史原貌；部署代码或拉取本分支不会自动写入用户知识库。
当前本地已授权的真实库执行上述步骤，保存23个ID、27个版本、50条声明、0审核决定。
23条v1及46条旧声明逐项一致；本次4条新增v2和4条原页声明全部pending，无专项审核提升。

## 完整恢复

```sh
PYTHONPATH=src .venv/bin/python -B scripts/manage_local_knowledge.py --kb-dir .local/p34-recovery-check full-restore --file .local/backups/p34-after.kb-full-backup.json
PYTHONPATH=src .venv/bin/python -B scripts/manage_local_knowledge.py --kb-dir .local/p34-recovery-check full-backup --file .local/backups/p34-restored.kb-full-backup.json
```

比较完整JSON（含archive、evidence_reports、review_decisions、snapshot_digest及authentication_tag）应完全相同。
普通backup/restore仅处理知识，不能代替full-backup/full-restore保存材料声明、决定和撤回历史。
使用既有私钥的备份须另行安全保管私钥，不把私钥写进备份或Git。
本次真实库无审核或撤回；既有合成测试覆盖带审核与撤回的完整恢复，不把合成批准当作真实材料审核。

## L05验收入口

```sh
PYTHONPATH=src .venv/bin/python -B scripts/run_prelesson_console.py --port 8767
```

本地智能备课→按课次备课→L05。七类教师字段、版本历史及JSON导出沿用P3.3。
专项素材K011v2、K012v2；进阶K018v2；评价K019v1。K010v2仍仅在先修定位核查区。
扫描原页核对声明可追溯，但受控引用为空，全部不是实施许可。
已保存旧稿不会无声替换为新知识：导出时撤下旧素材正文，提示重新生成；新稿显示当前v2定位。
无逐条专项意见前仍保留先修/资源不足暂缓和技术指导空列表。

L05-reviewable-draft.json是通过真实本地HTTP生成、教师编辑保存版本2、导出得到的验收样例。
班级/资源及教师填写文字是明确标注的合成验收数据，不是实际教师签署、冰场授课或学生记录。
L05-reviewable-draft.md供教师阅读；具体动作技术字段仍待填写与逐条复核。

## 测试命令

```sh
PYTHONPATH=src .venv/bin/python -B -m pytest -q -rs -p no:cacheprovider
PYTHONPATH=src .venv/bin/python -B scripts/verify_l05_application_browser.py
PYTHONPATH=src .venv/bin/python -B scripts/verify_l05_application_browser.py --p34
PYTHONPATH=src .venv/bin/python -B scripts/verify_lesson_planning_v3_browser.py
node --check src/integrations/prelesson/console_static/lesson-planning.js
git diff --check
```

新增tests/test_p34_source_verification.py覆盖真实修订包Schema、来源摘要绑定、无伪造审核、
旧23/46完整保留、重启、完整恢复、冲突/非法批次无损拒绝、旧稿引用失效及新稿45分钟pending。
原P3.2合成测试继续验证受控审核、撤回和备份边界，原P3.3测试继续验证七字段编辑、导出及跨会话隔离。

193跳过不作为通过，仍缺隔离PostgreSQL与获授权真实视频。

## 实际结果

- 完整pytest最终结果：951 passed, 193 skipped, 1 warning，89.77秒；新增7项通过。
- 193项跳过：191项需要显式隔离PostgreSQL，2项需要获授权真实视频；均未冒充本轮通过。未修改相关模块，因此不阻塞本次来源修订包审阅，但不能据此声称真实视频推理或生产数据库已验收。
- 1项警告：第三方cozeloop的Pydantic类配置弃用提示，与本次修订无关。
- 首轮为950通过、1失败：旧测试依赖定位警告中的原句；修订提示保留该语义并补充PDF94页首收尾细节后，完整重跑951通过。没有放宽测试或审核条件。
- Chromium原P3.3模式、加载真实P3.4 pending修订模式、原课次备课回归全部通过：七字段、版本、实际JSON下载、失效引用刷新、旧响应取消、资源暂缓及旧页签。
- 实际本地HTTP样例生成→编辑v2→历史v1/v2→JSON导出通过；前后知识完整快照一致。
- 实际本地持久化更新及完整恢复：23 IDs／27 versions／50 reports／0 decisions，原23条v1及46条声明逐项未变，全部pending，恢复快照完全一致。
- JS语法、git diff --check通过。未发现本次修订包的阻塞性代码问题。
- **逐条专项材料仍缺，阻塞正式技术教学批准；本PR只交付可审阅、可追溯的pending修订和教案。**

## 实际修改文件

- src/integrations/curriculum_v3/registry.py：旧候选冲突提示不再错误声称尚无原页，保留冲突与审核拦截。
- src/integrations/prelesson/console_static/lesson-planning.js：对应安全文本提示。
- scripts/verify_l05_application_browser.py：新增--p34验收现有工作流与真实pending修订。
- tests/test_p34_source_verification.py：7项修订、恢复及引用回归。
- docs/p34/artifact-manifest.json：扫描片段摘要、页码映射与审核边界。
- docs/p34/knowledge-revisions.json：4条v2严格Schema增量。
- docs/p34/source-evidence-reports.json：4条绑定原页摘要的独立核验声明。
- docs/p34/textbook-verification.md：22页逐页核验、来源冲突及课程自拟性质说明。
- docs/p34/L05-reviewable-draft.md：教师可审阅草稿。
- docs/p34/L05-reviewable-draft.json：实际HTTP生成、编辑保存与导出样例。
- docs/p34/operations-and-tests.md：本说明与真实测试结果。

扫描原件、渲染图、SQLite、完整本地备份、私钥均未进入Git。未合并、部署或开发非本阶段功能。
