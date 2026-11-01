# V3.0 第一阶段：8课次与四类知识库

基线：fetch 后 origin/main 与 work 均为 25cd7dd77a28d94625e80bf0a0cecf26ba973bb8，left/right=0/0。
开发分支：feat/v3-phase1-curriculum-kb。未合并、未部署。

## 运行与界面

沿用本地启动器：

```sh
PYTHONPATH=src .venv/bin/python scripts/run_prelesson_console.py --port 8767
```

浏览器打开 http://127.0.0.1:8767 ，展开顶部“V3.0 · 8课次课程目录与知识库管理”。
原有智能备课、视频动作分析、训练反馈入口保留；24候选主题不变，未映射或替换为8课次。

独立 lessons.json 定义 L01–L08，固定45分钟。选择课次查看目标草稿、待审核状态、缺失资料和关联条目。
目标只表达课程名称对应的待补充草稿，不虚构专项动作标准。

四类初始为空：KB-S 花样滑冰专项技能、KB-P 体育教学方法、KB-A AI技术、KB-E 学习评价与反馈。
可新增条目，按类别/课次/关键词（标题、正文、来源标题）检索；编辑追加版本、查看全部版本、导入导出JSON。
未添加正式或模拟种子知识；测试中的模拟条目只存在测试进程中。

## 最小存储机制和生命周期

每个 console app 持有独立内存 Registry；同一进程的已授权本机控制台会话共享。
不写文件、数据库或浏览器存储，不跨进程同步。退出/重启清空，正常 lifespan 退出显式清理。
请在退出前导出JSON，下载文件由用户自行保存/删除，应用不会自动删除下载副本。
禁止填写学生身份、健康信息、凭据等敏感资料。

保存采用锁及乐观版本校验：首次 version=1，后续必须紧接当前版本。
历史保留不可覆盖；不提供删除或重写旧版本接口。ID最多64位ASCII字母、数字、下划线、连字符。
最多200个ID、500个累计版本，按UTF-8/双空格缩进计算的完整导出最多900KiB，确保可在1MiB请求限制内恢复。
达到限制返回409，原数据不变。内存生命周期内无法无限归档，长期保留由导出承担。
导入先整批校验再原子追加；任意格式错误、版本不连续或冲突整批拒绝。
恢复完整导出应在新启动的空库中进行；重复导入已有版本会返回409，不覆盖历史。

## 来源、审核与教学依据边界

每个版本保存 knowledge_id/category/title/content/lesson_ids/source_id/source_title/source_locator/
source_verification_status/specialist_review_status/version。

来源状态仅 pending、submitted、rejected。submitted 必须有非空来源ID、标题与定位。
登记应填写真实文献、作者机构可追溯的来源及页码/章节/网址；服务不访问URL，不把用户登记视作真实性证明。
无完整来源显示“待补充”；来源齐全显示“已登记，待核实”。

专项状态仅 pending、requested、rejected；均显示“待审核”（退回有提示）。
普通用户不能写入 verified/approved/certified 或审核人身份、formal_teaching_basis 等额外字段；导入同样拒绝。
第一阶段没有可信专业身份认证渠道，因此没有“通过专项审核”的操作。
条目 formal_teaching_basis 始终 false，课次 formal_teaching_basis 始终为空；不注入既有备课Agent作为正式依据。
“申请审核”只记录待办状态，不发送通知或制造专业认证。

## HTTP与渲染安全

仅 console 注册 /api/v3/lessons、/knowledge、/history、/export（GET）及 /knowledge、/import（POST）。
所有路由同时要求可信本地边界标记；GET检查会话，POST沿用精确Host/Origin、会话Cookie与CSRF头校验。
复用已有1MiB实际请求体限制、重复JSON键/非有限数拒绝及脱敏字段错误。
严格Schema拒绝未知字段、非法课次、布尔版本、空白标题/正文、HTML标签及危险控制字符。
文本只通过 textContent / input.value 渲染，来源定位不生成超链接、不执行或抓取。
课堂远程白名单不扩大，生产 main、认证、数据库mock隔离、视频算法和远程视频限制均未修改。
课堂共享HTML默认隐藏V3入口，不运行本地管理界面。

## 等待2号花滑同学提供

- 每课次教学目标、先修要求、适用对象、动作要点、常见问题及练习组织。
- 冰场/装备/师资条件、安全注意事项及暂停练习条件。
- L07/L08完整步法顺序和综合评价量规、观察指标与反馈措辞。
- 可引用真实资料原文、来源ID/标题、作者或机构、版本/日期、页码/章节/网址与使用授权。
- KB-S专项审核意见及可追溯审核身份；后续需另建可信审核渠道，不能靠普通表单自报。
- KB-P/KB-A/KB-E相关材料也须注明来源和审核责任人，避免用AI生成内容冒充专业知识。

## 验证

新增测试：tests/test_curriculum_v3.py（仅明确标记的模拟知识）。
浏览器验收：scripts/verify_curriculum_v3_browser.py（本机Chromium，无模型、数据库或真实学生视频）。

```sh
PYTHONPATH=src .venv/bin/python -B -m pytest -q -p no:cacheprovider
PYTHONPATH=src .venv/bin/python -B scripts/verify_curriculum_v3_browser.py
node --check src/integrations/prelesson/console_static/curriculum.js
git diff --check
```

全量数据库用例仍要求显式隔离 PostgreSQL；未配置时跳过，绝不连接生产库。
真实视频需获授权输入与可选模型/依赖；未满足时跳过，不冒充实测视频结论。

本轮实际结果：全量 `pytest -q -rs -p no:cacheprovider` 为 **840 passed, 193 skipped, 1 warning**（48.37秒）。
其中V3新增25项均通过。193跳过=191项缺少显式隔离PostgreSQL配置+2项缺少获授权真实视频；不计为通过。
第三方cozeloop存在Pydantic旧config弃用警告，无本轮新增失败。
Chromium实际验收输出：`V3 Chromium acceptance: 8 lessons, selection, create/edit/history, pending labels, original 3 tabs PASS`。
JS语法与diff空白检查通过。
