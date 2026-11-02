# L05教学闭环验收报告

## 基线、复用和改动

fetch后的main为ef3b53dec701dacd694aa92863f7d9ac119b2018（PR #21已合并），独立分支feat/l05-teaching-loop。
开发前核对了curriculum_v3、local_video、LocalBoundary、PlanSessions、事件V5复核和原浏览器验收。
现有能力与缺口见README的审计表，本轮不重复实现MediaPipe、几何、V4、七字段教案、知识审核或数据库。

连接层只做：本会话L05已保存教案版本＋ready分析任务＋匿名编号＋教师观察/复练任务＋反馈版本/显式本地确认。
合成入口生成固定MOCK关键点，仍通过原几何、V4、V5；不是新推理或对真实识别的替代验收。

## 实际验证命令

```sh
PYTHONPATH=src .venv/bin/python -B -m pytest -q -rs -p no:cacheprovider
PYTHONPATH=src .venv/bin/python -B -m pytest -q tests/test_teaching_loop.py -p no:cacheprovider
PYTHONPATH=src .venv/bin/python -B scripts/verify_teaching_loop_browser.py --output-dir work/new-loop-evidence
PYTHONPATH=src .venv/bin/python -B scripts/verify_lesson_planning_v3_browser.py
PYTHONPATH=src .venv/bin/python -B scripts/verify_l05_application_browser.py --course-mvp
node --check src/integrations/prelesson/console_static/teaching-loop.js
node --check src/integrations/prelesson/console_static/video-console.js
node --check src/integrations/prelesson/console_static/lesson-planning.js
git diff --check
```

--output-dir须为新目录，只输出本脚本固定合成情境；验收使用临时SQLite，真实库不变。

## 结果与边界

- 新增25项连接层测试通过。覆盖L05/版本绑定、观察与任务、草稿/显式确认、修改降回草稿、事件或教案变化、合成受控知识撤回、并发版本/摘要冲突、非法文字/伪造身份、匿名编号、双会话隔离、TTL/删除、100版本上限、共享KB不变，以及production main和Cloudflare真实拒绝请求。
- 完整回归最终结果：986 passed, 193 skipped, 1 warning（91.80秒）。新增25项全部通过。
- 相关回归88 passed, 2 skipped, 1 warning；2项缺授权真实视频，不算通过。
- Chromium实际操作通过：编辑保存L05七字段→创建合成分析→原事件复核→关联匿名观察→草稿→显式本地确认→追加反馈→证据变更失效→实际JSON下载→刷新恢复。
- 浏览器还检查未勾选不能确认、未保存不能导出、重核证据保留未保存文字；旧响应/证据变化不会作为当前确认显示。
- 原课次备课与八课课程MVP浏览器回归通过；旧页签和资源暂缓保留。
- 页面截图已实际查看，显著标注合成、未调用MediaPipe、反馈草稿及身份未认证，没有学生影像或真实个人信息。
- JS语法与diff检查通过。真实默认KB与P3.4完整快照的只读比较完全一致：23 IDs／27版本／50声明／0决定，不新增知识/声明/决定。

193跳过仍是191项未配置专用PostgreSQL与2项缺授权真实视频；它们不算通过，也不能由合成关键点冒充真实推理验收。
1项警告为第三方cozeloop的Pydantic类配置弃用。
本轮浏览器初次运行修正了等待旧事件成功提示的验收脚本问题；没有放宽断言。随后端到端和旧浏览器回归通过。

## 实际交付含义

L05-teacher-feedback-report.md是从实际浏览器下载JSON整理的教师可读报告；所有观测和教师文字均为合成验收数据。
L05-loop-confirmed-local.SYNTHETIC.json是当时版本2有效的本地自报确认快照；不是专业审核或真人教师签署。
L05-loop-demo.SYNTHETIC.json是版本4证据改变后的完整草稿，保留历史确认但confirmation_current=false。
字段中保存的确认时间只证明自动化测试实际请求时间，不能伪装为专项同学审核日期。

## 存储与剩余问题

- 没有新增磁盘保存或导入恢复：闭环记录限时进程内存，100版本/2MiB；任务删除、过期后不可读，访问时清理，服务退出清空。长期留档只能用户导出本地JSON。
- 本地教师身份/专业资格仍未认证。确认只绑定当前本机输入和证据，不能升级知识审核或产生技术结论。
- 尚缺真实获授权花滑视频端到端验收、逐条专项意见、现场安全和学情、真实教师使用反馈；本轮不声称完成实际教学或学生测评。
- 导出文件是独立副本，不能自动随知识撤回更新，使用前须回到服务端核对；不自动上传学习通或其他服务。

## 实际修改文件

- src/integrations/teaching_loop/__init__.py、service.py、api.py：限额私有连接、显式确认、证据重核、审计及同会话路由。
- src/integrations/teaching_loop/synthetic.py：显式合成演示，原几何/V4/V5，不调用MediaPipe。
- src/integrations/prelesson/console.py：仅本地挂载、既有双会话验证及退出清理。
- src/integrations/local_video/service.py：只让合成任务的source_kind正确显示；真实任务响应不变。
- src/integrations/prelesson/console_static/teaching-loop.js：新私有闭环操作、纯文本报告、保存/确认/导出/恢复/删除。
- src/integrations/prelesson/console_static/index.html、console.css、console.js：入口、局部样式和仅本地加载脚本。
- src/integrations/prelesson/console_static/lesson-planning.js：传递已保存L05版本、未保存状态和变更通知。
- src/integrations/prelesson/console_static/video-console.js：显式区分合成、复用原复核、变更通知，真实视频处理不变。
- scripts/verify_teaching_loop_browser.py、scripts/verify_l05_application_browser.py：复用原Chromium脚本增加闭环实操验收。
- tests/test_teaching_loop.py：25项隔离合成测试。
- docs/teaching-loop/README.md、acceptance-report.md、L05-teacher-feedback-report.md：操作、边界、测试和报告。
- docs/teaching-loop/L05-loop-demo.SYNTHETIC.json、L05-loop-confirmed-local.SYNTHETIC.json、L05-loop.SYNTHETIC.png：实际下载的合成样例和截图。

未修改tools/video_analysis算法、生产main、数据库/mock隔离规则、知识条目/审核机制及原24主题引擎。
未提交真实视频、原始关键点、教材扫描、私有真实反馈、数据库或凭据。未合并或部署。
