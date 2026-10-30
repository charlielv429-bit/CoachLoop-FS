# CoachLoop-FS：集成交付状态与最小人工交接

日期：2026-10-30（北京时间）。线上代码基线main `3875f17`。本分支完成本地合成演示与受限数据库验证，不代表Coze上线验收。

## P0：认证、地址与端口

- 当前没有Coze账号连接器、浏览器控制或平台凭据注入能力。Mac路径未挂载，代码操作发生在云工作区。
- 云环境网络状态明确为restricted/enforced；官方Coze文档和 `33vnf9hq7m.coze.site` 请求均被出口代理以CONNECT403拒绝。该403不是源站状态，不能用于判定源站部署失败。本轮没有重复尝试密钥或猜测header。
- 用户已报告线上health与应用Bearer均401。部署源代码health不要求Bearer；应用错误Bearer应403。因此上游拦截/头未透传是强假设，尚未精确定位。5000与源码默认一致，网关401不证明端口已转发。
- 诊断工具分支已包含在本分支：`scripts/diagnose_coze_gateway.py`。不要求用户再次重复已有Mac测试，先取得新的平台调用规范。

安全适配决策必须依据官方调用示例：若平台认证使用独立header，应用Bearer可保持；若两者都使用Authorization且凭据不同，不能拼接、互相覆盖或关闭认证。需先确认官方透传与多凭据安全配置能力，再评估显式第二应用凭据头及对应Schema的最小变更。本分支没有实现未经证实的新认证路径，也没有修改生产认证。额外中转部署可能产生费用，未执行。

## P1：插件与ZIP

