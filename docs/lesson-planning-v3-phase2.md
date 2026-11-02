# V3.0 第二阶段：按课次备课（本地待审核框架）

基线：origin/main b21941cc0843bac99d6e339c11e5218e56b02753，已包含PR #15及18a0eeb最终修复。
工作区干净后从最新main新建 feat/v3-phase2-lesson-planning，未重置或丢弃代码。

## 使用

```sh
PYTHONPATH=src .venv/bin/python scripts/run_prelesson_console.py --port 8767
```

打开 http://127.0.0.1:8767 ，智能备课页展开“按课次备课模式 · L01–L08（独立于24主题）”。
默认L05，填写匿名学情、师资和场地装备条件后生成。可修改目标、组织说明、资源备注，保存待复核版本，查看历史和下载服务端JSON。
原24主题表单与原API保持独立；新接口拒绝theme_id/mastered_skills，旧接口拒绝L05等课次ID。

## 组织与依据规则

- 复用 TeachingFlow 45分钟约束：准备9、基本29、结束7。
- 从adaptive.py提取共用资源暂缓/分组/活动窗口算法及文本师资一致性校验，旧路径也调用同一逻辑。
- 实际容量由教师自报，不按面积推算安全容量或官方师生比。装备不足、无教练、等待区未确认、冰面不可用、轮换无效、轮换等待无教师时均暂缓组织。
- 先修条件未确认时暂缓。课次专项先修清单尚缺，教师确认仅记录应用外核对声明，未认证，不映射为任何旧主题ID，不替代专项审核。
- 即使组织资源满足，也始终 `execution_status=withheld_pending_specialist_evidence`；组织方案是待现场核定的设计，不能当实施许可。
- 预计负荷沿用原始精度公式（准备4+结束3+轮换有效窗口，基本29=5+24，每轮转换1）。为条件满足后的设计假设，不是专项暂缓期间实际负荷，心率不估计。
- 各层学生的专项任务均留空占位，不推断动作要领、纠错、技术阈值或官方等级标准。

知识库当前只允许pending/submitted/rejected来源状态与pending/requested/rejected专项状态，没有可信通过渠道。
新框架读取关联条目的真实knowledge_id、version及来源信息，保留 `source_registered`、`source_content_verified=false`、`specialist_verified=false` 三种独立判断。
`knowledge_inventory`是未核实资料目录，`usage=metadata_only_not_teaching_guidance`；不复制正文为教学指令。
`formal_teaching_evidence`和`technical_guidance`始终为空。不生成不存在的文献或引用，不因来源字段完整/申请审核而升级为正式依据。
既有知识库版本不可覆盖，教案保存生成时的来源与条目版本快照；后续条目更新不改写旧教案。
后续真正启用专项依据，需要另建可信身份、原文支持关系核验与专项审核通道，普通编辑/JSON导入不能开放认证升级。

## 修改、保存与导出

生成后服务端分配plan_id和version=1。教师修改只接收目标、组织说明和资源备注、plan_id、expected_version。
每次追加新快照，服务端记录UTC时间、local_unverified_operator与pending_review；不会把本地操作者认证为教师/专项教练。
有效目标显示为教师待复核草稿，原始课程目标仍保留；组织与资源备注独立展示，不改写原分组、安全暂缓、时间或知识状态。
过期expected_version返回409，原记录不变。客户端修改条件会隐藏旧输出，要求重新生成；并发返回不会展示过期条件结果。

教案存储在每个console app的内存中，按浏览器会话归属隔离，正常退出清理，重启丢失。不写文件/数据库/浏览器存储。
独立HttpOnly/SameSite=Strict教案Cookie由本进程签名，刷新保留会话和服务端记录（页面暂不自动恢复输出）；缺失、伪造或旧进程Cookie不能访问教案接口。
即使知道plan_id，其他浏览器会话也不能导出、查看历史或编辑。归属标记不出现在导出中；同一浏览器配置文件的标签页仍共享Cookie，这不是教师身份认证。
第一阶段知识库仍是明确共享的本地资料库，不保存教案修改记录。
总计最多100个教案历史快照，内部JSON最多2MiB；达到任一上限返回409，无部分写入。应及时导出并自行保存，不能无限归档。
知识库沿用第一阶段独立的200条目/500知识版本/900KiB限制，互不替换。下载副本由用户管理，不会随进程清除。
历史和导出始终从服务端读取，不能提交浏览器自改的整个教案。导出标题为“待审核教案框架”，包含课次、资源、45分钟阶段、分组、分层占位、资料状态、缺项、审核清单及教师修改记录。
本阶段没有教案JSON导入、正式批准或部署功能。

## 本地接口

- POST `/api/v3/plans/draft`：lesson_id、conditions、prerequisites_confirmed，可选edits。
- POST `/api/v3/plans/edit`：plan_id、expected_version及三个修改字段。
- GET `/api/v3/plans/export?plan_id=...`：当前服务端快照。
- GET `/api/v3/plans/history?plan_id=...`：全部历史快照。

