# L05教学闭环MVP｜操作与验收

基线：最新main ef3b53dec701dacd694aa92863f7d9ac119b2018，已包含合并的PR #21。
独立分支feat/l05-teaching-loop。本轮仅补私有连接层，不重复构建课程、知识库、算法或认证。

## 开发前审计：直接复用与缺口

| 模块 | 直接复用 | 本轮仅补的连接 |
|---|---|---|
| 备课 | curriculum_v3的L01–L08、9/29/7、L05七字段、PlanStore版本及guard_current_evidence | 读取同一签名会话的已保存L05版本，不改教案或24主题契约 |
| 视频 | local_video的上传/规范化/MediaPipe/V4、限额、TTL、同会话Job | 将ready任务ID绑定到L05和ANON编号；无新上传路径或新推理 |
| 事件复核 | 原review端点及序列冲突、历史、confirmed/uncertain等状态 | 将事件序列、文字和质量绑定到整份反馈确认，事件确认不自动升级整份反馈 |
| 反馈 | 现有feedback()质量与未认证观察适配器 | 教师自填观察、后续复练任务、显式本地确认及完整JSON |
| 安全 | LocalBoundary、CSRF、独立视频Cookie、PlanSessions | 同时绑定两个既有会话所有权；production main和Cloudflare仍不挂载/不放行 |

已有能力没有“L05教案＋视频任务＋匿名编号＋反馈版本”的私有记录模型，故本轮新增小型进程内存连接层。
不使用共享知识库保存私有数据，也不滥用原数据库mock训练归档或生产认证。

## 课堂汇报演示（不需要真实学生视频）

```sh
PYTHONPATH=src .venv/bin/python -B scripts/run_prelesson_console.py --port 8767
```

1. 本机打开http://127.0.0.1:8767，按课次备课选择L05。填明确的合成条件，不勾选未核对的先修，生成45分钟框架。
2. 编辑目标及七类字段，保存为教案新版本。未保存文字不能关联为“当前已保存教案”。
3. 切到“视频动作分析”，点击“创建合成关键点演示（不调用MediaPipe）”。40个固定合成帧通过原几何、V4和V5，界面和导出始终is_mock=true。
4. 查看候选事件，可显式选confirmed或uncertain并提交本地未认证复核。confirmed只报告变化，不证明技术错误。
5. 点击教案区“进入L05教学闭环”，或展开页面底部“L05教学闭环”并点击“读取当前L05教案与本机任务”。
6. 填ANON-005等匿名代号（不能用真实学号）、观察结论和后续复练任务，关联保存为反馈草稿。
7. 自行核对后显式勾选声明，再点击“本地教师自报确认当前版本”。状态只成为locally_confirmed_unverified，身份与专业资格未认证，不显示为专业已审核。
8. 修改反馈后追加保存，确认失效；未保存内容不能导出。证据变动后先重新核对，再决定是否确认。
9. 点击“导出完整闭环JSON”。刷新同一浏览器可通过“恢复本会话已保存记录”重开，服务退出或任务失效后不能恢复。
10. 为演示失效，把事件改为uncertain，重新核对/导出应显示draft与confirmation_current=false；不得沿用旧确认。

真实视频路径沿用原本机MP4/MOV上传、授权声明、FFmpeg和MediaPipe隔离环境；模型/环境/视频授权缺一不可。
真实分支不创建新的推理算法，也不使用合成结果冒充MediaPipe识别。本轮端到端验收只使用显著标记的合成关键点。
每个既有视频会话只能保留一个任务；已有任务时必须先显式清除，合成按钮不会覆盖真实分析。

## 反馈与确认的语义

- feedback_review_status=draft：未确认、修改后，或确认时的证据已变化。当前有效性看confirmation_current，不看历史confirmation对象是否存在。
- locally_confirmed_unverified：仅当前本机操作者勾选后确认了这份文字与证据，不证明真人教师身份、专项资格或内容正确。
- authenticated_teacher=false、specialist_review_status=pending、technical_error_assessment=not_assessed、trusted_observations=[]保持。
- 原base_feedback仍为draft，不能因连接层本地确认就升级其专业资格。
- 教师自己输入的观察/任务均为未认证文字。系统不从候选事件自动推断用刃、真实重心、等级、错误原因或纠错处方。
- 依据摘要覆盖关联教案版本、同教案最新版本、当前知识资格以及质量、事件状态/备注/历史。修改教案、知识更新/撤回或事件复核变动后，读取/导出重新核对并降回草稿；旧确认只保留审计。
- 关联的教案版本不被无声替换。导出同时列plan_version和current_plan_version，需改用新版本时重新关联一条观察。

## 隐私、保存与删除

- LoopStore只存本机进程内存，最多100个累计版本/2MiB；乐观版本与证据摘要冲突拒绝写入，不覆盖旧记录。
- 私有所有权同时绑定现有计划签名会话和视频会话。共享的本机控制台Cookie或一个被复制的计划Cookie都不能越权读取他人视频/反馈。同一浏览器配置文件的标签页共享会话。
- 受原视频任务20分钟、视频会话30分钟限制。删除/过期后立即不可读，闭环副本在下一次闭环访问时清理；退出服务清空。没有新磁盘持久化或重启恢复机制。
- “删除当前闭环记录”只删这份反馈；“清除本机视频任务”沿用原视频清理，并使关联反馈失效。已导出副本由操作者自行删除。
- 不写共享SQLite知识库、生产数据库或mock归档；不存真实身份、不建学生账号。导出仅含匿名编号、教案、质量/候选摘要、文字和审计，不附视频、原始关键点、Cookie或原始磁盘路径。
- 导出仍可能敏感，用户须本地保管，不自动上传GitHub或第三方。公开样例仅为固定合成情境，真实反馈不得照此提交公开仓库。
- 没有闭环JSON导入；它是离线留档，不是专业审核、学习通导入或可自动恢复的存储包。

## 本地连接API

仅现有loopback控制台挂载`/api/v3/loops`：POST link/edit/confirm/delete/demo-analysis，GET current/export/history。
link只允许当前浏览器已保存的L05，匿名编号为ANON-加3至8位数字；不是任意个人标识。
edit/confirm要求当前expected_version与expected_evidence_digest；确认另需严格布尔声明和非空观察/任务。
普通请求不能传入确认状态、审核人或审核日期；demo-analysis必须显式synthetic_demo=true。
读取同时验证控制台、计划和视频会话；POST沿用Origin、CSRF和严格JSON限制。production main与Cloudflare相应API/脚本均404。
所有新显示文字通过textContent，教师新输入限制长度并拒绝HTML和非法控制字符。

## 交付

- [教师可读报告](L05-teacher-feedback-report.md)：合成过程、观察、任务和确认失效。
- [完整JSON](L05-loop-demo.SYNTHETIC.json)：当前草稿与4版本历史。
- [当时本地确认快照](L05-loop-confirmed-local.SYNTHETIC.json)：仅历史，不是当前有效证明。
- [真实浏览器截图](L05-loop.SYNTHETIC.png)：合成演示草稿。
- [测试与修改清单](acceptance-report.md)。

尚缺真实授权花滑视频端到端验收、逐条专项意见、现场安全与学情确认、实际教师使用反馈；本机确认不能代替这些证据。
未开发新模型、评分、复杂Agent、学生账号、公网上传、学习通接入或自动部署。
