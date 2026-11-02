# 课程化展示MVP实际验收报告

## 基线与范围

fetch后的origin/main为9ae3cae63fe8a601ea2af143589b75862d8f9cd3。
GitHub PR #20确认merged=true，merge_commit_sha与该main一致；工作区干净后创建feat/course-mvp-acceptance。
复用现有课程、知识、受控审核、备份、教案编辑和本地安全边界；没有修改任何src应用代码。

## 实际执行与结果

| 命令／检查 | 真实结果 |
|---|---|
| `PYTHONPATH=src .venv/bin/python -B scripts/prepare_course_mvp.py --output-dir work/course-mvp/generated --docx` | 临时SQLite加载已有23 IDs／27版本／50声明／0决定；八课实际HTTP生成、编辑v2、历史v1/v2及导出成功，时间全部9/29/7；前后临时KB完整快照一致 |
| `PYTHONPATH=src .venv/bin/python -B -m pytest -q -rs -p no:cacheprovider` | **961 passed, 193 skipped, 1 warning，71.05秒**；新增10项课程验收全部通过 |
| `PYTHONPATH=src .venv/bin/python -B -m pytest -q tests/test_course_mvp_acceptance.py -p no:cacheprovider` | 教师Word补充准确知识正文/摘要后再验，10项通过；含八份草稿与最新API阅读投影逐项一致、来源绑定和可编辑Word结构检查 |
| `PYTHONPATH=src .venv/bin/python -B scripts/verify_l05_application_browser.py --course-mvp` | Chromium逐课选择8课、检查45分钟/pending/暂缓；L05来源与版本、七字段、反馈草稿显示、保存、历史及实际JSON下载通过；失效引用刷新、旧响应取消、原页签通过 |
| `PYTHONPATH=src .venv/bin/python -B scripts/verify_l05_application_browser.py --p34` | 原P3.4 L05浏览器回归通过 |
| `PYTHONPATH=src .venv/bin/python -B scripts/verify_lesson_planning_v3_browser.py` | 原课次备课浏览器回归通过，含资源不足暂缓、实际下载和原主题入口 |
| 真实默认SQLite与P3.4完整备份逐项比较 | 完全一致：23 IDs／27版本／50声明／0决定，无真实数据变更或状态升级 |
| Word结构检查 | 原生可编辑段落和3个表格；五个知识原文快照及knowledge_digest可追溯；无扫描/嵌入对象、宏、签名或外部关系 |
| `git diff --check` | 通过 |

193跳过仍是191项未配置专用PostgreSQL、2项缺少授权真实视频。它们不算通过，不能据此认定真实视频推理或生产数据库已验收。
本轮不修改这些模块。1项警告为第三方cozeloop Pydantic类配置弃用。
Word完成了内容/结构核验，没有执行Word/WPS打印分页验收；教师正式转PDF前应本地检查分页。

## 完整性结论

- 8课目录、45分钟组织草稿与软件展示流程完整；不是8课已获专项教学批准。
- L05最终教师送审文稿可编辑，七类内容、逐条意见和反馈区完整；原页事实与课程自拟安排分开。
- 原页定位已经核对的候选与系统可信审核分离；所有候选仍pending，受控技术指导为空。
- 原24主题、先修与资源暂缓、视频和本地数据隔离沿用，完整回归无新增失败。
- 教师反馈是空白收集表与未认证教案文字，不冒充真实授课意见或视频分析结果。
- 学习通只完成资源筹备建议，未访问或测试平台，不宣称已上传或上线。

## 尚缺资料与使用限制

1. 逐条专项意见及实际提供的填写者、日期和使用范围；五问整体认可不能代替。
2. 八课具体动作、练习顺序、保护、分层、先修与评价量规的专业及现场确认。
3. 其他候选的原页、教材版权页/版次与完整页序；不外推P3.4片段之外的内容。
4. 教学PPT、可分发且获授权的示范视频和图示。
5. 实际教师验收返回材料、真实授课及学生观察；本次均未发生。
6. 学习通学校租户权限、支持格式、官方模板、人工导入和发布验收。

这些缺项阻塞正式专项技术教学和平台发布，不阻塞本次待审核课程展示包的代码/材料审阅。

## 实际修改文件

- `.gitignore`：仅为本次空白L05教师送审Word设置单文件例外；扫描、真实意见和本地数据仍排除。
- `scripts/prepare_course_mvp.py`：复用本地API生成课程阅读包，只用临时SQLite；可选Word排版。
- `scripts/verify_l05_application_browser.py`：增加八课及反馈草稿的课程展示验收；浏览器JS异常直接报告。
- `tests/test_course_mvp_acceptance.py`：10项课程交付一致性、来源、状态与Word检查。
- `docs/course-mvp/L01-draft.md`至`L08-draft.md`：8份45分钟草稿。
- `docs/course-mvp/L05-teacher-review.md`、`L05-teacher-review.docx`：最终教师送审版，未批准。
- `docs/course-mvp/course-inventory.json`：八课实际API输出的阅读投影与来源摘要绑定。
- `docs/course-mvp/resource-catalog.json`：8课资源文件、准备状态及缺项。
- `docs/course-mvp/teacher-feedback-form.md`：空白教师验收反馈表。
- `docs/course-mvp/demo-runbook.md`：展示脚本、保存生命周期和失败处理。
- `docs/course-mvp/xuexitong-resources.md`：资源与人工导入建议。
- `docs/course-mvp/README.md`：简洁完成度与交付入口。
- `docs/course-mvp/acceptance-report.md`：本报告。

本轮没有修改知识条目、审核声明/决定、课程目录、应用API、生产数据库、mock隔离或视频算法。
教材扫描、真实反馈、SQLite、完整备份及私钥均未提交。未合并或部署。
