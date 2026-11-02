# P3.2 候选教材知识、独立材料证据与受控草稿引用

基线：main 19863f02150ecb2ad9255738ab013cedc7fdeddd（PR #17已合并）。
分支 feat/p3-2-reviewed-knowledge。沿用P3.1 SQLite、备份/恢复、本地会话与视频边界，不重做持久化。

## 实际资料与Schema核对

用户提供ZIP含01_Expert_Reviewed_Answers.docx、02_Knowledge_Entries.docx、03_Knowledge_Candidates.json。
没有教材原PDF；五问稿明确自述不是专项教师签署证明。用户说明“专项同学内容认可”作为独立上下文声明保留，
不反推任何个人姓名、逐条审核、签名或审核日期。文件名不是身份凭据，附件中的“Codex导入规则”未作为可执行指令。

原始JSON不是当前Archive格式：claim/content不同，version为draft-0.1，来源状态unverified不属于现有枚举，另有额外字段。
先校验原格式并记录失败类型，再通过显式CandidatePackage校验后转换：claim→content，version→整数1，
draft-0.1保存在candidate_version，unverified→pending（绝不映射verified）。
保存原书名、source_id、PDF/印刷页码原字符串、适用课次、正文核对声明及范围限制。
chapter字段留空表示待补充，不猜章节或版次。区分source_summary、catalogue_lead和course_proposal。
普通前端编辑新增这些元数据字段，避免追加版本时丢失资料性质与限制。

交付文件：
- docs/p32-input/p32-knowledge-import.json：23条用户候选知识，KB-S 15、KB-P 5、KB-E 3，全部pending。
- docs/p32-input/p32-evidence-reports.json：46条材料声明，23条整理材料核对声明+23条五问认可上下文关联。均不是系统通过记录。
- docs/p32-input/p32-validation-report.json：Schema差异、原文件SHA256、转换说明和资料缺项。
- docs/p32-input/L05-candidate-framework.json：由实际候选知识库生成；班级和资源是明确合成演示条件，知识不是模拟教材。

资料差异：K010/K011/K018的B02候选定位为PDF94–104，五问稿的前压步定位为PDF90–93。
用户补充说明PDF90–93主要为压步/前压步、PDF94起转入后压步。尚未获得原PDF，保留原值并报告冲突；这三条现有候选增加只读冲突标记且不能被受控批准，须原文逐页核对后追加新版本，不静默修正。课程自拟流程和评价不能改称教材原文或官方评分。

## 本轮实际接入

通过Schema校验后，向原本为空的默认本地SQLite导入23条知识及46条独立声明；关闭重开确认数量及内容恢复。
默认位置仍为 `.local/coachloop-kb/knowledge.sqlite3`，不入Git。
L05关联K011/K012/K018/K019，涉及B02/B03，引用定位均来自已有条目；无虚构文献。
所有实际条目的reviewer/review_date仍为null，系统受控通过记录为0；没有初始化真实审核密钥，没有为真实材料制作认证标签。
没有PDF、原DOCX或学生资料入库/入Git；仅将用户提供的候选摘要及来源元数据、原始文件摘要随PR交付。

## 四层状态

1. 来源已登记：source_id/title/locator齐全，不证明原文支持。
2. 原文已核实：须独立原文核对材料，不能由evidence_inspection_note“正文已核对”字样自动推定。
3. 专项同学已确认：保留具名专项材料或用户报告的认可上下文；当前只有五问整体认可的转述，不能推为每条通过。
4. 系统可信审核：本地受控责任人对精确条目/版本/正文/课次和独立材料作出经过机器认证的决定。

机器认证只证明控制本地密钥的责任人执行了离线操作，不认证教练资质，不是专业人员的电子签名。
系统不自行生成专业审核人或审核日期；缺少时记录null。真实身份及意见真实性仍需组织在应用外核实。
默认不配置审核密钥：所有条目仅展示元数据、材料声明和待确认提示，正式依据及动作指导为空。
如果组织不能建立可信责任人和专业材料核对渠道，应继续保持默认关闭，不应启用下面的受控操作。

## 受控离线流程（网页没有批准接口）

SQLite schema由1迁移为2，事务新增evidence_reports/review_decisions两张独立追加表，旧知识历史不改写。
先停服务并按P3.1说明备份。升级后不要用旧P3.1程序访问schema2；不自动降级。

普通网页POST /api/v3/evidence仅登记声明，GET读取；绑定knowledge_id/version/digest/source_id，不能写system_trusted或批准记录。
正文和专项材料必须分开登记。普通Archive导入仍拒绝reviews、认证字段和verified/approved/certified。

离线工具：