已读取官方组织的 [Coze Studio README](https://github.com/coze-dev/coze-studio/blob/main/README.md)：它链接到官方插件资源文档并明确开源/商业版有差异。该证据只能确认开发平台的资源概念，不能证明Coze Coding“扩展→我的→上传插件包”的ZIP结构或coze.site网关规范。官方文档正文仍不可访问，仓库无官方ZIPmanifest或导出模板。因此**没有制作冒充兼容的ZIP**，也不保证当前界面存在OpenAPI导入菜单。

已配置HTTPS的候选文件：[prelesson.coze-site.openapi.json](demo-delivery/prelesson.coze-site.openapi.json)，仅包含POST `/api/v1/lesson-plans/draft`、Bearer及真实API契约；没有占位域名或凭据，明确标记“尚未通过线上验证”。插件名称：**CoachLoop-FS 智能备课助手**。该文件是OpenAPI3.0.3，不是ZIP扩展包，尚未安装。

## P2—P4：本地可运行闭环

直接打开 [demo.html](demo-delivery/demo.html) 查看离线演示：无需模型、账号或网络，数据全部合成。它只展示脱敏测试证据，没有执行按钮或自动批准能力。GitHub文件页可通过下载原始文件保存；这不是部署网页或Coze应用。

代码链路：

1. 现有课前HTTP/`run_prelesson` → 七要素、45分钟、预计负荷、draft/unverified。
2. `integrations.three_stage_demo.synthetic_video_stages` → 40帧合成关键点 → 复用原几何特征、V4检测、V5待审核记录。没有调用MediaPipe或重新处理真实视频。
3. 独立PostgreSQL16中，受限agent创建真实生成草稿的db-a-1适配载荷；受限MOCK teacher明确模拟提交/批准；受限importer调用既有训练导入HTTP；重复请求返回同一收据；reader查询归档事件。
4. 受限MOCK coach明确模拟五种审核状态。`postlesson_agent.draft_from_database`只从已验证租户数据库连接读取，拒绝跨身份或不存在的训练；pending/tracking_error/uncertain及未认证记录不进入反馈观察。confirmed仍仅表示可观测变化，技术错误未评定，不给技能分数。
5. 课后输出为draft、requires_teacher_review=true、knowledge_status=unverified，分层练习为固定零基础模板建议，不是事件诊断。最终教师复核和课后报告归档**未实现**；已实现归档的是训练事件与追加审核历史。新课后能力仅为Python只读边界，没有挂到main或公开生产HTTP。

数据库中的authenticated仅表示测试数据库受限角色的审核状态；演示显式记录 `human_review_performed=false`，不能冒充真实教练审核。没有将真实Coze数据改标mock。

## 三阶段×五功能：真实状态

| 阶段 | Agent任务 | 插件 | 工作流 | 数据库 | 知识库 |
| --- | --- | --- | --- | --- | --- |
| 课前 | 本地七要素草稿已运行 | OpenAPI候选已生成；未安装 | 本地LangGraph已运行；Coze未绑定 | 合成教案入库与MOCK教师状态机已测；生产课前不依赖DB | A/B/C校验已有；无已核实在线来源 |
| 课中 | 本地候选事件与审核工具复用 | Coze已有识别由用户报告；配置未验证 | 本地几何→V4/V5→导入链已测；Coze未联通 | mock训练、事件、追加审核已测 | 安全/动作标准未核实，不输出正式技术判断 |
| 课后 | 新增确定性只读反馈草稿；非已部署LLM Agent | 无课后Coze插件 | 本地查询→过滤→草稿已测；教师最终确认待实现 | 经审核事件可查；最终报告存储待实现 | 无正式引用；练习为未核实模板，待教师复核 |

**课程矩阵尚未全部达成。** 不把离线文件、测试、设计节点或用户描述当成Coze在线功能。没有已证实安装的插件或绑定的Agent。

## Agent与工作流配置文件

- [Agent配置文本](demo-delivery/agent-instructions.txt)：可复制的安全提示，不会自动安装或调用模型。
- [节点映射设计](demo-delivery/workflow-design.json)：明确是设计文件，不宣称属于官方Coze工作流导入格式。
- [Postlesson JSON Schema](demo-delivery/postlesson-draft.schema.json)：Python输出契约，不代表新增公开API。
- [PostgreSQL脱敏链路证据](demo-delivery/three-stage.postgresql.mock-evidence.json)：保留草稿、导入收据重放、DB查询与反馈，全部mock。

## P5：知识库

当前未获得可核验的课程标准、安全资料原文/页码和真实人工核验记录；在线Coze知识库也未授权接入检查。可核实正式引用数量为0，维持unverified。目录、标题和图片块不升级证据，不运行OCR、不伪造引用。课程知识库评分维度需后续实际材料与平台检索展示，不能用本地校验模块冒充已建成知识库。

## 只需用户一次性完成的最小平台操作

1. 在当前部署的API渠道调用示例中，取得**脱敏**的正式URL/路径、方法、认证头名与凭据类型、Authorization透传说明，并核对生产端口；不要发送Token。现有应用日志中核对之前的401是否到达FastAPI，不重复跑同一组Mac命令。
2. 在插件/扩展上传页取得官方包说明链接或一个空白官方导出模板，并明确所处产品与版本。若页面确实提供OpenAPI导入，可选择本分支候选；若仅ZIP，先提供规范，不能把JSON压成ZIP试错。
3. 仅在官方方式确认后，在平台秘密配置中绑定所需凭据并执行一次合成课前调试，再将插件工具绑定Agent/课前工作流。这些是账号操作，本环境无执行能力；如涉及生产认证变更或付费发布，仍需用户单独批准。

本地工作已完成到可验证边界，没有后台持续执行安排。未Merge、未部署、未上传凭据/真实数据、未调用付费模型、未修改数据库迁移或V2—V5.2。

## P6：本轮实际验收

- 隔离PostgreSQL16.15完整pytest：**758 passed、0 failed、0 skipped，32.86秒，通过率100%**。包括main原710项、现有诊断17项和新增本地演示/课后保护31项；各专项是全量子集，不重复累计。
- 新增课后单元23项、真实数据库三阶段6项、离线导出/HTML安全2项。既有视频41项、RLS、审核信任、事件一致性、幂等/并发、高精度、真实无DB启动与错误响应烟测均在全量内通过。
- 首次新增集成夹具使用不符合既有mock资源目录约束的URI，产生5个新用例失败；改正夹具后专项29项及最终全量全部通过。没有放宽SQL或业务校验。
- `git diff --check`通过；导出文件检查无占位域名、已知密钥模式或数据库连接串，全部数据明确合成。没有生产安全认证通过的证据，也没有执行真实Coze视频识别或真实人工复核。仅有既有SDK的Pydantic弃用警告1项。
- 机器可读验收：[acceptance.json](demo-delivery/acceptance.json)。本地命令：`.venv/bin/python -B -m pytest -q -p no:cacheprovider`，必须按既有数据库文档显式连接专用隔离库。脱敏证据通过本地测试runner的 `COACHLOOP_DEMO_EVIDENCE_DIR` 输出；离线文件用 `.venv/bin/python scripts/prepare_three_stage_delivery.py` 生成，不要求用户再在Mac执行这些工程命令。