全部仅本地console注册；会话Cookie、精确Host/Origin、CSRF及可信scope标记保护沿用。
POST复用1MiB实际请求体限制、重复键/非有限JSON拒绝、脱敏错误；未知字段与伪造审核状态拒绝。
所有新增文本以textContent或value渲染，HTML/控制字符拒绝；不抓取来源URL。
课堂白名单不扩大，新增JS/教案接口在课堂返回404。未改生产main、数据库及mock规则、视频分析算法。

## L05实生成演示

`docs/lesson-planning-v3-L05.synthetic-example.json`为代码真实生成的合成班级样例，知识库为空，不含专业种子资料。
20名合成学生、2教练、1教师，声明容量10、装备20套，先修由模拟教师声明核对。
准备9分钟—基本29分钟—结束7分钟；拟定2轮，每轮2个5人组。
有效轮换窗口22分钟，人均核心11分钟；条件满足后的预计群体窗口29/45、人均18/45；非实际运动负荷。
正式专项依据为空，动作指导为空，专项实操暂缓；示范5分钟和轮换24分钟仅预留，审核前改为资料核对与口头讨论。

## 等待专项同学提供

L01–L08适用水平、可核查先修条件、目标与动作标准；特别是L05左前交叉步完整动作的授权原文、练习递进、保护及纠错边界。
每课场地/装备/人员要求、暂停条件、L07/L08步法与评价量规。
真实资料的来源ID/标题/作者机构/版本/页码或章节/授权，以及可追溯专项审核人和审核意见。
在可信审核完成前不据此生成确定性动作指导或正式通过的教案。

## 验证命令

```sh
PYTHONPATH=src .venv/bin/python -B -m pytest -q -rs -p no:cacheprovider
PYTHONPATH=src .venv/bin/python -B scripts/verify_lesson_planning_v3_browser.py
node --check src/integrations/prelesson/console_static/lesson-planning.js
git diff --check
```

浏览器脚本实际操作L05生成、修改、历史查看、下载并解析JSON、资源暂缓及原页签。
提取共用代码前后，24主题各取可组织/无教练两种输入，共48个完整JSON响应逐项一致。

本轮实际验证：全量885 passed, 193 skipped, 1 warning（46.19秒），第二阶段新增33项均通过。
193跳过=191项缺少显式隔离PostgreSQL配置+2项缺少获授权真实视频，不能视作已通过端到端验收。
第三方cozeloop保留Pydantic弃用警告。JS语法与diff检查通过。
Chromium输出：`V3 phase2 Chromium PASS: L05 generation, edits, history, actual JSON download, resource hold, legacy tabs`。

## PR #16 最终合并前复审

核对原12文件及安全相关差异；课程与主题ID仍独立。重新加载真实origin/main旧引擎，
24主题×可组织/无教练两种输入的48个完整JSON响应均与当前分支一致。
45分钟9/29/7约束、资源及未确认先修暂缓、无正式专项依据时技术指导为空、教师修改不能覆盖保护字段均保持。
输入严格Schema/1MiB实际请求限制、JSON导出及textContent安全渲染、本地Host/Origin/CSRF与课堂404边界通过。

复现并修复一个会话隔离缺口：原共享设计下，另一个独立本地浏览器取得plan_id后可返回200读取/导出历史及修改。
现由本进程签名的独立HttpOnly/SameSite=Strict教案Cookie绑定归属；API不接受客户端自报归属，存储在读取和修改时核对归属。
外会话即使知道ID也不能读取或修改；缺失/伪造Cookie返回401；刷新保留Cookie；旧进程Cookie无效；归属和Cookie不进入导出。
新增5个回归用例覆盖跨浏览器读取/历史/编辑、Cookie丢失/伪造/刷新、进程签名隔离及编辑后保护。
本地知识库的共享设计保持不变，教案总容量仍全服务100快照/2MiB，退出清空。

修复后实际测试：
- `PYTHONPATH=src .venv/bin/python -B -m pytest -q -rs -p no:cacheprovider`：890 passed, 193 skipped, 1 warning（58.27秒）。
- Chromium实际L05生成、修改、历史、下载解析JSON、资源暂缓和原页签通过；JS语法、git diff空白检查通过。
- 193跳过仍为191项未配置隔离PostgreSQL与2项无授权真实视频，不能视为已验收；这些实现未修改，不阻塞本地第二阶段合并。
- 第三方cozeloop保留Pydantic弃用警告。

非阻塞后续项：同一浏览器配置文件的标签页共享会话，不是教师身份认证；刷新后页面暂不自动恢复旧输出；
丢失Cookie的孤立教案仍占全局配额直至退出，可后续增加会话清理、历史索引与备份恢复。
专项依据仍缺可信核实与审核通道，不能把当前框架当正式专项教案。
结论：修复后无剩余合并阻断项，建议人工确认后合并；本次不合并、不部署。