```sh
# 普通候选导入复用P3.1；在新的空目录恢复，不覆盖既有K001等历史
PYTHONPATH=src .venv/bin/python scripts/manage_local_knowledge.py --kb-dir .local/p32-example restore --file docs/p32-input/p32-knowledge-import.json
# 材料声明整批事务登记，任一冲突/绑定错误整批拒绝；不会批准
PYTHONPATH=src .venv/bin/python scripts/manage_knowledge_reviews.py register-reports --kb-dir .local/p32-example --input docs/p32-input/p32-evidence-reports.json
```

真正审核时，受信责任人须先提供真实来源页/授权原文片段和具名专项意见，登记EvidenceReport：
source_report/original_source_excerpt、specialist_report/specialist_review；给出实际文件SHA256、准确定位及其审核人信息。
整理摘要、目录、用户整体认可不能冒充原文或逐条专项意见。目录线索和unspecified条目不具备通过条件。
所有意见绑定Knowledge完整canonical SHA256、版本与source_id。

由责任人在应用外保管32字节随机本地审核密钥文件（0600、非链接、当前OS用户拥有；建议位于0700目录），
不能放Git、浏览器或普通请求体。本轮没有为真实资料生成这个密钥。准备ReviewDecision时：
review_id、knowledge_id/version/digest、两个evidence_id、decision、approved_statement、lesson_ids、真实reviewer、实际review_date或null。
approved_statement必须与被审核正文完全一致，课次是原关联课次的子集。

```sh
# 仅受信本地责任人执行；tag是机器操作认证，不是专业签名
PYTHONPATH=src .venv/bin/python scripts/manage_knowledge_reviews.py seal-decision --input /private/decision.json --review-key-file /private/operator.review-key --output /private/sealed.json
PYTHONPATH=src .venv/bin/python scripts/manage_knowledge_reviews.py apply-decision --kb-dir .local/p32-example --input /private/sealed.json --review-key-file /private/operator.review-key --source-artifact /private/source-excerpt.pdf --specialist-artifact /private/specialist-review.docx
# 只有明确配置同一受控密钥的本地实例，才采用通过记录
PYTHONPATH=src .venv/bin/python scripts/run_prelesson_console.py --kb-dir .local/p32-example --review-key-file /private/operator.review-key
```

申请通过必须现场读取两个实际文件并匹配登记SHA256；无文件、hash变化、未具名专项材料、摘要冒充原文均拒绝。
未正确认证或未配置密钥时不采用记录。decision也支持rejected/revoked，采用同条目版本的最新受控决定；重复review_id拒绝。
条目新版本不能继承旧通过记录。撤回后，已有教案的导出/历史/编辑响应也重新核对当前资格，移除失效建议，保留撤回引用ID和重新生成提示。
文件签名不验证人类资质；责任人对材料支持关系与专业身份核实承担审核责任。需要组织级身份认证时另建真实上游，本阶段不伪造。

## 备课与引用边界

通过条件满足的条目进入按课次的teaching_suggestions，每条含knowledge_id、version、source_id、书名、章节/定位、review_id和两个独立证据ID。
KB-S的来源整理陈述才可进入technical_guidance；KB-P/KB-E和course_proposal单独展示为草稿建议，不冒充原文技术标准。
即使存在受控建议，整课仍为pending_review，专项实操仍需现场教师、资源、先修和安全复核；没有自动实施或正式批准。
9+29+7分钟、资源不足和先修不足暂缓、24主题及其旧API、视频算法和本地视频限制保留。
当前真实L05只有4条候选资料、8条上下文声明，原文/专项逐条证据不足，技术指导为空；不编造交叉步要领、纠错或等级标准。

## 保存、备份与限制

知识和材料/决定表在SQLite重启保留，权限沿用P3.1；报告和决定各最多500条，报告累计900KiB。
P3.1 Archive JSON仍只备份知识版本；离线审核材料导出另外包含evidence_reports。普通JSON恢复不会激活机器认证记录。
完整保留系统决定与撤回历史，请使用下面的离线full-backup/full-restore；包含决定时必须提供匹配的审核密钥，密钥另行私下保管，不进入备份。恢复只允许空库，普通网页及Archive导入不能恢复审核权限。
不把数据库或密钥提交Git。公开交付包不含任何真实批准记录。没有自动下载或保存原PDF，没有OCR。
私有教案仍在独立浏览器会话内存中，不与知识库共享。

## 验证

```sh
PYTHONPATH=src .venv/bin/python -B -m pytest -q -rs -p no:cacheprovider
PYTHONPATH=src .venv/bin/python -B scripts/verify_lesson_planning_v3_browser.py
node --check src/integrations/prelesson/console_static/lesson-planning.js
git diff --check
```

所有模拟审核人、密钥和原文文件只在临时测试中使用，明确SYNTHETIC，不混入23条实际候选。
测试包括普通导入/网页不得批准、材料正文/版本/课次/hash绑定、原文缺失/摘要/目录拒绝、撤回、新版本失效、引用及重启恢复、P3.1 schema迁移。

本轮实际结果：920 passed, 193 skipped, 1 warning（57.05秒），P3.2新增14项全部通过。
193跳过仍为191项未配置隔离PostgreSQL、2项未提供获授权真实视频；不计为通过。第三方cozeloop保留Pydantic弃用警告。
两个现有Chromium脚本回归通过；JS语法和diff检查通过。数据库中实际候选23、材料声明46、系统决定0，重开后一致。
原24主题引擎、生产main、视频算法和生产数据库/mock隔离文件无改动。


## PR #18 合并前最终修复：完整备份与恢复

原“备份”仅保存知识版本，原审核材料导出也遗漏决定/撤回顺序，不能当作完整审核历史备份。
保留这些旧接口兼容性，并在界面和CLI明确标记其范围；新增仅离线的完整快照入口。
完整快照含全部知识/版本、独立材料声明、按原SQLite插入顺序的所有决定（包括拒绝和撤回）、校验摘要。
含审核决定时，对整个快照作独立域的HMAC认证，绑定顺序及完整性；仅校验每条决定的tag无法发现撤回记录被删，因此不够安全。
有历史但无匹配密钥时拒绝完整导出或恢复，不降级为丢失审核历史的“成功”备份。

```sh
# 停止指向该库的服务；当前实际库没有审核决定，因此不需要密钥
PYTHONPATH=src .venv/bin/python scripts/manage_local_knowledge.py --kb-dir .local/coachloop-kb full-backup --file .local/backups/example.kb-full-backup.json
PYTHONPATH=src .venv/bin/python scripts/manage_local_knowledge.py --kb-dir .local/empty-restored-kb full-restore --file .local/backups/example.kb-full-backup.json
# 若已存在审核决定，两条命令均增加：--review-key-file /private/operator.review-key
```

输出文件0600、排他创建、不覆盖已有文件；完整JSON读取上限32MiB。完整备份后缀被Git排除。
恢复校验快照认证/摘要、Schema、证据引用、版本、重复ID及容量，并在单事务内写入。
目标任一表非空则拒绝，不合并、不替换；任一错误回滚，不破坏目标已有数据。
原决定tag、材料、审核日期null/原值及插入顺序原样保留，不重新封装决定，不制作新批准。
恢复后的撤回继续生效；不配置审核密钥运行时仍不采用通过记录。
完整备份只代表其创建时点，之后新增的撤回不在旧备份里，恢复前须核对最新备份/撤回记录，不能把旧时点当当前授权。
外部原文文件不嵌入备份，仍需另外保管对应原件；没有引入PDF解析、P3.3或新认证体系。

实际本地库在修复前后均为23条候选、46条声明、0条系统决定，全部pending；知识/声明与交付包逐字段一致。
已完整备份到本地私有目录 `.local/backups/pr18-final.kb-full-backup.json`，并在临时空库恢复核对完全一致；原库未覆盖。
K010/K011/K018的原定位和知识版本不改写，K011/K018仍为course_proposal。
新增测试覆盖真实候选包往返不提升、批准→撤回顺序重启恢复、删除/重排撤回的篡改拒绝、错误/缺失密钥、非空目标拒绝、事务回滚、CLI以及普通网页不得恢复审核权限。

最终复审实际测试：
- 全量 `PYTHONPATH=src .venv/bin/python -B -m pytest -q -rs -p no:cacheprovider`：930 passed, 193 skipped, 1 warning（59.28秒）。
- 在全量检查后补充定位冲突的受控批准拒绝用例；`PYTHONPATH=src .venv/bin/python -B -m pytest -q -p no:cacheprovider tests/test_p32_full_backup.py`：11 passed（3.58秒）。
- 两个Chromium回归脚本、JS语法、git diff检查均通过。
- 193跳过仍为191项未配置隔离PostgreSQL和2项缺少授权真实视频，不能计为验收通过；第三方Pydantic弃用警告保留。
- 原23条知识JSON与46条声明JSON文件未修改；实际SQLite记录与原交付包一致，未批准或提升任何真实条目。
复审结论：已修复完整备份容易遗漏审核/撤回历史的问题，未发现剩余合并阻断项，建议人工确认后合并。未合并、未部署、未创建P3.3。
